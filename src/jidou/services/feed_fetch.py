"""Fetch an RSS/Atom feed and reduce it to plain entries.

The backend never persisted or parsed feed content before: YaRSS2 on the
Deluge host does the real fetching. This service exists so the UI can show what
a feed actually publishes (e.g. to onboard a show from real release titles).

Design constraints:

* **Bytes only into the parser.** The body is fetched here with ``httpx2`` so
  the address guard, timeouts, size cap and redirect re-validation always
  apply; ``feedparser`` is never given a URL (it would fetch with ``urllib``
  and bypass all of that).
* **Connect to the address we validated.** The host is resolved once, every
  resolved address is checked, and the request is sent to that literal IP with
  the original ``Host`` header and TLS SNI. A hostile DNS server therefore
  cannot return a public address for the check and a blocked one for the
  connect (DNS rebinding).
* **Feed URLs are secrets.** Private-tracker URLs embed passkeys/API keys in
  the query string *or the path*. Nothing here logs, caches under a label, or
  puts a URL beyond ``scheme://host`` in an exception message. Entry links are
  dropped entirely for the same reason (torznab links carry the indexer key).
* **Lenient parsing.** Real tracker feeds routinely contain bare ``&`` and
  other XML sins; ``feedparser`` recovers what it can and we report that the
  feed was malformed rather than failing.
"""

import asyncio
import contextvars
import functools
import hashlib
import ipaddress
import logging
import re
import socket
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlsplit

import feedparser
import httpx2 as httpx
from redis.exceptions import RedisError

from jidou.services.cache import CacheBackend, cache
from jidou.services.rate_limiter import RateLimiter, feed_rate_limiter

logger = logging.getLogger(__name__)

MAX_FEED_BYTES = 5 * 1024 * 1024
MAX_ENTRIES = 200
FETCH_TIMEOUT_SECONDS = 15.0  # per connect/read/write operation
TOTAL_DEADLINE_SECONDS = 30.0  # whole fetch, all redirects and the body read
MAX_REDIRECTS = 3
CACHE_TTL_SECONDS = 300

_CACHE_KEY_PREFIX = "rss_feed_entries:"
_USER_AGENT = "Jidou/1.0 (+RSS feed browser)"
_ACCEPT = (
    "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5"
)

# Set while a feed request is in flight so the HTTP client's own log lines can
# be scrubbed down to scheme://host (see _RedactUrlsFilter).
_in_feed_fetch: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "jidou_in_feed_fetch", default=False
)

_URL_TOKEN = re.compile(r"https?://[^\s\"']+")


def redact_url(url: str) -> str:
    """Return only ``scheme://host[:port]`` of *url*, for logs and labels.

    Path and query are both dropped: trackers embed the passkey in either
    (``/rss/<passkey>``, ``?passkey=...``), and userinfo may carry credentials.

    Args:
        url: A feed URL that may embed credentials.

    Returns:
        ``scheme://host[:port]``, or ``"<invalid url>"`` if it cannot be parsed.
    """
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if ":" in host:  # IPv6 literal
            host = f"[{host}]"
        port = parts.port
    except ValueError:
        return "<invalid url>"
    return f"{parts.scheme}://{host}" + (f":{port}" if port else "")


