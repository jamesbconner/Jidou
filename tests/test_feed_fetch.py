"""Tests for the RSS feed fetch service."""

import logging
import socket
from unittest.mock import AsyncMock, patch

import httpx2 as httpx
import pytest

from jidou.services import feed_fetch
from jidou.services.feed_fetch import (
    MAX_ENTRIES,
    MAX_FEED_BYTES,
    FeedFetchError,
    FeedFetchService,
    parse_feed_bytes,
    redact_url,
)
from jidou.services.rate_limiter import RateLimiter

SECRET_URL = "https://tracker.example/rss?passkey=SUPERSECRET&u=bob"

_HDR = '<?xml version="1.0" encoding="UTF-8"?>\n'


def _rss(items: str, channel_extra: str = "") -> bytes:
    return (
        _HDR
        + '<rss version="2.0"><channel><title>T</title><link>http://x</link>'
        + f"<description>d</description>{channel_extra}{items}</channel></rss>"
    ).encode()


def _item(title: str, n: int = 1, extra: str = "") -> str:
    return f"<item><title>{title}</title><link>http://x/{n}?apikey=K</link><guid>g{n}</guid>{extra}</item>"


# ---------------------------------------------------------------------------
# parse_feed_bytes
# ---------------------------------------------------------------------------


def test_parse_clean_feed_extracts_title_guid_and_iso_published() -> None:
    data = _rss(
        _item(
            "[Grp] Show - 01 (1080p).mkv", 1, "<pubDate>Fri, 03 Oct 2026 14:00:00 +0000</pubDate>"
        )
    )

    result = parse_feed_bytes(data)

    assert [e.title for e in result.entries] == ["[Grp] Show - 01 (1080p).mkv"]
    assert result.entries[0].guid == "g1"
    assert result.entries[0].published == "2026-10-03T14:00:00+00:00"
    assert result.malformed is False
    assert result.cached is False


def test_parse_never_exposes_entry_links() -> None:
    result = parse_feed_bytes(_rss(_item("Show - 01")))

    assert not hasattr(result.entries[0], "link")
    assert "apikey" not in repr(result)


def test_parse_recovers_from_bare_ampersand_and_flags_malformed() -> None:
    data = _rss(_item("Tom & Jerry - 01") + _item("Fine Show - 02", 2))

    result = parse_feed_bytes(data)

    assert [e.title for e in result.entries] == ["Tom & Jerry - 01", "Fine Show - 02"]
    assert result.malformed is True


def test_parse_keeps_item_lacking_nothing_but_skips_blank_titles() -> None:
    data = _rss("<item><link>http://x/1</link></item>" + _item("Good - 05", 2))

    result = parse_feed_bytes(data)

    assert [e.title for e in result.entries] == ["Good - 05"]


def test_parse_html_error_page_is_not_a_feed() -> None:
    with pytest.raises(FeedFetchError, match="not an RSS or Atom feed"):
        parse_feed_bytes(b"<html><body><h1>503 Service Unavailable</h1></body></html>")


def test_parse_empty_feed_with_title_is_valid_and_empty() -> None:
    result = parse_feed_bytes(_rss(""))

    assert result.entries == []
    assert result.malformed is False


def test_parse_caps_entries_and_reports_truncation() -> None:
    items = "".join(_item(f"Show - {i:03d}", i) for i in range(MAX_ENTRIES + 25))

    result = parse_feed_bytes(_rss(items))

    assert len(result.entries) == MAX_ENTRIES
    assert result.truncated is True


def test_parse_encoding_override_is_not_flagged_malformed() -> None:
    body = (
        '<?xml version="1.0" encoding="windows-1251"?>\n<rss version="2.0"><channel>'
        "<title>T</title><link>http://x</link><description>d</description>"
        "<item><title>Привет - 01</title><link>http://x/1</link></item></channel></rss>"
    ).encode("cp1251")

    result = parse_feed_bytes(body)

    assert result.entries[0].title == "Привет - 01"
    assert result.malformed is False


def test_parse_external_entity_is_not_expanded(tmp_path) -> None:
    canary = tmp_path / "secret.txt"
    canary.write_text("TOP-SECRET-CANARY")
    data = (
        f'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "{canary.as_uri()}">]>'
        '<rss version="2.0"><channel><title>&x;</title><link>http://x</link>'
        "<description>d</description><item><title>&x;</title></item></channel></rss>"
    ).encode()

    try:
        result = parse_feed_bytes(data)
    except FeedFetchError:
        return  # refused outright is also acceptable
    assert "CANARY" not in repr(result)


