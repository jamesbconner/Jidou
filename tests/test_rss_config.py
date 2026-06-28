"""Tests for the RSS config parser, composer, and reconciliation helpers."""

import json
from unittest.mock import MagicMock

import pytest

from jidou.services.rss_config import (
    ReconcileDelta,
    compose_rss_config,
    compute_subscription_deltas,
    extract_max_subscription_key,
    parse_rss_config,
)

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

_HEADER = {"file": 1, "format": 1}
_BODY = {
    "cookies": {},
    "general": {"update_interval": 30},
    "rssfeeds": {"0": {"name": "ShowRSS", "url": "https://showrss.info/feed", "active": True}},
    "subscriptions": {
        "0": {
            "name": "The Last of Us",
            "regex_include": ".*1080p.*",
            "regex_exclude": None,
            "active": True,
            "last_match": "2026-06-01T12:00:00",
        },
        "1": {
            "name": "Severance",
            "regex_include": ".*1080p.*",
            "regex_exclude": None,
            "active": True,
            "last_match": None,
        },
    },
    "email_messages": {},
    "email_configurations": {},
}

_RAW = json.dumps(_HEADER, separators=(",", ":")) + json.dumps(_BODY, separators=(",", ":"))


# ---------------------------------------------------------------------------
# parse_rss_config
# ---------------------------------------------------------------------------


class TestParseRssConfig:
    def test_parses_two_objects(self) -> None:
        """parse_rss_config splits the concatenated objects correctly."""
        header, body = parse_rss_config(_RAW)
        assert header == _HEADER
        assert body["subscriptions"]["0"]["name"] == "The Last of Us"

    def test_whitespace_tolerant(self) -> None:
        """Leading/trailing whitespace does not break parsing."""
        raw_with_whitespace = f"\n  {_RAW}  \n"
        header, _body = parse_rss_config(raw_with_whitespace)
        assert header["format"] == 1

    def test_raises_on_single_object(self) -> None:
        """A single JSON object raises ValueError."""
        with pytest.raises(ValueError, match="parse"):
            parse_rss_config(json.dumps(_HEADER))

    def test_raises_on_invalid_json(self) -> None:
        """Completely invalid JSON raises ValueError."""
        with pytest.raises(ValueError, match="parse"):
            parse_rss_config("{not valid json}")

    def test_raises_on_non_dict_objects(self) -> None:
        """Two JSON arrays (not objects) raise ValueError."""
        with pytest.raises(ValueError, match="two JSON objects"):
            parse_rss_config("[1,2,3][4,5,6]")


# ---------------------------------------------------------------------------
# compose_rss_config
# ---------------------------------------------------------------------------


class TestComposeRssConfig:
    def test_round_trip(self) -> None:
        """parse → compose → parse produces identical dicts."""
        header, body = parse_rss_config(_RAW)
        recomposed = compose_rss_config(header, body)
        header2, body2 = parse_rss_config(recomposed)
        assert header2 == header
        assert body2 == body

    def test_output_is_compact_json(self) -> None:
        """compose_rss_config uses compact separators (no extra whitespace)."""
        result = compose_rss_config({"a": 1}, {"b": 2})
        assert result == '{"a":1}{"b":2}'

    def test_no_separator_between_objects(self) -> None:
        """The two JSON objects are directly concatenated with no separator."""
        result = compose_rss_config(_HEADER, _BODY)
        # Must be parseable as two concatenated objects
        header, body = parse_rss_config(result)
        assert header == _HEADER
        assert body == _BODY


# ---------------------------------------------------------------------------
# extract_max_subscription_key
# ---------------------------------------------------------------------------


class TestExtractMaxSubscriptionKey:
    def test_returns_max_key(self) -> None:
        """Returns the maximum integer key from the subscriptions dict."""
        assert extract_max_subscription_key(_BODY) == 1

    def test_empty_subscriptions_returns_zero(self) -> None:
        """Returns 0 when subscriptions is empty."""
        assert extract_max_subscription_key({"subscriptions": {}}) == 0

    def test_missing_subscriptions_returns_zero(self) -> None:
        """Returns 0 when the subscriptions key is absent."""
        assert extract_max_subscription_key({}) == 0

    def test_single_entry(self) -> None:
        """Single subscription with key '7' returns 7."""
        body = {"subscriptions": {"7": {"name": "test"}}}
        assert extract_max_subscription_key(body) == 7

    def test_non_contiguous_keys(self) -> None:
        """Non-contiguous keys: max of {0, 3, 10} is 10."""
        body = {"subscriptions": {"0": {}, "3": {}, "10": {}}}
        assert extract_max_subscription_key(body) == 10


# ---------------------------------------------------------------------------
# compute_subscription_deltas
# ---------------------------------------------------------------------------