class _RedactUrlsFilter(logging.Filter):
    """Scrub URLs in log lines emitted by the HTTP client.

    ``httpx2`` logs every request at INFO as ``HTTP Request: GET <full url>``.
    Always: userinfo and query strings are removed. While a feed fetch is in
    flight (``_in_feed_fetch``), the path is dropped too, because feed URLs may
    carry the passkey there. Other callers (e.g. TMDB, whose ``api_key`` rides
    in the query string) keep their paths for debugging.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        drop_path = _in_feed_fetch.get()

        def _scrub(match: re.Match[str]) -> str:
            url = match.group(0)
            if drop_path:
                return redact_url(url)
            try:
                parts = urlsplit(url)
            except ValueError:
                return "<invalid url>"
            return redact_url(url) + parts.path

        record.msg = _URL_TOKEN.sub(_scrub, record.getMessage())
        record.args = None
        return True


def _install_http_log_redaction() -> None:
    http_logger = logging.getLogger("httpx2")
    if not any(isinstance(f, _RedactUrlsFilter) for f in http_logger.filters):
        http_logger.addFilter(_RedactUrlsFilter())


_install_http_log_redaction()


class FeedFetchError(Exception):
    """A feed could not be fetched or is not a feed.

    Messages are safe to show to the user: they never contain more of the feed
    URL than its host.

    Attributes:
        timed_out: True when the failure was a timeout (maps to HTTP 504).
    """

    def __init__(self, message: str, *, timed_out: bool = False) -> None:
        super().__init__(message)
        self.timed_out = timed_out


@dataclass(frozen=True)
class FeedEntry:
    """One entry of a feed, reduced to what Jidou needs.

    Attributes:
        title: Release title as published.
        guid: Feed-supplied stable identifier, if any.
        published: ISO 8601 UTC timestamp, if the feed supplied a parseable one.
    """

    title: str
    guid: str | None
    published: str | None


@dataclass(frozen=True)
class FeedFetchResult:
    """Outcome of one feed fetch.

    Attributes:
        entries: Parsed entries, newest-first as published, capped at
            :data:`MAX_ENTRIES`.
        malformed: True when the XML was not well-formed and entries may be
            incomplete.
        cached: True when served from the short-lived cache.
        truncated: True when the feed had more than :data:`MAX_ENTRIES` entries.
    """

    entries: list[FeedEntry]
    malformed: bool
    cached: bool
    truncated: bool = False


# Cloud metadata endpoints outside the link-local range.
_EXTRA_BLOCKED_NETWORKS = (
    ipaddress.ip_network("100.100.100.200/32"),  # Alibaba Cloud metadata
    ipaddress.ip_network("fd00:ec2::/64"),  # AWS IPv6 IMDS
)
_NAT64 = ipaddress.ip_network("64:ff9b::/96")


def _embedded_ipv4(ip: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    """Return the IPv4 address an IPv6 address tunnels, if it embeds one."""
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip.sixtofour is not None:
        return ip.sixtofour
    if ip in _NAT64:
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return None


def _blocked_address(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Whether *ip* must never be fetched.

    Private (RFC 1918) and loopback addresses are deliberately *allowed*:
    self-hosted Jackett/Prowlarr on the LAN is the common case. Link-local
    (which includes the 169.254.169.254 cloud metadata endpoint), multicast,
    unspecified, reserved and known metadata ranges are not. IPv6 forms that
    tunnel an IPv4 address (mapped, 6to4, NAT64) are judged by the embedded
    IPv4 address.
    """
    if isinstance(ip, ipaddress.IPv6Address):
        embedded = _embedded_ipv4(ip)
        if embedded is not None:
            return _blocked_address(embedded)
    if any(ip in net for net in _EXTRA_BLOCKED_NETWORKS if net.version == ip.version):
        return True
    return ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved


async def _resolve_validated(url: str) -> tuple[str, str]:
    """Validate *url* and return the address to connect to.

    Resolves the host once, requires **every** resolved address to be
    routable-enough per :func:`_blocked_address`, and returns the first one so
    the caller can connect to exactly the address that was checked.

    Args:
        url: The URL about to be requested.

    Returns:
        ``(ip, hostname)``: the validated IP literal and the original hostname.

    Raises:
        FeedFetchError: If the scheme is not http(s), the host is missing,
            invalid or unresolvable, or any resolved address is blocked.
    """
    try:
        parts = urlsplit(url)
        hostname = parts.hostname
        port = parts.port
    except ValueError:
        raise FeedFetchError("Feed URL is not valid") from None
    if parts.scheme not in ("http", "https") or not hostname:
        raise FeedFetchError("Feed URL must be an http(s) URL")
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise FeedFetchError(f"Could not resolve feed host {hostname!r}") from None
    except (UnicodeError, ValueError):
        raise FeedFetchError("Feed URL host is not valid") from None
    if not infos:
        raise FeedFetchError(f"Could not resolve feed host {hostname!r}")
    addresses = [ipaddress.ip_address(info[4][0]) for info in infos]
    for ip in addresses:
        if _blocked_address(ip):
            logger.warning("Blocked feed fetch to non-routable address host=%s", hostname)
            raise FeedFetchError("Feed host resolves to a blocked address range")
    return str(addresses[0]), hostname


