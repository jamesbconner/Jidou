"""Tests for the RSS import orchestrator and POST /api/rss/import endpoint."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jidou.orchestrators.rss_import_orchestrator import RssImportOrchestrator
from jidou.services.sftp_service import SFTPService
from jidou.services.task_dispatch import TaskDispatchError

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_HEADER = {"file": 1, "format": 1}
_BODY = {
    "rssfeeds": {
        "0": {"name": "ShowRSS", "url": "https://showrss.info/user/123.rss", "active": True}
    },
    "subscriptions": {
        "0": {
            "name": "The Last of Us",
            "active": True,
            "last_match": "2026-06-01",
            "regex_include": ".*1080p.*",
        },
        "1": {"name": "Severance", "active": True, "last_match": None},
    },
    "cookies": {},
    "email_messages": {},
}

_RAW = json.dumps(_HEADER, separators=(",", ":")) + json.dumps(_BODY, separators=(",", ":"))


def _make_sftp(raw_bytes: bytes = _RAW.encode()) -> MagicMock:
    sftp = MagicMock(spec=SFTPService)
    sftp.download_bytes = AsyncMock(return_value=raw_bytes)
    return sftp


def _make_session() -> MagicMock:
    """Build a session mock with sync `add` and async `execute`/`flush`."""
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock()
    return session


async def _noop_event(level: str, msg: str, ctx: object = None) -> None:
    pass


def _exec_result(scalar: object = None, scalars_all: list | None = None) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = scalar
    r.scalars.return_value.all.return_value = scalars_all if scalars_all is not None else []
    r.all.return_value = scalars_all if scalars_all is not None else []
    return r


def _fake_enqueue(task: MagicMock) -> AsyncMock:
    """Return a fake enqueue_task: calls dispatch(), commits+re-raises on failure.

    Mirrors enqueue_task's real "create row, dispatch, mark FAILED + commit on
    broker failure" shape closely enough for both call_args and
    session.commit() assertions to hold without exercising the real DB calls.
    """

    async def _run(session, task_id, task_type, dispatch, *, dry_run=False):  # type: ignore[no-untyped-def]
        try:
            dispatch()
        except Exception as exc:
            await session.commit()
            raise TaskDispatchError(str(exc)) from exc
        return task

    return AsyncMock(side_effect=_run)


# ---------------------------------------------------------------------------
# dry_run behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_parses_and_counts_but_skips_db_writes() -> None:
    """dry_run=True downloads and computes deltas but performs no DB writes."""
    session = _make_session()
    # Reads still happen: feed lookup, db_subs, shows
    session.execute = AsyncMock(
        side_effect=[
            _exec_result(scalar=None),  # feed "0" select
            _exec_result(scalars_all=[]),  # RssSubscription select
            _exec_result(scalars_all=[]),  # Show select
        ]
    )
    sftp = _make_sftp()

    orc = RssImportOrchestrator(
        session=session,
        sftp=sftp,
        remote_path="/remote/yarss2.conf",
        dry_run=True,
        on_event=_noop_event,
    )
    result = await orc.run()

    assert result.dry_run is True
    assert result.feeds_created == 1
    assert result.subscriptions_created == 2
    # Downloads without dry_run flag (always fetches the real config)
    sftp.download_bytes.assert_awaited_once_with("/remote/yarss2.conf")
    # No snapshot stored, no subscription rows written
    session.add.assert_not_called()
    session.flush.assert_not_called()


# ---------------------------------------------------------------------------
# Happy-path: feeds upsert (tested via _upsert_feeds directly)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_feeds_creates_new_feed() -> None:
    """A feed not in the DB is created."""
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    session = _make_session()
    session.execute = AsyncMock(return_value=_exec_result(scalar=None))

    sftp = _make_sftp()
    orc = RssImportOrchestrator(
        session=session,
        sftp=sftp,
        remote_path="/remote/yarss2.conf",
        dry_run=False,
        on_event=_noop_event,
    )

    rssfeeds = {"0": {"name": "ShowRSS", "url": "https://showrss.info/feed"}}
    result = RssImportResult()
    await orc._upsert_feeds(rssfeeds, result)

    assert result.feeds_created == 1
    assert result.feeds_updated == 0
    session.add.assert_called_once()


@pytest.mark.asyncio
async def test_upsert_feeds_updates_existing_feed() -> None:
    """A feed already in the DB is updated, not duplicated."""
    from jidou.models.rss import RssFeed
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    session = _make_session()
    existing_feed = MagicMock(spec=RssFeed)
    existing_feed.id = 1
    session.execute = AsyncMock(return_value=_exec_result(scalar=existing_feed))

    sftp = _make_sftp()
    orc = RssImportOrchestrator(
        session=session,
        sftp=sftp,
        remote_path="/remote/yarss2.conf",
        dry_run=False,
        on_event=_noop_event,
    )

    rssfeeds = {"0": {"name": "ShowRSS", "url": "https://showrss.info/feed"}}
    result = RssImportResult()
    key_to_id = await orc._upsert_feeds(rssfeeds, result)

    assert result.feeds_updated == 1
    assert result.feeds_created == 0
    assert key_to_id["0"] == 1
    assert existing_feed.name == "ShowRSS"
    assert existing_feed.url == "https://showrss.info/feed"


# ---------------------------------------------------------------------------
# Happy-path: subscriptions upsert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscriptions_created_for_new_keys() -> None:
    """Remote subscriptions not in DB are added as new rows."""
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    session = _make_session()
    # First execute: db_subs (empty), second: shows (empty)
    session.execute = AsyncMock(
        side_effect=[_exec_result(scalars_all=[]), _exec_result(scalars_all=[])]
    )

    sftp = _make_sftp()
    orc = RssImportOrchestrator(
        session=session,
        sftp=sftp,
        remote_path="/remote/yarss2.conf",
        dry_run=False,
        on_event=_noop_event,
    )

    remote_subs = {
        "0": {"name": "The Last of Us", "active": True},
        "1": {"name": "Severance", "active": True},
    }
    result = RssImportResult()
    await orc._upsert_subscriptions(remote_subs, {}, result)

    assert result.subscriptions_created == 2
    assert result.subscriptions_updated == 0
    assert session.add.call_count == 2
    # All imported subscriptions must be marked as enabled in the remote config
    for call in session.add.call_args_list:
        added = call.args[0]
        assert added.enabled_in_config is True


@pytest.mark.asyncio
async def test_rssfeed_key_resolves_feed_id() -> None:
    """The native YaRSS2 field rssfeed_key is used to link subscriptions to feeds."""
    from jidou.models.rss import RssSubscription
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    session = _make_session()
    session.execute = AsyncMock(
        side_effect=[_exec_result(scalars_all=[]), _exec_result(scalars_all=[])]
    )

    sftp = _make_sftp()
    orc = RssImportOrchestrator(
        session=session,
        sftp=sftp,
        remote_path="/remote/yarss2.conf",
        dry_run=False,
        on_event=_noop_event,
    )

    remote_subs = {"216": {"name": "Scum of the Brave", "active": True, "rssfeed_key": "1"}}
    feed_key_to_id = {"0": 10, "1": 11, "2": 12}
    result = RssImportResult()
    await orc._upsert_subscriptions(remote_subs, feed_key_to_id, result)

    assert result.subscriptions_created == 1
    added_sub = session.add.call_args_list[0].args[0]
    assert isinstance(added_sub, RssSubscription)
    assert added_sub.feed_id == 11  # rssfeed_key "1" → DB id 11


@pytest.mark.asyncio
async def test_upsert_feeds_dry_run_maps_new_feed_to_placeholder_id() -> None:
    """_upsert_feeds in dry-run maps a brand-new feed's key to the placeholder id.

    Regression test for #425: previously a new feed's key was simply omitted
    from the returned mapping in dry-run mode (no real id exists yet), making
    it indistinguishable from a genuinely unresolvable key.
    """
    from jidou.orchestrators.rss_import_orchestrator import (
        _DRY_RUN_PENDING_FEED_ID,
        RssImportResult,
    )

    session = _make_session()
    session.execute = AsyncMock(return_value=_exec_result(scalar=None))  # no existing row

    sftp = _make_sftp()
    orc = RssImportOrchestrator(
        session=session,
        sftp=sftp,
        remote_path="/remote/yarss2.conf",
        dry_run=True,
        on_event=_noop_event,
    )

    rssfeeds = {"1": {"name": "New Feed", "url": "https://example.com/new.rss"}}
    result = RssImportResult()
    key_to_id = await orc._upsert_feeds(rssfeeds, result)

    assert key_to_id == {"1": _DRY_RUN_PENDING_FEED_ID}
    assert result.feeds_created == 1
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_dry_run_subscription_for_new_feed_does_not_warn() -> None:
    """A subscription pointing at a brand-new feed must not spuriously warn in dry-run.

    Regression test for #425: a dry-run preview where most feeds already
    exist but one subscription points at a brand-new feed previously warned
    "could not resolve feed" for that subscription, even though the real
    (non-dry-run) import would resolve it correctly once the feed is
    actually created. A genuinely unresolvable rssfeed_key must still warn.
    """
    from jidou.orchestrators.rss_import_orchestrator import (
        _DRY_RUN_PENDING_FEED_ID,
        RssImportResult,
    )

    session = _make_session()
    session.execute = AsyncMock(
        side_effect=[_exec_result(scalars_all=[]), _exec_result(scalars_all=[])]
    )

    events: list[tuple[str, str, object]] = []

    async def _capture_event(level: str, msg: str, ctx: object = None) -> None:
        events.append((level, msg, ctx))

    sftp = _make_sftp()
    orc = RssImportOrchestrator(
        session=session,
        sftp=sftp,
        remote_path="/remote/yarss2.conf",
        dry_run=True,
        on_event=_capture_event,
    )

    # feed_key_to_id as _upsert_feeds produces it in dry-run: "0" already
    # exists (real id), "1" is brand-new (placeholder).
    feed_key_to_id = {"0": 10, "1": _DRY_RUN_PENDING_FEED_ID}
    remote_subs = {
        "216": {"name": "Existing-Feed Sub", "active": True, "rssfeed_key": "0"},
        "217": {"name": "New-Feed Sub", "active": True, "rssfeed_key": "1"},
        "218": {"name": "Truly Unresolvable", "active": True, "rssfeed_key": "999"},
    }
    result = RssImportResult()
    await orc._upsert_subscriptions(remote_subs, feed_key_to_id, result)

    warn_msgs = [msg for level, msg, _ in events if level == "warn"]
    assert not any("New-Feed Sub" in m for m in warn_msgs)
    assert any("Truly Unresolvable" in m for m in warn_msgs)


@pytest.mark.asyncio
async def test_show_auto_linked_by_name() -> None:
    """A subscription whose name matches a show title gets show_id set."""
    from jidou.models.rss import RssSubscription
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    session = _make_session()

    show_row = MagicMock()
    show_row.id = 42
    show_row.title = "The Last of Us"
    shows_result = MagicMock()
    shows_result.all.return_value = [show_row]

    session.execute = AsyncMock(side_effect=[_exec_result(scalars_all=[]), shows_result])

    sftp = _make_sftp()
    orc = RssImportOrchestrator(
        session=session,
        sftp=sftp,
        remote_path="/remote/yarss2.conf",
        dry_run=False,
        on_event=_noop_event,
    )

    remote_subs = {"0": {"name": "The Last of Us", "active": True}}
    result = RssImportResult()
    await orc._upsert_subscriptions(remote_subs, {}, result)

    assert result.shows_linked == 1
    added_sub = session.add.call_args_list[0].args[0]
    assert isinstance(added_sub, RssSubscription)
    assert added_sub.show_id == 42


@pytest.mark.asyncio
async def test_show_fuzzy_linked_by_name() -> None:
    """A subscription whose name fuzzy-matches a show title (token-set ratio) gets show_id set."""
    from jidou.models.rss import RssSubscription
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    session = _make_session()

    show_row = MagicMock()
    show_row.id = 7
    show_row.title = "Marvel's Daredevil"
    shows_result = MagicMock()
    shows_result.all.return_value = [show_row]

    session.execute = AsyncMock(side_effect=[_exec_result(scalars_all=[]), shows_result])

    sftp = _make_sftp()
    orc = RssImportOrchestrator(
        session=session,
        sftp=sftp,
        remote_path="/remote/yarss2.conf",
        dry_run=False,
        on_event=_noop_event,
    )

    # YaRSS2 uses "Daredevil" — token_set_ratio vs "Marvel's Daredevil" is 100
    remote_subs = {"9": {"name": "Daredevil", "active": True}}
    result = RssImportResult()
    await orc._upsert_subscriptions(remote_subs, {}, result)

    assert result.shows_linked == 1
    added_sub = session.add.call_args_list[0].args[0]
    assert isinstance(added_sub, RssSubscription)
    assert added_sub.show_id == 7


@pytest.mark.asyncio
async def test_show_fuzzy_link_ambiguous_not_matched() -> None:
    """Ambiguous fuzzy match (two shows at same score) leaves show_id unset."""
    from jidou.models.rss import RssSubscription
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    session = _make_session()

    # Both titles score 100 on token_set_ratio against "Daredevil"
    show_row_1 = MagicMock()
    show_row_1.id = 7
    show_row_1.title = "Marvel's Daredevil"
    show_row_2 = MagicMock()
    show_row_2.id = 8
    show_row_2.title = "Daredevil Born Again"  # no colon — scores 100, not 60
    shows_result = MagicMock()
    shows_result.all.return_value = [show_row_1, show_row_2]

    session.execute = AsyncMock(side_effect=[_exec_result(scalars_all=[]), shows_result])

    sftp = _make_sftp()
    orc = RssImportOrchestrator(
        session=session,
        sftp=sftp,
        remote_path="/remote/yarss2.conf",
        dry_run=False,
        on_event=_noop_event,
    )

    remote_subs = {"9": {"name": "Daredevil", "active": True}}
    result = RssImportResult()
    await orc._upsert_subscriptions(remote_subs, {}, result)

    assert result.shows_linked == 0
    added_sub = session.add.call_args_list[0].args[0]
    assert isinstance(added_sub, RssSubscription)
    assert added_sub.show_id is None


@pytest.mark.asyncio
async def test_show_fuzzy_link_below_threshold_not_matched() -> None:
    """A subscription name that scores below the fuzzy threshold does not get show_id set."""
    from jidou.models.rss import RssSubscription
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    session = _make_session()

    show_row = MagicMock()
    show_row.id = 3
    show_row.title = "The Boys"
    shows_result = MagicMock()
    shows_result.all.return_value = [show_row]

    session.execute = AsyncMock(side_effect=[_exec_result(scalars_all=[]), shows_result])

    sftp = _make_sftp()
    orc = RssImportOrchestrator(
        session=session,
        sftp=sftp,
        remote_path="/remote/yarss2.conf",
        dry_run=False,
        on_event=_noop_event,
    )

    remote_subs = {"11": {"name": "Attack on Titan", "active": True}}
    result = RssImportResult()
    await orc._upsert_subscriptions(remote_subs, {}, result)

    assert result.shows_linked == 0
    added_sub = session.add.call_args_list[0].args[0]
    assert isinstance(added_sub, RssSubscription)
    assert added_sub.show_id is None


@pytest.mark.asyncio
async def test_stub_promoted_when_remote_matches_by_show_id() -> None:
    """A watchlist stub (remote_key=None) is promoted in-place when import finds a match."""
    from jidou.models.rss import RssSubscription
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    stub = MagicMock(spec=RssSubscription)
    stub.remote_key = None
    stub.show_id = 42
    stub.name = "Daredevil Born Again"
    stub.feed_id = None
    stub.id = 7

    session = _make_session()

    show_row = MagicMock()
    show_row.id = 42
    show_row.title = "Daredevil Born Again"
    shows_result = MagicMock()
    shows_result.all.return_value = [show_row]

    session.execute = AsyncMock(side_effect=[_exec_result(scalars_all=[stub]), shows_result])

    sftp = _make_sftp()
    orc = RssImportOrchestrator(
        session=session,
        sftp=sftp,
        remote_path="/remote/yarss2.conf",
        dry_run=False,
        on_event=_noop_event,
    )

    remote_subs = {
        "5": {"name": "Daredevil Born Again", "active": True, "regex_include": ".*1080p.*"}
    }
    result = RssImportResult()
    await orc._upsert_subscriptions(remote_subs, {}, result)

    # No new row created; stub promoted in-place
    assert result.stubs_promoted == 1
    assert result.subscriptions_created == 0
    session.add.assert_not_called()
    assert stub.remote_key == "5"
    assert stub.enabled_in_config is True
    assert stub.name == "Daredevil Born Again"


@pytest.mark.asyncio
async def test_stub_promoted_when_remote_matches_by_name_only() -> None:
    """A stub with show_id=None is promoted when the remote sub name matches case-insensitively."""
    from jidou.models.rss import RssSubscription
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    stub = MagicMock(spec=RssSubscription)
    stub.remote_key = None
    stub.show_id = None
    stub.name = "Daredevil Born Again"
    stub.feed_id = None
    stub.id = 8

    session = _make_session()
    session.execute = AsyncMock(
        side_effect=[_exec_result(scalars_all=[stub]), _exec_result(scalars_all=[])]
    )

    sftp = _make_sftp()
    orc = RssImportOrchestrator(
        session=session,
        sftp=sftp,
        remote_path="/remote/yarss2.conf",
        dry_run=False,
        on_event=_noop_event,
    )

    remote_subs = {"3": {"name": "daredevil born again", "active": True}}
    result = RssImportResult()
    await orc._upsert_subscriptions(remote_subs, {}, result)

    assert result.stubs_promoted == 1
    assert result.subscriptions_created == 0
    session.add.assert_not_called()
    assert stub.remote_key == "3"
    assert stub.enabled_in_config is True


@pytest.mark.asyncio
async def test_stub_not_mutated_in_dry_run() -> None:
    """In dry_run mode, a matching stub is counted as promoted but not mutated."""
    from jidou.models.rss import RssSubscription
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    stub = MagicMock(spec=RssSubscription)
    stub.remote_key = None
    stub.show_id = None
    stub.name = "Daredevil Born Again"
    stub.feed_id = None
    stub.id = 9

    session = _make_session()
    session.execute = AsyncMock(
        side_effect=[_exec_result(scalars_all=[stub]), _exec_result(scalars_all=[])]
    )

    sftp = _make_sftp()
    orc = RssImportOrchestrator(
        session=session,
        sftp=sftp,
        remote_path="/remote/yarss2.conf",
        dry_run=True,
        on_event=_noop_event,
    )

    remote_subs = {"3": {"name": "Daredevil Born Again", "active": True}}
    result = RssImportResult()
    await orc._upsert_subscriptions(remote_subs, {}, result)

    assert result.stubs_promoted == 1
    # dry_run: stub fields must NOT be mutated
    assert stub.remote_key is None
    assert not hasattr(stub, "enabled_in_config") or stub.enabled_in_config != True  # noqa: E712


@pytest.mark.asyncio
async def test_stub_only_promoted_once_second_remote_match_creates_new_row() -> None:
    """A stub evicted after first promotion; a second remote sub with same name gets a new row."""
    from jidou.models.rss import RssSubscription
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    stub = MagicMock(spec=RssSubscription)
    stub.remote_key = None
    stub.show_id = None
    stub.name = "Daredevil Born Again"
    stub.feed_id = None
    stub.id = 10

    session = _make_session()
    session.execute = AsyncMock(
        side_effect=[_exec_result(scalars_all=[stub]), _exec_result(scalars_all=[])]
    )

    sftp = _make_sftp()
    orc = RssImportOrchestrator(
        session=session,
        sftp=sftp,
        remote_path="/remote/yarss2.conf",
        dry_run=False,
        on_event=_noop_event,
    )

    # Two remote subs with the same name matching the same stub
    remote_subs = {
        "3": {"name": "Daredevil Born Again", "active": True},
        "7": {"name": "Daredevil Born Again", "active": True},
    }
    result = RssImportResult()
    await orc._upsert_subscriptions(remote_subs, {}, result)

    # First match promotes the stub; second match creates a new row
    assert result.stubs_promoted == 1
    assert result.subscriptions_created == 1
    session.add.assert_called_once()


@pytest.mark.asyncio
async def test_remote_deleted_keys_logged() -> None:
    """Keys in DB but absent from remote are reported as remote-deleted."""
    from jidou.models.rss import RssSubscription
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    db_sub = MagicMock(spec=RssSubscription)
    db_sub.remote_key = "99"

    session = _make_session()
    session.execute = AsyncMock(
        side_effect=[_exec_result(scalars_all=[db_sub]), _exec_result(scalars_all=[])]
    )

    events: list[str] = []

    async def capture_event(level: str, msg: str, ctx: object = None) -> None:
        events.append(f"{level}:{msg}")

    sftp = _make_sftp()
    orc = RssImportOrchestrator(
        session=session,
        sftp=sftp,
        remote_path="/remote/yarss2.conf",
        dry_run=False,
        on_event=capture_event,
    )

    result = RssImportResult()
    await orc._upsert_subscriptions({}, {}, result)

    assert result.subscriptions_remote_deleted == 1
    assert any("99" in e for e in events)


@pytest.mark.asyncio
async def test_last_update_preserved_in_extra_config_on_update() -> None:
    """On subscription update, remote non-column fields like last_update go into extra_config."""
    from jidou.models.rss import RssSubscription
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    db_sub = MagicMock(spec=RssSubscription)
    db_sub.remote_key = "0"
    db_sub.name = "Severance"
    db_sub.regex_include = None
    db_sub.regex_exclude = None
    db_sub.regex_include_ignorecase = True
    db_sub.regex_exclude_ignorecase = True
    db_sub.download_location = None
    db_sub.move_completed = None
    db_sub.label = None
    db_sub.extra_config = {"last_update": "2026-01-01"}
    db_sub.show_id = None

    session = _make_session()
    session.execute = AsyncMock(
        side_effect=[
            _exec_result(scalars_all=[db_sub]),  # db_subs
            _exec_result(scalars_all=[]),  # shows
        ]
    )

    sftp = _make_sftp()
    orc = RssImportOrchestrator(
        session=session,
        sftp=sftp,
        remote_path="/remote/yarss2.conf",
        dry_run=False,
        on_event=_noop_event,
    )

    # Remote has a newer last_update
    remote_subs = {"0": {"name": "Severance", "active": True, "last_update": "2026-06-01"}}
    result = RssImportResult()
    await orc._upsert_subscriptions(remote_subs, {}, result)

    # extra_config should contain the NEW remote last_update, not the old one
    assert db_sub.extra_config is not None
    assert db_sub.extra_config["last_update"] == "2026-06-01"


@pytest.mark.asyncio
async def test_dry_run_does_not_mutate_existing_feed() -> None:
    """In dry_run mode, existing RssFeed ORM objects are not mutated."""
    from jidou.models.rss import RssFeed
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    session = _make_session()
    existing_feed = MagicMock(spec=RssFeed)
    existing_feed.id = 7
    existing_feed.name = "OldName"
    session.execute = AsyncMock(return_value=_exec_result(scalar=existing_feed))

    sftp = _make_sftp()
    orc = RssImportOrchestrator(
        session=session,
        sftp=sftp,
        remote_path="/remote/yarss2.conf",
        dry_run=True,
        on_event=_noop_event,
    )

    rssfeeds = {"0": {"name": "NewName", "url": "https://showrss.info/feed"}}
    result = RssImportResult()
    await orc._upsert_feeds(rssfeeds, result)

    assert result.feeds_updated == 1
    # Name must NOT be changed in dry_run
    assert existing_feed.name == "OldName"
    session.flush.assert_not_called()


@pytest.mark.asyncio
async def test_null_rssfeeds_section_treated_as_empty() -> None:
    """A JSON null value for rssfeeds/subscriptions is treated as empty, not crashed."""
    import json as _json

    body_with_nulls = {
        "rssfeeds": None,
        "subscriptions": None,
        "cookies": {},
        "email_messages": {},
    }
    raw = _json.dumps({"file": 1}, separators=(",", ":")) + _json.dumps(
        body_with_nulls, separators=(",", ":")
    )

    session = _make_session()
    session.execute = AsyncMock(
        side_effect=[
            _exec_result(scalars_all=[]),  # db_subs select (subscriptions empty)
            _exec_result(scalars_all=[]),  # shows select
        ]
    )
    sftp = _make_sftp(raw.encode())
    orc = RssImportOrchestrator(
        session=session,
        sftp=sftp,
        remote_path="/remote/yarss2.conf",
        dry_run=False,
        on_event=_noop_event,
    )
    result = await orc.run()

    assert result.feeds_created == 0
    assert result.subscriptions_created == 0
    assert result.errors == []


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parse_error_returns_result_with_error_message() -> None:
    """If the raw content is not parseable, returns result with errors list."""
    session = _make_session()
    sftp = _make_sftp(b"this is not valid json at all")
    orc = RssImportOrchestrator(
        session=session,
        sftp=sftp,
        remote_path="/remote/yarss2.conf",
        dry_run=False,
        on_event=_noop_event,
    )
    result = await orc.run()

    assert len(result.errors) == 1
    assert "parse" in result.errors[0].lower()
    assert result.snapshot_id is None
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_celery_task_marks_failed_when_orchestrator_returns_errors() -> None:
    """_rss_import's `work` closure surfaces RssImportOrchestrator errors as a soft failure.

    The actual FAILED-status transition and RuntimeError-after-session-closes
    behavior now live in run_task_workflow and are covered generically in
    tests/test_worker_harness.py (test_soft_failure_marks_failed_...); this
    only needs to prove _rss_import's `work` closure produces the right
    WorkflowResult(errors=...) when the orchestrator reports errors.
    """
    from unittest.mock import AsyncMock, MagicMock, patch

    from jidou.orchestrators.rss_import_orchestrator import RssImportResult
    from jidou.workers.rss_tasks import _rss_import

    error_result = RssImportResult(errors=["Failed to parse RSS config: malformed JSON"])

    captured: dict[str, object] = {}

    async def fake_run_task_workflow(
        celery_task_id: str,
        task_type: str,
        work: object,
        *,
        progress_total: int = 0,
        dry_run: bool = False,
        running_message: str = "",
    ) -> str:
        captured["work"] = work
        return celery_task_id

    with patch("jidou.workers.rss_tasks.run_task_workflow", side_effect=fake_run_task_workflow):
        await _rss_import("test-task-id", dry_run=False)

    with (
        patch("jidou.workers.rss_tasks.create_sftp_service", return_value=MagicMock()),
        patch(
            "jidou.workers.rss_tasks.RssImportOrchestrator.run",
            new_callable=AsyncMock,
            return_value=error_result,
        ),
    ):
        wf_result = await captured["work"](AsyncMock(), AsyncMock(), AsyncMock())  # type: ignore[operator]

    assert wf_result.errors == ["Failed to parse RSS config: malformed JSON"]  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# POST /api/rss/import endpoint
# ---------------------------------------------------------------------------


def test_import_endpoint_422_when_path_not_configured() -> None:
    """POST /api/rss/import returns 422 when RSS_CONFIG_REMOTE_PATH is not set."""
    from fastapi.testclient import TestClient

    from jidou.database import get_session
    from jidou.main import app

    async def _mock_session() -> MagicMock:
        session = _make_session()
        yield session

    app.dependency_overrides[get_session] = _mock_session
    try:
        with patch("jidou.api.routes.rss.settings") as mock_settings:
            mock_settings.rss_config_remote_path = None
            r = TestClient(app).post("/api/rss/import")
        assert r.status_code == 422
        assert "RSS_CONFIG_REMOTE_PATH" in r.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_import_endpoint_202_when_path_configured() -> None:
    """POST /api/rss/import returns 202 and a task record when configured."""
    from datetime import UTC, datetime

    from fastapi.testclient import TestClient

    from jidou.database import get_session
    from jidou.main import app
    from jidou.models.task import BackgroundTask

    task = MagicMock(spec=BackgroundTask)
    task.id = 1
    task.celery_task_id = "abc-123"
    task.task_type = "rss_import"
    task.status = "pending"
    task.progress_current = 0
    task.progress_total = 0
    task.progress_message = None
    task.result_summary = None
    task.dry_run = False
    now = datetime.now(UTC)
    task.created_at = now
    task.updated_at = now
    task.completed_at = None
    task.event_log = []

    async def _mock_session() -> MagicMock:
        session = _make_session()
        yield session

    app.dependency_overrides[get_session] = _mock_session
    try:
        with (
            patch("jidou.api.routes.rss.settings") as mock_settings,
            patch("jidou.services.task_dispatch.enqueue_task", _fake_enqueue(task)),
            patch("jidou.workers.rss_tasks.rss_import_task") as mock_task,
        ):
            mock_settings.rss_config_remote_path = "/remote/yarss2.conf"
            mock_task.apply_async = MagicMock()
            r = TestClient(app).post("/api/rss/import")
        assert r.status_code == 202
        mock_task.apply_async.assert_called_once()
    finally:
        app.dependency_overrides.clear()


def test_import_endpoint_503_when_broker_unavailable() -> None:
    """POST /api/rss/import returns 503 when the Celery broker is unreachable."""
    from fastapi.testclient import TestClient

    from jidou.database import get_session
    from jidou.main import app
    from jidou.models.task import BackgroundTask

    task = MagicMock(spec=BackgroundTask)
    task.id = 1
    task.status = "pending"
    task.completed_at = None

    session = _make_session()
    session.commit = AsyncMock()

    async def _mock_session() -> MagicMock:
        yield session

    app.dependency_overrides[get_session] = _mock_session
    try:
        with (
            patch("jidou.api.routes.rss.settings") as mock_settings,
            patch("jidou.services.task_dispatch.enqueue_task", _fake_enqueue(task)),
            patch("jidou.workers.rss_tasks.rss_import_task") as mock_task,
        ):
            mock_settings.rss_config_remote_path = "/remote/yarss2.conf"
            mock_task.apply_async = MagicMock(side_effect=RuntimeError("Celery broker down"))
            r = TestClient(app).post("/api/rss/import")

        assert r.status_code == 503
        assert "broker" in r.json()["detail"].lower()
        session.commit.assert_called_once()
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Characterization: subscription upsert paths (pins behaviour before the
# _upsert_subscriptions split -- every path, count, event and DB-call order)
# ---------------------------------------------------------------------------

EventLog = list[tuple[str, str, object]]


def _recorder(events: EventLog):  # type: ignore[no-untyped-def]
    """Return an on_event callback appending (level, msg, ctx) to *events*."""

    async def _record(level: str, msg: str, ctx: object = None) -> None:
        events.append((level, msg, ctx))

    return _record


def _recording_orc(
    session: MagicMock, events: EventLog, *, dry_run: bool = False
) -> RssImportOrchestrator:
    """Build an orchestrator whose on_event appends (level, msg, ctx) to *events*."""
    return RssImportOrchestrator(
        session=session,
        sftp=_make_sftp(),
        remote_path="/remote/yarss2.conf",
        dry_run=dry_run,
        on_event=_recorder(events),
    )


async def _boom(level: str, msg: str, ctx: object = None) -> None:
    raise RuntimeError("sink down")


def _stub_row(*, id: int = 7, name: str = "Daredevil", show_id=None, feed_id=None):  # type: ignore[no-untyped-def]
    from jidou.models.rss import RssSubscription

    return RssSubscription(
        id=id,
        remote_key=None,
        name=name,
        show_id=show_id,
        feed_id=feed_id,
        enabled_in_config=False,
        regex_include_ignorecase=True,
        regex_exclude_ignorecase=True,
    )


def _keyed_row(*, remote_key="0", name="Severance", feed_id=None, show_id=None, extra=None):  # type: ignore[no-untyped-def]
    from jidou.models.rss import RssSubscription

    return RssSubscription(
        id=int(remote_key) + 100,
        remote_key=remote_key,
        name=name,
        show_id=show_id,
        feed_id=feed_id,
        enabled_in_config=True,
        regex_include=None,
        regex_exclude=None,
        regex_include_ignorecase=True,
        regex_exclude_ignorecase=True,
        extra_config=extra,
    )


def _shows_result(*rows: tuple[int, str]) -> MagicMock:
    r = MagicMock()
    shows = []
    for sid, title in rows:
        row = MagicMock()
        row.id = sid
        row.title = title
        shows.append(row)
    r.all.return_value = shows
    return r


def _upsert_session(db_subs: list, shows: MagicMock | None = None) -> MagicMock:
    session = _make_session()
    session.execute = AsyncMock(
        side_effect=[_exec_result(scalars_all=db_subs), shows or _shows_result()]
    )
    return session


@pytest.mark.asyncio
async def test_upsert_stub_promotion_links_show_and_copies_remote_columns() -> None:
    """Promoting a stub with no show_id links the fuzzy-matched show and applies remote data."""
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    stub = _stub_row(name="Daredevil", show_id=None, feed_id=None)
    session = _upsert_session([stub], _shows_result((42, "Daredevil")))
    events: EventLog = []
    orc = _recording_orc(session, events)
    result = RssImportResult()

    await orc._upsert_subscriptions(
        {
            "5": {
                "name": "Daredevil",
                "active": False,
                "regex_include": ".*720p.*",
                "rssfeed_key": "f1",
                "custom_flag": 3,
            }
        },
        {"f1": 11},
        result,
    )

    assert (result.stubs_promoted, result.shows_linked, result.subscriptions_created) == (1, 1, 0)
    assert stub.remote_key == "5"
    assert stub.feed_id == 11
    assert stub.show_id == 42
    assert stub.enabled_in_config is True
    assert stub.regex_include == ".*720p.*"
    assert stub.active is False
    assert stub.extra_config == {"rssfeed_key": "f1", "custom_flag": 3}
    assert events == []
    session.add.assert_not_called()
    assert session.flush.await_count == 2


@pytest.mark.asyncio
async def test_upsert_stub_promotion_keeps_existing_show_and_feed() -> None:
    """A stub already linked to a show/feed keeps them; shows_linked is not bumped."""
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    stub = _stub_row(name="Daredevil", show_id=42, feed_id=9)
    session = _upsert_session([stub], _shows_result((42, "Daredevil")))
    events: EventLog = []
    orc = _recording_orc(session, events)
    result = RssImportResult()

    await orc._upsert_subscriptions({"5": {"name": "Daredevil"}}, {"f1": 11}, result)

    assert result.stubs_promoted == 1
    assert result.shows_linked == 0
    assert stub.feed_id == 9  # remote had no rssfeed_key -> stub's feed kept
    assert stub.show_id == 42
    assert events == []  # effective feed id present -> no warning


@pytest.mark.asyncio
async def test_upsert_stub_promotion_warns_when_feed_still_unresolved() -> None:
    """A promoted stub that ends up with no feed warns with the exact create wording."""
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    stub = _stub_row(name="Daredevil")
    session = _upsert_session([stub])
    events: EventLog = []
    orc = _recording_orc(session, events)
    result = RssImportResult()

    await orc._upsert_subscriptions(
        {"5": {"name": "Daredevil", "rssfeed_key": "zz"}}, {"f1": 11}, result
    )

    assert events == [
        (
            "warn",
            "Subscription '5' ('Daredevil'): could not resolve feed — "
            "rssfeed_key='zz', available feed keys=['f1']",
            {"remote_key": "5", "rssfeed_key": "zz"},
        )
    ]
    assert result.stubs_promoted == 1


@pytest.mark.asyncio
async def test_upsert_no_feed_warning_when_no_feeds_known() -> None:
    """With an empty feed map the unresolved-feed warning is suppressed (stub and new row)."""
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    stub = _stub_row(name="Daredevil")
    session = _upsert_session([stub])
    events: EventLog = []
    orc = _recording_orc(session, events)
    result = RssImportResult()

    await orc._upsert_subscriptions(
        {"5": {"name": "Daredevil", "rssfeed_key": "zz"}, "6": {"name": "Other"}}, {}, result
    )

    assert events == []
    assert (result.stubs_promoted, result.subscriptions_created) == (1, 1)


@pytest.mark.asyncio
async def test_upsert_new_row_warns_unresolved_feed_and_sets_columns() -> None:
    """A brand-new row with an unknown feed key warns, is added, and carries extras."""
    from jidou.models.rss import RssSubscription
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    session = _upsert_session([], _shows_result((3, "Severance")))
    events: EventLog = []
    orc = _recording_orc(session, events)
    result = RssImportResult()

    await orc._upsert_subscriptions(
        {"8": {"name": "Severance", "rssfeed_key": "nope", "regex_include": "x", "extra": 1}},
        {"f1": 11},
        result,
    )

    assert events == [
        (
            "warn",
            "Subscription '8' ('Severance'): could not resolve feed — "
            "rssfeed_key='nope', available feed keys=['f1']",
            {"remote_key": "8", "rssfeed_key": "nope"},
        )
    ]
    session.add.assert_called_once()
    new_sub = session.add.call_args.args[0]
    assert isinstance(new_sub, RssSubscription)
    assert new_sub.remote_key == "8"
    assert new_sub.feed_id is None
    assert new_sub.show_id == 3
    assert new_sub.enabled_in_config is True
    assert new_sub.regex_include == "x"
    assert new_sub.extra_config == {"rssfeed_key": "nope", "extra": 1}
    assert (result.subscriptions_created, result.shows_linked) == (1, 1)
    assert session.flush.await_count == 2


@pytest.mark.asyncio
async def test_upsert_new_row_resolved_feed_does_not_warn() -> None:
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    session = _upsert_session([])
    events: EventLog = []
    orc = _recording_orc(session, events)
    result = RssImportResult()

    await orc._upsert_subscriptions({"8": {"name": "X", "rssfeed_key": "f1"}}, {"f1": 11}, result)

    assert events == []
    assert session.add.call_args.args[0].feed_id == 11
    assert result.shows_linked == 0


@pytest.mark.asyncio
async def test_upsert_dry_run_create_and_stub_warn_but_do_not_write() -> None:
    """Dry run still warns and counts, but adds/mutates/flushes nothing."""
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    stub = _stub_row(name="Daredevil")
    session = _upsert_session([stub], _shows_result((3, "Severance")))
    events: EventLog = []
    orc = _recording_orc(session, events, dry_run=True)
    result = RssImportResult()

    await orc._upsert_subscriptions(
        {
            "5": {"name": "Daredevil", "rssfeed_key": "zz"},
            "6": {"name": "Severance", "rssfeed_key": "zz"},
        },
        {"f1": 11},
        result,
    )

    assert [e[1].split(":")[0] for e in events] == [
        "Subscription '5' ('Daredevil')",
        "Subscription '6' ('Severance')",
    ]
    assert (result.stubs_promoted, result.subscriptions_created, result.shows_linked) == (1, 1, 1)
    assert stub.remote_key is None
    assert stub.enabled_in_config is False
    session.add.assert_not_called()
    session.flush.assert_not_called()


@pytest.mark.asyncio
async def test_upsert_update_resolves_feed_and_rebuilds_extra_config() -> None:
    """Live update: feed id from rssfeed_key, extras merged over old extra_config."""
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    row = _keyed_row(extra={"old": 1, "last_update": "a"})
    session = _upsert_session([row])
    events: EventLog = []
    orc = _recording_orc(session, events)
    result = RssImportResult()

    await orc._upsert_subscriptions(
        {"0": {"name": "Severance", "active": False, "rssfeed_key": "f1", "last_update": "b"}},
        {"f1": 11},
        result,
    )

    assert row.feed_id == 11
    assert row.active is False
    assert row.extra_config == {"old": 1, "last_update": "b", "rssfeed_key": "f1"}
    assert result.subscriptions_updated == 1
    assert events == []
    assert session.flush.await_count == 2


@pytest.mark.asyncio
async def test_upsert_update_warns_with_on_update_wording_when_row_has_no_feed() -> None:
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    row = _keyed_row(feed_id=None)
    session = _upsert_session([row])
    events: EventLog = []
    orc = _recording_orc(session, events)
    result = RssImportResult()

    await orc._upsert_subscriptions(
        {"0": {"name": "Severance", "rssfeed_key": "zz"}}, {"f1": 1}, result
    )

    assert events == [
        (
            "warn",
            "Subscription '0' ('Severance'): could not resolve feed on update — "
            "rssfeed_key='zz', available feed keys=['f1']",
            {"remote_key": "0", "rssfeed_key": "zz"},
        )
    ]
    assert row.feed_id is None
    assert result.subscriptions_updated == 1


@pytest.mark.parametrize(
    ("feed_id", "feed_map"),
    [(5, {"f1": 1}), (None, {})],
    ids=["row-keeps-existing-feed", "no-feeds-known"],
)
@pytest.mark.asyncio
async def test_upsert_update_unresolved_feed_is_silent(
    feed_id: int | None, feed_map: dict[str, int]
) -> None:
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    row = _keyed_row(feed_id=feed_id)
    session = _upsert_session([row])
    events: EventLog = []
    orc = _recording_orc(session, events)
    result = RssImportResult()

    await orc._upsert_subscriptions(
        {"0": {"name": "Severance", "rssfeed_key": "zz"}}, feed_map, result
    )

    assert events == []
    assert row.feed_id == feed_id


@pytest.mark.asyncio
async def test_upsert_update_non_dict_old_extra_config_is_replaced() -> None:
    """A non-dict extra_config on the merged row is treated as empty, not merged."""
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    row = _keyed_row(extra=["junk"])
    session = _upsert_session([row])
    orc = _recording_orc(session, [])
    result = RssImportResult()

    await orc._upsert_subscriptions({"0": {"name": "Severance", "last_update": "b"}}, {}, result)

    assert row.extra_config == {"last_update": "b"}


@pytest.mark.asyncio
async def test_upsert_update_empty_extras_becomes_none() -> None:
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    row = _keyed_row(extra={})
    session = _upsert_session([row])
    orc = _recording_orc(session, [])
    result = RssImportResult()

    await orc._upsert_subscriptions({"0": {"name": "Severance"}}, {}, result)

    assert row.extra_config is None


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.asyncio
async def test_upsert_update_auto_links_show_live_but_only_counts_in_dry_run(
    dry_run: bool,
) -> None:
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    row = _keyed_row(show_id=None)
    session = _upsert_session([row], _shows_result((3, "Severance")))
    orc = _recording_orc(session, [], dry_run=dry_run)
    result = RssImportResult()

    await orc._upsert_subscriptions({"0": {"name": "Severance"}}, {}, result)

    assert result.shows_linked == 1
    assert result.subscriptions_updated == 1
    assert row.show_id == (None if dry_run else 3)


@pytest.mark.asyncio
async def test_upsert_update_dry_run_writes_nothing_and_does_not_warn() -> None:
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    row = _keyed_row(feed_id=None, extra={"k": 1})
    session = _upsert_session([row])
    events: EventLog = []
    orc = _recording_orc(session, events, dry_run=True)
    result = RssImportResult()

    await orc._upsert_subscriptions(
        {"0": {"name": "Severance", "active": False, "rssfeed_key": "zz"}}, {"f1": 1}, result
    )

    assert events == []
    assert row.feed_id is None
    assert row.extra_config == {"k": 1}
    assert result.subscriptions_updated == 1
    session.flush.assert_not_called()


@pytest.mark.asyncio
async def test_upsert_update_no_show_match_leaves_unlinked() -> None:
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    row = _keyed_row(show_id=None)
    session = _upsert_session([row], _shows_result((3, "Zzzzzz Unrelated")))
    orc = _recording_orc(session, [])
    result = RssImportResult()

    await orc._upsert_subscriptions({"0": {"name": "Severance"}}, {}, result)

    assert row.show_id is None
    assert result.shows_linked == 0


@pytest.mark.asyncio
async def test_upsert_mixed_pass_pins_event_order_flushes_and_counts() -> None:
    """create + stub + update + remote-delete in one pass: exact events, counts, flush count."""
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    stub = _stub_row(name="Daredevil")
    upd = _keyed_row(remote_key="0", name="Severance", feed_id=None)
    gone = _keyed_row(remote_key="99", name="Gone")
    session = _upsert_session([stub, upd, gone])
    events: EventLog = []
    orc = _recording_orc(session, events)
    result = RssImportResult()

    await orc._upsert_subscriptions(
        {
            "0": {"name": "Severance", "rssfeed_key": "zz"},
            "1": {"name": "Daredevil", "rssfeed_key": "zz"},
            "2": {"name": "Brand New", "rssfeed_key": "zz"},
        },
        {"f1": 1},
        result,
    )

    assert [(e[0], e[1].split(":")[0]) for e in events] == [
        ("warn", "Subscription '1' ('Daredevil')"),
        ("warn", "Subscription '2' ('Brand New')"),
        ("warn", "Subscription '0' ('Severance')"),
        ("warn", "Subscription remote_key='99' no longer in remote config (not deleted from DB)"),
    ]
    assert events[-1][2] == {"remote_key": "99"}
    assert (
        result.stubs_promoted,
        result.subscriptions_created,
        result.subscriptions_updated,
        result.subscriptions_remote_deleted,
    ) == (1, 1, 1, 1)
    assert session.flush.await_count == 2
    session.add.assert_called_once()


@pytest.mark.asyncio
async def test_upsert_empty_everything_flushes_twice_and_emits_nothing() -> None:
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    session = _upsert_session([])
    events: EventLog = []
    orc = _recording_orc(session, events)
    result = RssImportResult()

    await orc._upsert_subscriptions({}, {}, result)

    assert events == []
    assert session.flush.await_count == 2
    session.add.assert_not_called()
    assert result == RssImportResult()


@pytest.mark.asyncio
async def test_upsert_event_failure_on_new_row_warning_propagates_before_count() -> None:
    """on_event errors propagate; a new row's warning fires before add/count."""
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    session = _upsert_session([])
    orc = RssImportOrchestrator(session, _make_sftp(), "/r", on_event=_boom)
    result = RssImportResult()

    with pytest.raises(RuntimeError, match="sink down"):
        await orc._upsert_subscriptions(
            {"1": {"name": "X", "rssfeed_key": "zz"}}, {"f1": 1}, result
        )

    assert result.subscriptions_created == 0
    session.add.assert_not_called()
    session.flush.assert_not_called()