def _make_sub(
    remote_key: str | None,
    name: str = "Test Show",
    regex_include: str | None = ".*1080p.*",
    regex_exclude: str | None = None,
    download_location: str | None = None,
    move_completed: str | None = None,
    enabled_in_config: bool = True,
    label: str | None = None,
) -> MagicMock:
    """Build a minimal RssSubscription mock."""
    sub = MagicMock()
    sub.remote_key = remote_key
    sub.name = name
    sub.regex_include = regex_include
    sub.regex_exclude = regex_exclude
    sub.regex_include_ignorecase = True
    sub.regex_exclude_ignorecase = True
    sub.download_location = download_location
    sub.move_completed = move_completed
    sub.active = True
    sub.enabled_in_config = enabled_in_config
    sub.label = label
    return sub


class TestComputeSubscriptionDeltas:
    def test_new_remote_subscription_goes_to_create(self) -> None:
        """A remote subscription not in DB is added to to_create."""
        remote = {"0": {"name": "New Show", "active": True}}
        delta = compute_subscription_deltas([], remote)
        assert len(delta.to_create) == 1
        assert delta.to_create[0]["name"] == "New Show"
        assert delta.to_create[0]["remote_key"] == "0"

    def test_unchanged_subscription_goes_to_update(self) -> None:
        """A subscription matching a DB row still appears in to_update (for merge)."""
        sub = _make_sub(remote_key="0", name="The Last of Us")
        remote = {"0": {"name": "The Last of Us", "active": True, "last_match": "2026-06-01"}}
        delta = compute_subscription_deltas([sub], remote)
        assert len(delta.to_update) == 1
        assert delta.to_update[0][0] is sub

    def test_remote_owns_last_match(self) -> None:
        """Remote value for last_match overwrites the DB value in the merged dict."""
        sub = _make_sub(remote_key="0")
        sub.last_match = "2026-01-01"
        remote = {"0": {"name": "Show", "active": True, "last_match": "2026-06-15"}}
        delta = compute_subscription_deltas([sub], remote)
        _, merged = delta.to_update[0]
        assert merged["last_match"] == "2026-06-15"

    def test_remote_owns_active(self) -> None:
        """Remote value for active field takes precedence over DB."""
        sub = _make_sub(remote_key="0")
        sub.active = True
        remote = {"0": {"name": "Show", "active": False, "last_match": None}}
        delta = compute_subscription_deltas([sub], remote)
        _, merged = delta.to_update[0]
        assert merged["active"] is False

    def test_jidou_owns_regex(self) -> None:
        """Jidou's regex_include survives the merge even when remote has a different value."""
        sub = _make_sub(remote_key="0", regex_include=".*2160p.*")
        remote = {"0": {"name": "Show", "regex_include": ".*1080p.*", "active": True}}
        delta = compute_subscription_deltas([sub], remote)
        _, merged = delta.to_update[0]
        assert merged["regex_include"] == ".*2160p.*"

    def test_jidou_owns_name(self) -> None:
        """Jidou's name survives the merge."""
        sub = _make_sub(remote_key="0", name="Jidou Name")
        remote = {"0": {"name": "Remote Name", "active": True}}
        delta = compute_subscription_deltas([sub], remote)
        _, merged = delta.to_update[0]
        assert merged["name"] == "Jidou Name"

    def test_deleted_remote_key_detected(self) -> None:
        """A DB row whose remote_key is absent from remote goes to remote_deleted_keys."""
        sub = _make_sub(remote_key="5")
        delta = compute_subscription_deltas([sub], {})
        assert "5" in delta.remote_deleted_keys

    def test_stub_rows_ignored(self) -> None:
        """Rows with remote_key=None (stubs) are skipped entirely."""
        stub = _make_sub(remote_key=None, name="Stub Show")
        remote: dict[str, dict[str, object]] = {}
        delta = compute_subscription_deltas([stub], remote)
        assert delta == ReconcileDelta()

    def test_empty_inputs(self) -> None:
        """No DB rows and no remote subscriptions produces an empty delta."""
        delta = compute_subscription_deltas([], {})
        assert delta == ReconcileDelta()

    def test_multiple_keys(self) -> None:
        """Mixed scenario: one new, one updated, one deleted."""
        sub_existing = _make_sub(remote_key="0")
        sub_deleted = _make_sub(remote_key="2")
        remote = {
            "0": {"name": "Existing", "active": True},
            "1": {"name": "Brand New", "active": True},
        }
        delta = compute_subscription_deltas([sub_existing, sub_deleted], remote)
        assert len(delta.to_create) == 1
        assert delta.to_create[0]["remote_key"] == "1"
        assert len(delta.to_update) == 1
        assert "2" in delta.remote_deleted_keys