# ---------------------------------------------------------------------------
# redact_url
# ---------------------------------------------------------------------------


def test_redact_url_keeps_only_scheme_and_host() -> None:
    assert redact_url("https://user:pw@tracker.example:8443/rss/PASSKEY123/feed?k=S") == (
        "https://tracker.example:8443"
    )


def test_redact_url_ipv6_and_garbage() -> None:
    assert redact_url("http://[2606:2800::1]:8080/x?k=1") == "http://[2606:2800::1]:8080"
    assert redact_url("http://[bad") == "<invalid url>"


# ---------------------------------------------------------------------------
# Address guard
# ---------------------------------------------------------------------------


def _addrinfo(*ips: str) -> list[tuple]:
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in ips]


@pytest.mark.parametrize("ip", ["10.0.0.5", "192.168.1.20", "127.0.0.1", "93.184.216.34"])
async def test_assert_fetchable_allows_private_loopback_and_public(ip: str) -> None:
    with patch("asyncio.BaseEventLoop.getaddrinfo", new=AsyncMock(return_value=_addrinfo(ip))):
        await feed_fetch._resolve_validated("http://indexer.lan/api")


@pytest.mark.parametrize(
    "ip", ["169.254.169.254", "0.0.0.0", "224.0.0.1", "240.0.0.1", "100.100.100.200"]
)
async def test_assert_fetchable_blocks_link_local_multicast_unspecified_reserved(ip: str) -> None:
    with (
        patch("asyncio.BaseEventLoop.getaddrinfo", new=AsyncMock(return_value=_addrinfo(ip))),
        pytest.raises(FeedFetchError, match="blocked address"),
    ):
        await feed_fetch._resolve_validated("http://rebind.example/feed")


async def test_assert_fetchable_blocks_if_any_resolved_address_is_blocked() -> None:
    with (
        patch(
            "asyncio.BaseEventLoop.getaddrinfo",
            new=AsyncMock(return_value=_addrinfo("93.184.216.34", "169.254.169.254")),
        ),
        pytest.raises(FeedFetchError, match="blocked address"),
    ):
        await feed_fetch._resolve_validated("http://mixed.example/feed")


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://x/feed", "gopher://x", "http://"])
async def test_assert_fetchable_rejects_non_http_schemes(url: str) -> None:
    with pytest.raises(FeedFetchError, match="http"):
        await feed_fetch._resolve_validated(url)


async def test_assert_fetchable_unresolvable_host() -> None:
    with (
        patch("asyncio.BaseEventLoop.getaddrinfo", new=AsyncMock(side_effect=socket.gaierror)),
        pytest.raises(FeedFetchError, match="Could not resolve"),
    ):
        await feed_fetch._resolve_validated("http://nope.invalid/feed")


# ---------------------------------------------------------------------------
# FeedFetchService
# ---------------------------------------------------------------------------


class _FakeCache:
    def __init__(self) -> None:
        self.store: dict[str, object] = {}
        self.set_calls: list[tuple[str, str | None, int | None]] = []

    async def get(self, key: str) -> object | None:
        return self.store.get(key)

    async def set(self, key: str, value: object, label: str | None = None, ttl: int | None = None):
        self.store[key] = value
        self.set_calls.append((key, label, ttl))


def _service(handler, cache: _FakeCache | None = None) -> tuple[FeedFetchService, _FakeCache]:
    fake = cache or _FakeCache()

    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)

    svc = FeedFetchService(
        limiter=RateLimiter(rate=2.0),
        cache_backend=fake,
        client_factory=factory,  # type: ignore[arg-type]
    )
    return svc, fake


@pytest.fixture(autouse=True)
def _public_dns():
    """Resolve every host to a routable public address unless a test overrides."""
    with patch(
        "asyncio.BaseEventLoop.getaddrinfo", new=AsyncMock(return_value=_addrinfo("93.184.216.34"))
    ) as m:
        yield m


async def test_fetch_entries_success_and_caches_under_redacted_label() -> None:
    svc, cache = _service(lambda req: httpx.Response(200, content=_rss(_item("Show - 01"))))

    result = await svc.fetch_entries(SECRET_URL)

    assert [e.title for e in result.entries] == ["Show - 01"]
    assert result.cached is False
    (key, label, ttl) = cache.set_calls[0]
    assert "SUPERSECRET" not in key and "SUPERSECRET" not in (label or "")
    assert label == "rss feed https://tracker.example"
    assert ttl == feed_fetch.CACHE_TTL_SECONDS


