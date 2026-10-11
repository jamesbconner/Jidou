"""Tests for POST /api/rss/feeds/{id}/add-show."""

from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from jidou.api.dependencies import get_llm_service
from jidou.api.routes.shows import get_tmdb
from jidou.database import get_session
from jidou.main import app
from jidou.models.rss import RssFeed, RssSubscription
from jidou.models.show import Show
from jidou.orchestrators.feed_onboarding_orchestrator import (
    FeedOnboardingError,
    OnboardingOutcome,
)

ORCH = "jidou.api.routes.rss.FeedOnboardingOrchestrator"
URL = "/api/rss/feeds/7/add-show"


def _feed() -> MagicMock:
    f = MagicMock(spec=RssFeed)
    f.id = 7
    f.url = "https://tracker.example/rss?passkey=SUPERSECRET"
    return f


def _show(show_id: int = 42) -> MagicMock:
    s = MagicMock(spec=Show)
    s.id = show_id
    s.title = "Brand New Show"
    s.status = "Returning Series"
    s.poster_path = None
    return s


def _sub(sub_id: int = 5) -> MagicMock:
    now = datetime.now(UTC)
    s = MagicMock(spec=RssSubscription)
    s.id = sub_id
    s.remote_key = None
    s.name = "Brand New Show"
    s.feed_id = 7
    s.show_id = 42
    s.regex_include = "Brand.New.Show"
    s.regex_exclude = None
    s.regex_include_ignorecase = True
    s.regex_exclude_ignorecase = True
    s.download_location = None
    s.move_completed = None
    s.active = True
    s.enabled_in_config = True
    s.label = None
    s.last_match = None
    s.extra_config = None
    s.feed = None
    s.show = _show()
    s.created_at = now
    s.updated_at = now
    return s


def _session(feed: MagicMock | None, sub: MagicMock | None = None):
    async def _mock_session():
        session = AsyncMock()
        feed_result = MagicMock()
        feed_result.scalar_one_or_none.return_value = feed
        sub_result = MagicMock()
        sub_result.scalar_one.return_value = sub
        session.execute = AsyncMock(side_effect=[feed_result, sub_result])
        yield session

    return _mock_session


def _outcome(**kw) -> OnboardingOutcome:
    base = {
        "show": _show(),
        "show_created": False,
        "subscription_id": 5,
        "subscription_created": True,
        "adopted_stub": False,
        "alias_added": True,
        "dry_run": False,
    }
    base.update(kw)
    return OnboardingOutcome(**base)


@pytest.fixture
def wired() -> Iterator[None]:
    app.dependency_overrides[get_tmdb] = lambda: MagicMock()
    app.dependency_overrides[get_llm_service] = lambda: MagicMock()
    yield
    app.dependency_overrides.clear()


def test_add_show_existing_library_show_returns_show_and_subscription(wired) -> None:
    app.dependency_overrides[get_session] = _session(_feed(), _sub(5))

    with patch(ORCH) as orch_cls:
        orch_cls.return_value.add_show_from_feed = AsyncMock(return_value=_outcome())
        r = TestClient(app).post(
            URL,
            json={
                "parsed_name": "brand new show",
                "show_id": 42,
                "regex_include": "Brand.New.Show",
                "enabled": True,
            },
        )

    assert r.status_code == 200
    body = r.json()
    assert body["show"]["id"] == 42
    assert body["subscription"]["id"] == 5
    assert (body["show_created"], body["subscription_created"]) == (False, True)
    assert body["alias_added"] is True and body["dry_run"] is False
    request_arg = orch_cls.return_value.add_show_from_feed.await_args.args[1]
    assert request_arg.regex_include == "Brand.New.Show" and request_arg.enabled is True


def test_add_show_new_tmdb_show_payload_is_accepted(wired) -> None:
    app.dependency_overrides[get_session] = _session(_feed(), _sub(5))

    with patch(ORCH) as orch_cls:
        orch_cls.return_value.add_show_from_feed = AsyncMock(
            return_value=_outcome(show_created=True)
        )
        r = TestClient(app).post(
            URL,
            json={
                "parsed_name": "Fresh.Show",
                "show": {"tmdb_id": 555, "title": "Fresh Show", "media_type": "tv"},
            },
        )

    assert r.status_code == 200
    assert r.json()["show_created"] is True
    request_arg = orch_cls.return_value.add_show_from_feed.await_args.args[1]
    assert request_arg.show.tmdb_id == 555 and request_arg.show_id is None


def test_add_show_dry_run_has_no_subscription_to_serialise(wired) -> None:
    app.dependency_overrides[get_session] = _session(_feed(), None)

    with patch(ORCH) as orch_cls:
        orch_cls.return_value.add_show_from_feed = AsyncMock(
            return_value=_outcome(show=None, show_created=True, subscription_id=None, dry_run=True)
        )
        r = TestClient(app).post(
            URL,
            json={
                "parsed_name": "Fresh.Show",
                "show": {"tmdb_id": 555, "title": "Fresh Show"},
                "dry_run": True,
            },
        )

    body = r.json()
    assert r.status_code == 200
    assert (body["show"], body["subscription"], body["dry_run"]) == (None, None, True)
    assert body["show_created"] is True and body["subscription_created"] is True


def test_add_show_unknown_feed_is_404_and_does_nothing(wired) -> None:
    app.dependency_overrides[get_session] = _session(None)

    with patch(ORCH) as orch_cls:
        r = TestClient(app).post(URL, json={"parsed_name": "x", "show_id": 1})

    assert r.status_code == 404
    orch_cls.assert_not_called()


def test_add_show_unknown_library_show_maps_orchestrator_error(wired) -> None:
    app.dependency_overrides[get_session] = _session(_feed())

    with patch(ORCH) as orch_cls:
        orch_cls.return_value.add_show_from_feed = AsyncMock(
            side_effect=FeedOnboardingError(404, "Show not found")
        )
        r = TestClient(app).post(URL, json={"parsed_name": "x", "show_id": 999})

    assert r.status_code == 404
    assert r.json()["detail"] == "Show not found"


@pytest.mark.parametrize(
    "payload",
    [
        {"parsed_name": "x"},  # neither show_id nor show
        {"parsed_name": "x", "show_id": 1, "show": {"tmdb_id": 1, "title": "X"}},  # both
        {"show_id": 1},  # no parsed_name
        {"parsed_name": "", "show_id": 1},
        {"parsed_name": "x", "show_id": 1, "regex_include": "(unclosed"},
        {"parsed_name": "x", "show_id": 1, "regex_exclude": "a" * 513},
        {"parsed_name": "x", "show": {"tmdb_id": 1, "title": "X", "media_type": "bogus"}},
    ],
)
def test_add_show_validates_the_request(wired, payload: dict) -> None:
    app.dependency_overrides[get_session] = _session(_feed())

    with patch(ORCH) as orch_cls:
        r = TestClient(app).post(URL, json=payload)

    assert r.status_code == 422
    orch_cls.assert_not_called()