@pytest.mark.asyncio
async def test_upsert_event_failure_on_stub_warning_propagates_after_count() -> None:
    """A stub's warning fires AFTER it was mutated and counted (count stays 1)."""
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    stub = _stub_row(name="Daredevil")
    session = _upsert_session([stub])
    orc = RssImportOrchestrator(session, _make_sftp(), "/r", on_event=_boom)
    result = RssImportResult()

    with pytest.raises(RuntimeError, match="sink down"):
        await orc._upsert_subscriptions(
            {"5": {"name": "Daredevil", "rssfeed_key": "zz"}}, {"f1": 1}, result
        )

    assert result.stubs_promoted == 1
    assert stub.remote_key == "5"
    session.flush.assert_not_called()


@pytest.mark.asyncio
async def test_upsert_event_failure_on_update_warning_leaves_row_partially_updated() -> None:
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    row = _keyed_row(feed_id=None, extra={"old": 1})
    session = _upsert_session([row])
    orc = RssImportOrchestrator(session, _make_sftp(), "/r", on_event=_boom)
    result = RssImportResult()

    with pytest.raises(RuntimeError, match="sink down"):
        await orc._upsert_subscriptions(
            {"0": {"name": "Severance", "active": False, "rssfeed_key": "zz"}}, {"f1": 1}, result
        )

    assert result.subscriptions_updated == 0
    assert row.active is False  # columns were applied before the warning
    assert row.extra_config == {"old": 1}  # extra_config rebuild comes after the warning
    assert session.flush.await_count == 1  # only the post-create flush ran