async def test_fetch_entries_serves_from_cache_without_http() -> None:
    calls = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=_rss(_item("Show - 01")))

    svc, _ = _service(handler)
    await svc.fetch_entries(SECRET_URL)
    second = await svc.fetch_entries(SECRET_URL)

    assert calls == 1
    assert second.cached is True
    assert [e.title for e in second.entries] == ["Show - 01"]


async def test_fetch_entries_bypass_cache_refetches() -> None:
    calls = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=_rss(_item(f"Show - {calls:02d}")))

    svc, _ = _service(handler)
    await svc.fetch_entries(SECRET_URL)
    fresh = await svc.fetch_entries(SECRET_URL, bypass_cache=True)

    assert calls == 2
    assert fresh.cached is False
    assert fresh.entries[0].title == "Show - 02"


async def test_fetch_entries_http_error_message_has_no_url(caplog) -> None:
    svc, _ = _service(lambda req: httpx.Response(403))

    with (
        caplog.at_level(logging.DEBUG),
        pytest.raises(FeedFetchError, match="HTTP 403") as exc_info,
    ):
        await svc.fetch_entries(SECRET_URL)

    assert "SUPERSECRET" not in str(exc_info.value)
    assert "SUPERSECRET" not in caplog.text


async def test_fetch_entries_timeout_sets_timed_out_and_hides_url(caplog) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=req)

    svc, _ = _service(handler)

    with caplog.at_level(logging.DEBUG), pytest.raises(FeedFetchError) as exc_info:
        await svc.fetch_entries(SECRET_URL)

    assert exc_info.value.timed_out is True
    assert "SUPERSECRET" not in caplog.text


async def test_fetch_entries_transport_error_hides_url(caplog) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"connect failed for {req.url}", request=req)

    svc, _ = _service(handler)

    with caplog.at_level(logging.DEBUG), pytest.raises(FeedFetchError) as exc_info:
        await svc.fetch_entries(SECRET_URL)

    assert exc_info.value.timed_out is False
    assert "SUPERSECRET" not in str(exc_info.value)
    assert "SUPERSECRET" not in caplog.text


async def test_fetch_entries_rejects_oversize_body() -> None:
    big = b"x" * (MAX_FEED_BYTES + 1)
    svc, _ = _service(lambda req: httpx.Response(200, content=big))

    with pytest.raises(FeedFetchError, match="5 MB"):
        await svc.fetch_entries(SECRET_URL)


async def test_fetch_entries_html_body_is_not_a_feed() -> None:
    svc, _ = _service(
        lambda req: httpx.Response(200, content=b"<html><body>Just a moment</body></html>")
    )

    with pytest.raises(FeedFetchError, match="not an RSS or Atom feed"):
        await svc.fetch_entries(SECRET_URL)


async def test_fetch_entries_follows_redirect_to_new_host() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.headers["host"] == "tracker.example":
            return httpx.Response(302, headers={"location": "https://cdn.example/feed.xml"})
        return httpx.Response(200, content=_rss(_item("Show - 01")))

    svc, _ = _service(handler)

    result = await svc.fetch_entries(SECRET_URL)

    assert [e.title for e in result.entries] == ["Show - 01"]


async def test_fetch_entries_revalidates_redirect_target(_public_dns) -> None:
    async def resolver(host: str, *a, **k):
        return _addrinfo("169.254.169.254" if host == "metadata.internal" else "93.184.216.34")

    _public_dns.side_effect = resolver

    def handler(req: httpx.Request) -> httpx.Response:
        if req.headers["host"] == "tracker.example":
            return httpx.Response(301, headers={"location": "http://metadata.internal/latest"})
        pytest.fail("redirect target must not be requested")

    svc, _ = _service(handler)

    with pytest.raises(FeedFetchError, match="blocked address"):
        await svc.fetch_entries(SECRET_URL)


async def test_fetch_entries_too_many_redirects() -> None:
    svc, _ = _service(
        lambda req: httpx.Response(302, headers={"location": "https://tracker.example/again"})
    )

    with pytest.raises(FeedFetchError, match="Too many redirects"):
        await svc.fetch_entries(SECRET_URL)


