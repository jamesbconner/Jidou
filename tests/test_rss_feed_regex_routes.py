"""Tests for POST /api/rss/feeds/{id}/suggest-regex and /test-regex."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from jidou.api.dependencies import get_feed_fetch_service, get_llm_service
from jidou.database import get_session
from jidou.main import app
from jidou.models.rss import RssFeed
from jidou.services.feed_fetch import FeedEntry, FeedFetchError, FeedFetchResult
from jidou.services.llm_service import LLMProvider, LLMResponse

FEED_URL = "https://tracker.example/rss?passkey=SUPERSECRET"

ENTRIES = [
    "[Grp] Brand New Show - 05 (1080p).mkv",
    "[Grp] Brand New Show - 06 (1080p).mkv",
    "[Grp] Brand New Show - 06 (720p).mkv",
    "[Grp] Other Thing - 01 (1080p).mkv",
]


def _feed() -> MagicMock:
    f = MagicMock(spec=RssFeed)
    f.id = 7
    f.url = FEED_URL
    f.regex_include_samples = None
    f.regex_exclude_hint = None
    return f


def _session(feed: MagicMock | None):
    async def _mock_session():
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = feed
        session.execute = AsyncMock(return_value=result)
        yield session

    return _mock_session


def _llm(content: str | None = None, *, available: bool = True) -> MagicMock:
    llm = MagicMock()
    llm.is_available.return_value = available
    response = (
        LLMResponse(content=content, model="test-model", provider=LLMProvider.OPENAI, cached=False)
        if content is not None
        else None
    )
    llm.complete = AsyncMock(return_value=response)
    return llm


@pytest.fixture
def fetcher() -> Iterator[MagicMock]:
    svc = MagicMock()
    svc.fetch_entries = AsyncMock(
        return_value=FeedFetchResult(
            entries=[FeedEntry(title=t, guid=None, published=None) for t in ENTRIES],
            malformed=False,
            cached=True,
        )
    )
    app.dependency_overrides[get_feed_fetch_service] = lambda: svc
    app.dependency_overrides[get_session] = _session(_feed())
    yield svc
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# suggest-regex
# ---------------------------------------------------------------------------


def test_suggest_shows_the_model_real_titles_and_reports_matches(fetcher: MagicMock) -> None:
    llm = _llm('{"regex_include": "Brand.New.Show.*1080p", "regex_exclude": ""}')
    app.dependency_overrides[get_llm_service] = lambda: llm

    r = TestClient(app).post(
        "/api/rss/feeds/7/suggest-regex",
        json={"parsed_name": "brand new show", "show_title": "Brand New Show (2024)"},
    )

    assert r.status_code == 200
    body = r.json()
    assert body["regex_include"] == "Brand.New.Show.*1080p"
    assert body["model"] == "test-model"
    assert body["match"]["total"] == 3  # only the group's titles, not "Other Thing"
    assert body["match"]["matched_titles"] == [ENTRIES[0], ENTRIES[1]]
    assert body["match"]["unmatched_titles"] == [ENTRIES[2]]

    prompt = llm.complete.await_args.kwargs["prompt"]
    assert '"Brand New Show (2024)"' in prompt
    assert ENTRIES[0] in prompt and ENTRIES[2] in prompt
    assert ENTRIES[3] not in prompt  # a different show's release never leaks in
    fetcher.fetch_entries.assert_awaited_once_with(FEED_URL)


def test_suggest_falls_back_to_parsed_name_as_label(fetcher: MagicMock) -> None:
    llm = _llm('{"regex_include": "Brand.New.Show", "regex_exclude": ""}')
    app.dependency_overrides[get_llm_service] = lambda: llm

    r = TestClient(app).post(
        "/api/rss/feeds/7/suggest-regex", json={"parsed_name": "Brand New Show"}
    )

    assert r.status_code == 200
    assert '"Brand New Show"' in llm.complete.await_args.kwargs["prompt"]


def test_suggest_passes_previous_and_bypasses_llm_cache(fetcher: MagicMock) -> None:
    llm = _llm('{"regex_include": "Different", "regex_exclude": ""}')
    app.dependency_overrides[get_llm_service] = lambda: llm

    r = TestClient(app).post(
        "/api/rss/feeds/7/suggest-regex",
        json={"parsed_name": "Brand New Show", "previous": ["Old.Pattern"]},
    )

    assert r.status_code == 200
    kwargs = llm.complete.await_args.kwargs
    assert kwargs["bypass_cache"] is True
    assert '"Old.Pattern"' in kwargs["prompt"]


def test_suggest_unknown_feed_404(fetcher: MagicMock) -> None:
    app.dependency_overrides[get_session] = _session(None)
    app.dependency_overrides[get_llm_service] = lambda: _llm("{}")

    r = TestClient(app).post("/api/rss/feeds/7/suggest-regex", json={"parsed_name": "X"})

    assert r.status_code == 404
    fetcher.fetch_entries.assert_not_called()


def test_suggest_llm_not_configured_is_422_before_any_feed_fetch(fetcher: MagicMock) -> None:
    app.dependency_overrides[get_llm_service] = lambda: _llm(available=False)

    r = TestClient(app).post(
        "/api/rss/feeds/7/suggest-regex", json={"parsed_name": "Brand New Show"}
    )

    assert r.status_code == 422
    fetcher.fetch_entries.assert_not_called()


def test_suggest_group_gone_from_feed_is_404(fetcher: MagicMock) -> None:
    app.dependency_overrides[get_llm_service] = lambda: _llm("{}")

    r = TestClient(app).post("/api/rss/feeds/7/suggest-regex", json={"parsed_name": "Vanished"})

    assert r.status_code == 404
    assert "no longer in the feed" in r.json()["detail"]


@pytest.mark.parametrize(("timed_out", "status"), [(False, 502), (True, 504)])
def test_suggest_feed_fetch_failure_maps_status_without_secret(
    fetcher: MagicMock, timed_out: bool, status: int
) -> None:
    fetcher.fetch_entries.side_effect = FeedFetchError("Could not fetch feed", timed_out=timed_out)
    app.dependency_overrides[get_llm_service] = lambda: _llm("{}")

    r = TestClient(app).post("/api/rss/feeds/7/suggest-regex", json={"parsed_name": "X"})

    assert r.status_code == status
    assert "SUPERSECRET" not in r.text


def test_suggest_llm_failure_is_503(fetcher: MagicMock) -> None:
    app.dependency_overrides[get_llm_service] = lambda: _llm(None)

    r = TestClient(app).post(
        "/api/rss/feeds/7/suggest-regex", json={"parsed_name": "Brand New Show"}
    )

    assert r.status_code == 503


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"parsed_name": ""},
        {"parsed_name": "x" * 301},
        {"parsed_name": "X", "previous": ["a"] * 6},
    ],
)
def test_suggest_validates_request_body(fetcher: MagicMock, payload: dict) -> None:
    app.dependency_overrides[get_llm_service] = lambda: _llm("{}")

    r = TestClient(app).post("/api/rss/feeds/7/suggest-regex", json=payload)

    assert r.status_code == 422


# ---------------------------------------------------------------------------
# test-regex
# ---------------------------------------------------------------------------


def test_test_regex_reports_matches_for_a_hand_edited_filter(fetcher: MagicMock) -> None:
    r = TestClient(app).post(
        "/api/rss/feeds/7/test-regex",
        json={
            "parsed_name": "Brand New Show",
            "regex_include": "Brand.New.*1080p",
            "regex_exclude": "- 06",
        },
    )

    assert r.status_code == 200
    assert r.json() == {
        "matched_titles": [ENTRIES[0]],
        "unmatched_titles": [ENTRIES[1], ENTRIES[2]],
        "total": 3,
    }


def test_test_regex_honours_case_flags(fetcher: MagicMock) -> None:
    r = TestClient(app).post(
        "/api/rss/feeds/7/test-regex",
        json={
            "parsed_name": "Brand New Show",
            "regex_include": "BRAND NEW SHOW",
            "regex_include_ignorecase": False,
        },
    )

    assert r.json()["matched_titles"] == []


def test_test_regex_empty_filters_match_everything(fetcher: MagicMock) -> None:
    r = TestClient(app).post("/api/rss/feeds/7/test-regex", json={"parsed_name": "Brand New Show"})

    assert r.json()["total"] == 3
    assert len(r.json()["matched_titles"]) == 3


@pytest.mark.parametrize("field", ["regex_include", "regex_exclude"])
def test_test_regex_rejects_uncompilable_pattern(fetcher: MagicMock, field: str) -> None:
    r = TestClient(app).post(
        "/api/rss/feeds/7/test-regex", json={"parsed_name": "Brand New Show", field: "(unclosed"}
    )

    assert r.status_code == 422
    fetcher.fetch_entries.assert_not_called()


def test_test_regex_rejects_oversize_pattern(fetcher: MagicMock) -> None:
    r = TestClient(app).post(
        "/api/rss/feeds/7/test-regex",
        json={"parsed_name": "Brand New Show", "regex_include": "a" * 513},
    )

    assert r.status_code == 422


def test_test_regex_unknown_feed_404(fetcher: MagicMock) -> None:
    app.dependency_overrides[get_session] = _session(None)

    r = TestClient(app).post("/api/rss/feeds/7/test-regex", json={"parsed_name": "X"})

    assert r.status_code == 404


def test_test_regex_group_gone_from_feed_is_404(fetcher: MagicMock) -> None:
    r = TestClient(app).post("/api/rss/feeds/7/test-regex", json={"parsed_name": "Vanished"})

    assert r.status_code == 404


def test_test_regex_feed_fetch_timeout_is_504(fetcher: MagicMock) -> None:
    fetcher.fetch_entries.side_effect = FeedFetchError("Timed out fetching feed", timed_out=True)

    r = TestClient(app).post("/api/rss/feeds/7/test-regex", json={"parsed_name": "X"})

    assert r.status_code == 504