@pytest.mark.asyncio
async def test_upsert_event_failure_on_remote_deleted_counts_first() -> None:
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    session = _upsert_session([_keyed_row(remote_key="99")])
    orc = RssImportOrchestrator(session, _make_sftp(), "/r", on_event=_boom)
    result = RssImportResult()

    with pytest.raises(RuntimeError, match="sink down"):
        await orc._upsert_subscriptions({}, {}, result)

    assert result.subscriptions_remote_deleted == 1


@pytest.mark.asyncio
async def test_run_with_empty_body_sections_completes_with_zero_counts() -> None:
    """A parseable config with no feeds/subscriptions imports cleanly (live: snapshot only)."""
    raw = json.dumps(_HEADER, separators=(",", ":")) + json.dumps({}, separators=(",", ":"))
    session = _make_session()
    session.execute = AsyncMock(side_effect=[_exec_result(scalars_all=[]), _shows_result()])
    events: EventLog = []
    added: list[object] = []

    def _add(obj: object) -> None:
        obj.id = 5  # type: ignore[attr-defined]
        added.append(obj)

    session.add.side_effect = _add
    orc = RssImportOrchestrator(
        session, _make_sftp(raw.encode()), "/remote/yarss2.conf", on_event=_recorder(events)
    )

    result = await orc.run()

    assert result.errors == []
    assert result.snapshot_id == 5
    assert (result.feeds_created, result.subscriptions_created) == (0, 0)
    assert added[0].snapshot_type == "import"  # type: ignore[attr-defined]
    assert [e[1] for e in events] == [
        "Downloading RSS config from /remote/yarss2.conf",
        f"Stored config snapshot id=5 ({len(raw)} bytes)",
        "Import complete — feeds: +0/~0, subscriptions: +0/~0, stubs promoted: 0, "
        "remote-deleted: 0, shows linked: 0",
    ]


@pytest.mark.asyncio
async def test_run_malformed_config_reports_error_and_writes_nothing() -> None:
    session = _make_session()
    events: EventLog = []
    orc = RssImportOrchestrator(
        session, _make_sftp(b"not json at all"), "/remote/yarss2.conf", on_event=_recorder(events)
    )

    result = await orc.run()

    assert len(result.errors) == 1
    assert result.errors[0].startswith("Failed to parse RSS config: ")
    assert result.raw_content == "not json at all"
    assert events[-1] == ("error", result.errors[0], None)
    session.add.assert_not_called()
    session.execute.assert_not_called()