async def test_fetch_entries_redirect_without_location() -> None:
    svc, _ = _service(lambda req: httpx.Response(302))

    with pytest.raises(FeedFetchError, match="Location"):
        await svc.fetch_entries(SECRET_URL)


async def test_cache_failure_is_non_fatal(caplog) -> None:
    class _BrokenCache(_FakeCache):
        async def get(self, key: str) -> object | None:
            raise OSError("redis down")

        async def set(self, *a, **k) -> None:
            raise OSError("redis down")

    svc, _ = _service(
        lambda req: httpx.Response(200, content=_rss(_item("Show - 01"))), _BrokenCache()
    )

    with caplog.at_level(logging.WARNING):
        result = await svc.fetch_entries(SECRET_URL)

    assert [e.title for e in result.entries] == ["Show - 01"]
    assert "cache read failed" in caplog.text
    assert "cache write failed" in caplog.text


# ---------------------------------------------------------------------------
# Hardening: blocklist gaps, pinning, deadline, path secrets, dedupe
# ---------------------------------------------------------------------------


def _addrinfo6(*ips: str) -> list[tuple]:
    return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ip, 0, 0, 0)) for ip in ips]


@pytest.mark.parametrize(
    "ip",
    [
        "::ffff:169.254.169.254",  # IPv4-mapped
        "2002:a9fe:a9fe::1",  # 6to4 embedding 169.254.169.254
        "64:ff9b::a9fe:a9fe",  # NAT64 embedding 169.254.169.254
        "fd00:ec2::254",  # AWS IPv6 IMDS
        "fe80::1",  # link-local v6
    ],
)
async def test_blocks_ipv6_forms_of_blocked_targets(ip: str) -> None:
    with (
        patch("asyncio.BaseEventLoop.getaddrinfo", new=AsyncMock(return_value=_addrinfo6(ip))),
        pytest.raises(FeedFetchError, match="blocked address"),
    ):
        await feed_fetch._resolve_validated("http://v6.example/feed")


async def test_allows_ipv6_embedding_a_private_v4() -> None:
    with patch(
        "asyncio.BaseEventLoop.getaddrinfo",
        new=AsyncMock(return_value=_addrinfo6("::ffff:192.168.1.5")),
    ):
        _ip, host = await feed_fetch._resolve_validated("http://lan.example/feed")
    assert host == "lan.example"


@pytest.mark.parametrize("exc", [UnicodeError("bad label"), ValueError("embedded null")])
async def test_resolver_unicode_and_value_errors_become_feed_errors(exc: Exception) -> None:
    with (
        patch("asyncio.BaseEventLoop.getaddrinfo", new=AsyncMock(side_effect=exc)),
        pytest.raises(FeedFetchError, match="not valid"),
    ):
        await feed_fetch._resolve_validated("http://weird.example/feed")


async def test_request_is_pinned_to_the_validated_ip_with_host_and_sni() -> None:
    seen: dict[str, object] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["connect_host"] = req.url.host
        seen["host_header"] = req.headers["host"]
        seen["sni"] = req.extensions.get("sni_hostname")
        return httpx.Response(200, content=_rss(_item("Show - 01")))

    svc, _ = _service(handler)
    await svc.fetch_entries("https://tracker.example:8443/rss/PASSKEY?k=1")

    assert seen == {
        "connect_host": "93.184.216.34",
        "host_header": "tracker.example:8443",
        "sni": "tracker.example",
    }


async def test_dns_is_resolved_once_per_hop_so_rebinding_cannot_swap_the_target(
    _public_dns,
) -> None:
    answers = iter([_addrinfo("93.184.216.34"), _addrinfo("169.254.169.254")])

    async def resolver(*_a, **_k):
        return next(answers)

    _public_dns.side_effect = resolver
    connected: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        connected.append(req.url.host)
        return httpx.Response(200, content=_rss(_item("Show - 01")))

    svc, _ = _service(handler)
    await svc.fetch_entries(SECRET_URL)

    assert connected == ["93.184.216.34"]  # never the second, hostile answer


async def test_total_deadline_maps_to_timeout(monkeypatch) -> None:
    import asyncio

    monkeypatch.setattr(feed_fetch, "TOTAL_DEADLINE_SECONDS", 0.05)

    async def slow(req: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1)
        return httpx.Response(200, content=_rss(""))

    svc, _ = _service(slow)

    with pytest.raises(FeedFetchError) as exc_info:
        await svc.fetch_entries(SECRET_URL)

    assert exc_info.value.timed_out is True