def _struct_time_to_iso(value: Any) -> str | None:
    """Convert feedparser's UTC ``struct_time`` to ISO 8601, or None."""
    if not value:
        return None
    try:
        year, month, day, hour, minute, second = value[:6]
        return datetime(year, month, day, hour, minute, second, tzinfo=UTC).isoformat()
    except (TypeError, ValueError):
        return None


def parse_feed_bytes(data: bytes) -> FeedFetchResult:
    """Parse feed bytes into entries (synchronous, CPU-bound).

    Args:
        data: Raw response body.

    Returns:
        Parsed result with ``cached=False``.

    Raises:
        FeedFetchError: If feedparser did not recognise a feed format (e.g.
            an HTML error or challenge page, which it accepts silently).
    """
    parsed = feedparser.parse(data)
    # ``version`` is feedparser's detected format ("rss20", "atom10", ...) and
    # is empty for anything that isn't a feed. Recoverable-but-malformed feeds
    # still report their format, so this does not reject them. A title is *not*
    # a safe signal: HTML error/challenge pages carry a <title> too.
    if not parsed.get("version"):
        raise FeedFetchError("Response was not an RSS or Atom feed")

    entries: list[FeedEntry] = []
    for raw in parsed.entries:
        title = (raw.get("title") or "").strip()
        if not title:
            continue
        entries.append(
            FeedEntry(
                title=title,
                guid=raw.get("id") or None,
                published=_struct_time_to_iso(raw.get("published_parsed")),
            )
        )

    exc = parsed.get("bozo_exception")
    # CharacterEncodingOverride only means the declared encoding was corrected;
    # the content is intact.
    malformed = bool(parsed.get("bozo")) and not isinstance(
        exc, feedparser.CharacterEncodingOverride
    )
    truncated = len(entries) > MAX_ENTRIES
    return FeedFetchResult(
        entries=entries[:MAX_ENTRIES], malformed=malformed, cached=False, truncated=truncated
    )