async def test_invalid_redirect_location_is_a_clean_error() -> None:
    svc, _ = _service(lambda req: httpx.Response(302, headers={"location": "http://[bad"}))

    with pytest.raises(FeedFetchError, match="not valid"):
        await svc.fetch_entries(SECRET_URL)


async def test_path_embedded_passkey_never_reaches_logs_labels_or_errors(caplog) -> None:
    url = "https://tracker.example/rss/PATHPASSKEY123/feed.xml"
    svc, cache = _service(lambda req: httpx.Response(200, content=_rss(_item("Show - 01"))))

    with caplog.at_level(logging.DEBUG):
        await svc.fetch_entries(url)

    assert "PATHPASSKEY123" not in caplog.text
    assert all("PATHPASSKEY123" not in (label or "") for _k, label, _t in cache.set_calls)
    assert all("PATHPASSKEY123" not in k for k, _l, _t in cache.set_calls)


def test_http_log_filter_scrubs_path_only_during_a_feed_fetch() -> None:
    f = feed_fetch._RedactUrlsFilter()

    def run(msg: str) -> str:
        rec = logging.LogRecord("httpx2", logging.INFO, __file__, 1, msg, None, None)
        f.filter(rec)
        return str(rec.msg)

    line = 'HTTP Request: GET https://u:p@t.example/rss/KEY?passkey=S "HTTP/1.1 200 OK"'

    outside = run(line)
    assert "passkey" not in outside and "u:p@" not in outside
    assert "/rss/KEY" in outside  # TMDB-style callers keep their path for debugging

    token = feed_fetch._in_feed_fetch.set(True)
    try:
        inside = run(line)
    finally:
        feed_fetch._in_feed_fetch.reset(token)
    assert "KEY" not in inside and "/rss" not in inside
    assert "https://t.example" in inside


async def test_concurrent_requests_for_one_feed_share_a_single_fetch() -> None:
    import asyncio

    calls = 0

    async def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return httpx.Response(200, content=_rss(_item("Show - 01")))

    svc, _ = _service(handler)

    a, b, c = await asyncio.gather(
        svc.fetch_entries(SECRET_URL),
        svc.fetch_entries(SECRET_URL, bypass_cache=True),
        svc.fetch_entries(SECRET_URL, bypass_cache=True),
    )

    assert calls == 1
    assert a.entries == b.entries == c.entries


async def test_inflight_failure_propagates_to_every_waiter_and_is_cleared() -> None:
    import asyncio

    calls = 0

    async def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.02)
        return httpx.Response(500)

    svc, _ = _service(handler)

    results = await asyncio.gather(
        svc.fetch_entries(SECRET_URL),
        svc.fetch_entries(SECRET_URL, bypass_cache=True),
        return_exceptions=True,
    )

    assert calls == 1
    assert all(isinstance(r, FeedFetchError) for r in results)
    assert svc._inflight == {}


@pytest.mark.parametrize(
    "body",
    [
        b"<html><head><title>Just a moment...</title></head><body>x</body></html>",
        b'<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><head>'
        b"<title>Login</title></head><body/></html>",
        b'<?xml version="1.0"?><root><title>Just a title</title></root>',
        b'{"title": "not xml at all"}',
    ],
)
def test_parse_non_feed_documents_with_a_title_are_rejected(body: bytes) -> None:
    with pytest.raises(FeedFetchError, match="not an RSS or Atom feed"):
        parse_feed_bytes(body)


@pytest.mark.parametrize(
    "body",
    [
        # whitespace before the XML declaration
        b"\n  " + _rss(_item("Ws - 01")),
        # body cut off mid-item
        (
            _HDR + '<rss version="2.0"><channel><title>T</title><item><title>Cut - 01</title>'
            "<link>http://x/1"
        ).encode(),
        # Atom and RSS 1.0 (RDF)
        b'<feed xmlns="http://www.w3.org/2005/Atom"><title>A</title><id>u</id>'
        b"<entry><title>E - 01</title><id>e</id></entry></feed>",
        b'<?xml version="1.0"?><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
        b'xmlns="http://purl.org/rss/1.0/"><channel><title>R</title></channel>'
        b"<item><title>I - 01</title></item></rdf:RDF>",
    ],
)
def test_parse_recoverable_and_alternate_formats_are_still_feeds(body: bytes) -> None:
    result = parse_feed_bytes(body)

    assert len(result.entries) == 1