class FeedFetchService:
    """Fetches and parses RSS/Atom feeds with SSRF, size, time and rate guards.

    Concurrent requests for the same feed URL share one in-flight fetch.

    Args:
        limiter: Shared outbound rate limiter.
        cache_backend: Cache used for the short-lived entry cache.
        client_factory: Builds the ``httpx.AsyncClient`` (injectable for tests).
    """

    def __init__(
        self,
        limiter: RateLimiter = feed_rate_limiter,
        cache_backend: CacheBackend = cache,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self._limiter = limiter
        self._cache = cache_backend
        self._client_factory = client_factory or self._default_client
        self._inflight: dict[str, asyncio.Task[FeedFetchResult]] = {}

    @staticmethod
    def _default_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=FETCH_TIMEOUT_SECONDS,
            follow_redirects=False,  # redirects are followed manually and re-validated
            headers={"User-Agent": _USER_AGENT, "Accept": _ACCEPT},
        )

    @staticmethod
    def _cache_key(url: str) -> str:
        # Hash the full URL (path and query select the feed content) but never
        # store or label it in the clear.
        return _CACHE_KEY_PREFIX + hashlib.sha256(url.encode()).hexdigest()

    async def fetch_entries(self, url: str, *, bypass_cache: bool = False) -> FeedFetchResult:
        """Return the entries of the feed at *url*.

        Args:
            url: Feed URL (may embed credentials; never logged).
            bypass_cache: Skip the cache read and refetch. The fresh result
                still refreshes the cache.

        Returns:
            Parsed feed entries.

        Raises:
            FeedFetchError: On an invalid/blocked URL, transport failure,
                timeout, non-2xx response, oversize body, or a non-feed body.
        """
        key = self._cache_key(url)

        if not bypass_cache:
            hit = await self._cache_get(key)
            if hit is not None:
                logger.debug("Feed cache hit feed=%s", redact_url(url))
                return hit

        task = self._inflight.get(key)
        if task is None:
            task = asyncio.create_task(self._fetch_and_cache(url, key))
            self._inflight[key] = task
            task.add_done_callback(functools.partial(self._on_done, key))
        # shield: one caller disconnecting must not cancel the fetch the
        # others are waiting on.
        return await asyncio.shield(task)

    def _on_done(self, key: str, task: "asyncio.Task[FeedFetchResult]") -> None:
        self._inflight.pop(key, None)
        if not task.cancelled():
            task.exception()  # mark retrieved; waiters re-raise it themselves

    async def _fetch_and_cache(self, url: str, key: str) -> FeedFetchResult:
        label = redact_url(url)
        started = time.monotonic()
        body = await self._download(url)
        result = await asyncio.to_thread(parse_feed_bytes, body)
        logger.info(
            "Fetched feed feed=%s entries=%d malformed=%s bytes=%d elapsed_ms=%d",
            label,
            len(result.entries),
            result.malformed,
            len(body),
            int((time.monotonic() - started) * 1000),
        )
        await self._cache_set(key, label, result)
        return result

    async def _download(self, url: str) -> bytes:
        """GET *url* following up to :data:`MAX_REDIRECTS` validated redirects."""
        token = _in_feed_fetch.set(True)
        try:
            async with self._limiter.acquire(), self._client_factory() as client:
                try:
                    # Deadline starts after the rate-limiter wait, so a queued
                    # request is not penalised for waiting its turn.
                    async with asyncio.timeout(TOTAL_DEADLINE_SECONDS):
                        return await self._follow_redirects(client, url)
                except TimeoutError:
                    raise FeedFetchError("Timed out fetching feed", timed_out=True) from None
        finally:
            _in_feed_fetch.reset(token)

    async def _follow_redirects(self, client: httpx.AsyncClient, url: str) -> bytes:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            ip, hostname = await _resolve_validated(current)
            try:
                target = httpx.URL(current)
                headers = {"Host": target.netloc.decode().rsplit("@", 1)[-1]}
                extensions: dict[str, Any] = (
                    {"sni_hostname": hostname} if target.scheme == "https" else {}
                )
                pinned = target.copy_with(host=ip)
                async with client.stream(
                    "GET", pinned, headers=headers, extensions=extensions
                ) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise FeedFetchError("Feed redirect had no Location header")
                        try:
                            current = urljoin(current, location)
                        except ValueError:
                            raise FeedFetchError("Feed redirect target is not valid") from None
                        continue
                    if response.status_code >= 400:
                        raise FeedFetchError(f"Feed server returned HTTP {response.status_code}")
                    return await self._read_capped(response)
            except httpx.TimeoutException:
                raise FeedFetchError("Timed out fetching feed", timed_out=True) from None
            except httpx.InvalidURL:
                raise FeedFetchError("Feed URL is not valid") from None
            except httpx.HTTPError as exc:
                # httpx messages can embed the full URL; report the class only.
                logger.warning(
                    "Feed transport error feed=%s error=%s",
                    redact_url(current),
                    type(exc).__name__,
                )
                raise FeedFetchError("Could not fetch feed (connection error)") from None
        raise FeedFetchError("Too many redirects fetching feed")

    @staticmethod
    async def _read_capped(response: httpx.Response) -> bytes:
        """Read the body, aborting once it exceeds :data:`MAX_FEED_BYTES`."""
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > MAX_FEED_BYTES:
                raise FeedFetchError("Feed is larger than the 5 MB limit")
            chunks.append(chunk)
        return b"".join(chunks)

    async def _cache_get(self, key: str) -> FeedFetchResult | None:
        try:
            raw = await self._cache.get(key)
        except (RedisError, OSError) as exc:
            logger.warning("Feed cache read failed error=%s", type(exc).__name__)
            return None
        if raw is None:
            return None
        return FeedFetchResult(
            entries=[FeedEntry(**e) for e in raw["entries"]],
            malformed=raw["malformed"],
            cached=True,
            truncated=raw.get("truncated", False),
        )

    async def _cache_set(self, key: str, label: str, result: FeedFetchResult) -> None:
        payload = {
            "entries": [asdict(e) for e in result.entries],
            "malformed": result.malformed,
            "truncated": result.truncated,
        }
        try:
            await self._cache.set(key, payload, label=f"rss feed {label}", ttl=CACHE_TTL_SECONDS)
        except (RedisError, OSError) as exc:
            logger.warning("Feed cache write failed error=%s", type(exc).__name__)
