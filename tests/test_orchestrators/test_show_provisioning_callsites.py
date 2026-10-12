"""Characterization tests for the three show-provisioning call sites.

These pin the failure-path behaviour of ``get_or_create_show_from_tmdb``,
``ManualMatchOrchestrator._resolve_show_by_tmdb_id`` and
``PathImportOrchestrator._tmdb_create_show`` (what is raised, swallowed, rolled back, committed
and emitted) so the shared primitives in ``_show_provisioning`` can replace their inline copies
without changing observable behaviour. They patch ``TMDBOrchestrator`` methods on the class so
they hold wherever the call is made from.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from jidou.models.show import Show
from jidou.orchestrators.manual_match_orchestrator import ManualMatchOrchestrator
from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
from jidou.orchestrators.show_creation_orchestrator import get_or_create_show_from_tmdb
from jidou.orchestrators.tmdb_orchestrator import TMDBOrchestrator
from jidou.schemas.file_schema import FileMatchRequest
from jidou.schemas.show_schema import ShowCreate

# Where each call site resolves ``generate_aliases`` from.
_SHOW_CREATION_ALIASES = "jidou.orchestrators._show_provisioning.generate_aliases"
_LAZY_ALIASES = "jidou.orchestrators._show_provisioning.generate_aliases"


def _db_error() -> OperationalError:
    return OperationalError("stmt", {}, Exception("conn lost"))


# ---------------------------------------------------------------------------
# get_or_create_show_from_tmdb
# ---------------------------------------------------------------------------


def _creation_session(*lookups: Show | None) -> AsyncMock:
    session = AsyncMock()
    results = []
    for existing in lookups:
        r = MagicMock()
        r.scalar_one_or_none.return_value = existing
        results.append(r)
    session.execute = AsyncMock(side_effect=results)
    session.add = MagicMock(side_effect=lambda obj: setattr(obj, "id", 5))
    return session


@pytest.fixture
def creation_patches():
    """Patch the creation flow's collaborators; TMDBOrchestrator at class level."""
    fields = {"tmdb_id": 1396, "title": "Brand New Show", "media_type": "tv"}
    with (
        patch(
            "jidou.orchestrators.show_creation_orchestrator.fetch_show_metadata",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "jidou.orchestrators.show_creation_orchestrator.build_show_fields",
            return_value=dict(fields),
        ),
        patch(_SHOW_CREATION_ALIASES, new=AsyncMock()) as aliases,
        patch.object(TMDBOrchestrator, "sync_show_episodes", new=AsyncMock()) as sync,
        patch.object(TMDBOrchestrator, "ensure_episode_group_map", new=AsyncMock()) as ensure,
    ):
        yield {"aliases": aliases, "sync": sync, "ensure": ensure}


async def _create(session: AsyncMock):
    return await get_or_create_show_from_tmdb(
        session, MagicMock(), ShowCreate(tmdb_id=1396, title="X"), llm=MagicMock()
    )


async def test_creation_success_call_sequence(creation_patches) -> None:
    session = _creation_session(None)
    order: list[str] = []
    session.add.side_effect = lambda obj: (setattr(obj, "id", 5), order.append("add"))
    session.flush.side_effect = lambda: order.append("flush")
    session.commit.side_effect = lambda: order.append("commit")
    session.refresh.side_effect = lambda _s: order.append("refresh")
    session.rollback.side_effect = lambda: order.append("rollback")
    creation_patches["sync"].side_effect = lambda _s: order.append("sync")
    creation_patches["aliases"].side_effect = lambda *a, **k: order.append("aliases")

    result = await _create(session)

    assert result.created is True
    assert order == ["add", "flush", "sync", "commit", "aliases", "flush", "refresh"]


async def test_creation_sync_db_error_propagates_without_commit_or_rollback(
    creation_patches,
) -> None:
    session = _creation_session(None)
    creation_patches["sync"].side_effect = _db_error()

    with pytest.raises(OperationalError):
        await _create(session)

    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()
    creation_patches["aliases"].assert_not_awaited()


async def test_creation_sync_generic_failure_is_swallowed_without_rollback(
    creation_patches,
) -> None:
    session = _creation_session(None)
    creation_patches["sync"].side_effect = RuntimeError("tmdb down")

    result = await _create(session)

    assert result.created is True
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()
    creation_patches["aliases"].assert_awaited_once()


async def test_creation_alias_db_error_is_swallowed_without_rollback(creation_patches) -> None:
    session = _creation_session(None)
    creation_patches["aliases"].side_effect = _db_error()

    result = await _create(session)

    assert result.created is True
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()
    session.refresh.assert_awaited_once()


async def test_creation_alias_flush_failure_is_swallowed(creation_patches) -> None:
    session = _creation_session(None)
    session.flush.side_effect = [None, RuntimeError("flush failed")]

    result = await _create(session)

    assert result.created is True
    assert session.flush.await_count == 2
    session.rollback.assert_not_awaited()


async def test_creation_race_without_winner_reraises_after_rollback(creation_patches) -> None:
    session = _creation_session(None, None)
    session.flush.side_effect = IntegrityError("stmt", {}, Exception("dup"))

    with pytest.raises(IntegrityError):
        await _create(session)

    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()
    creation_patches["sync"].assert_not_awaited()


async def test_creation_race_winner_gets_episode_group_map(creation_patches) -> None:
    winner = MagicMock(spec=Show)
    winner.id = 7
    winner.tmdb_id = 1396
    session = _creation_session(None, winner)
    session.flush.side_effect = IntegrityError("stmt", {}, Exception("dup"))

    result = await _create(session)

    assert result.show is winner and result.created is False
    creation_patches["ensure"].assert_awaited_once_with(winner)
    session.commit.assert_not_awaited()


# ---------------------------------------------------------------------------
# ManualMatchOrchestrator._resolve_show_by_tmdb_id
# ---------------------------------------------------------------------------


def _mm_session(*lookups: object) -> MagicMock:
    session = MagicMock()
    results = []
    for existing in lookups:
        r = MagicMock()
        r.scalar_one_or_none.return_value = existing
        results.append(r)
    session.execute = AsyncMock(side_effect=results)
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.add = MagicMock(side_effect=lambda obj: setattr(obj, "id", 42))
    return session


def _mm_payload(**kwargs: object) -> FileMatchRequest:
    base: dict[str, object] = {
        "tmdb_id": 1396,
        "local_path": "/media/tv/Show",
        "content_type": "tv",
    }
    base.update(kwargs)
    return FileMatchRequest(**base)  # type: ignore[arg-type]


@pytest.fixture
def mm_patches():
    """Patch TMDB access for the manual-match create path."""
    data = {"id": 1396, "name": "Breaking Bad", "first_air_date": "2008-01-20"}
    with (
        patch(
            "jidou.orchestrators.manual_match_orchestrator.fetch_show_metadata",
            new=AsyncMock(return_value=data),
        ),
        patch("jidou.orchestrators.manual_match_orchestrator.TMDBService"),
        patch(_LAZY_ALIASES, new=AsyncMock()) as aliases,
        patch.object(TMDBOrchestrator, "sync_show_episodes", new=AsyncMock()) as sync,
        patch.object(TMDBOrchestrator, "ensure_episode_group_map", new=AsyncMock()) as ensure,
    ):
        yield {"aliases": aliases, "sync": sync, "ensure": ensure}


async def test_manual_match_success_call_sequence(mm_patches) -> None:
    session = _mm_session(None)
    order: list[str] = []
    session.add.side_effect = lambda obj: (setattr(obj, "id", 42), order.append("add"))
    session.flush.side_effect = lambda: order.append("flush")
    session.commit.side_effect = lambda: order.append("commit")
    session.rollback.side_effect = lambda: order.append("rollback")
    mm_patches["sync"].side_effect = lambda _s: order.append("sync")
    mm_patches["aliases"].side_effect = lambda *a, **k: order.append("aliases")

    show = await ManualMatchOrchestrator(session)._resolve_show_by_tmdb_id(_mm_payload())

    assert show.id == 42
    assert order == ["add", "flush", "sync", "commit", "aliases", "flush"]


async def test_manual_match_alias_db_error_propagates_after_commit(mm_patches) -> None:
    session = _mm_session(None)
    mm_patches["aliases"].side_effect = _db_error()

    with pytest.raises(OperationalError):
        await ManualMatchOrchestrator(session)._resolve_show_by_tmdb_id(_mm_payload())

    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


async def test_manual_match_alias_generic_failure_is_swallowed_without_rollback(
    mm_patches,
) -> None:
    session = _mm_session(None)
    mm_patches["aliases"].side_effect = RuntimeError("llm down")

    show = await ManualMatchOrchestrator(session)._resolve_show_by_tmdb_id(_mm_payload())

    assert show.id == 42
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


async def test_manual_match_sync_db_error_propagates_without_rollback(mm_patches) -> None:
    session = _mm_session(None)
    mm_patches["sync"].side_effect = _db_error()

    with pytest.raises(OperationalError):
        await ManualMatchOrchestrator(session)._resolve_show_by_tmdb_id(_mm_payload())

    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()
    mm_patches["aliases"].assert_not_awaited()


async def test_manual_match_movie_skips_sync(mm_patches) -> None:
    session = _mm_session(None)

    await ManualMatchOrchestrator(session)._resolve_show_by_tmdb_id(
        _mm_payload(tmdb_media_type="movie", content_type="movie")
    )

    mm_patches["sync"].assert_not_awaited()
    session.commit.assert_awaited_once()
    mm_patches["aliases"].assert_awaited_once()


async def test_manual_match_race_winner_gets_fields_filled_then_syncs(mm_patches) -> None:
    winner = MagicMock(spec=Show)
    winner.id = 7
    winner.tmdb_id = 1396
    winner.media_type = "tv"
    winner.local_path = None
    winner.content_type = None
    session = _mm_session(None, winner)
    session.flush.side_effect = [IntegrityError("stmt", {}, Exception("dup")), None, None]

    show = await ManualMatchOrchestrator(session)._resolve_show_by_tmdb_id(_mm_payload())

    assert show is winner
    assert winner.local_path == "/media/tv/Show"
    assert str(winner.content_type) == "tv"
    session.rollback.assert_awaited_once()
    # Not a fresh insert, but the sync/commit/alias tail still runs for the winner.
    mm_patches["sync"].assert_awaited_once_with(winner)
    session.commit.assert_awaited_once()
    mm_patches["aliases"].assert_awaited_once()
    # The winner's episode-group map is NOT ensured on this path.
    mm_patches["ensure"].assert_not_awaited()


async def test_manual_match_race_winner_keeps_existing_fields(mm_patches) -> None:
    winner = MagicMock(spec=Show)
    winner.id = 7
    winner.tmdb_id = 1396
    winner.media_type = "tv"
    winner.local_path = "/already/set"
    winner.content_type = "anime"
    session = _mm_session(None, winner)
    session.flush.side_effect = [IntegrityError("stmt", {}, Exception("dup")), None, None]

    await ManualMatchOrchestrator(session)._resolve_show_by_tmdb_id(_mm_payload())

    assert winner.local_path == "/already/set"
    assert winner.content_type == "anime"


async def test_manual_match_race_without_winner_reraises(mm_patches) -> None:
    session = _mm_session(None, None)
    session.flush.side_effect = IntegrityError("stmt", {}, Exception("dup"))

    with pytest.raises(IntegrityError):
        await ManualMatchOrchestrator(session)._resolve_show_by_tmdb_id(_mm_payload())

    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()
    mm_patches["sync"].assert_not_awaited()


async def test_manual_match_existing_show_is_filled_flushed_then_group_mapped(mm_patches) -> None:
    existing = MagicMock(spec=Show)
    existing.local_path = None
    existing.content_type = None
    session = _mm_session(existing)
    order: list[str] = []
    session.flush.side_effect = lambda: order.append("flush")
    mm_patches["ensure"].side_effect = lambda _s: order.append("ensure")

    show = await ManualMatchOrchestrator(session)._resolve_show_by_tmdb_id(_mm_payload())

    assert show is existing
    assert existing.local_path == "/media/tv/Show"
    assert order == ["flush", "ensure"]
    session.commit.assert_not_awaited()
    mm_patches["sync"].assert_not_awaited()


# ---------------------------------------------------------------------------
# PathImportOrchestrator._tmdb_create_show
# ---------------------------------------------------------------------------


def _pi_orch(
    events: list[tuple[str, str]] | None = None,
) -> tuple[PathImportOrchestrator, AsyncMock]:
    session = AsyncMock()
    session.add = MagicMock()
    session.scalar = AsyncMock(return_value=10)
    tmdb = AsyncMock()
    tmdb.search = AsyncMock(
        return_value={"results": [{"id": 42, "name": "SomeShow", "media_type": "tv"}]}
    )
    tmdb.get_details = AsyncMock(return_value={"name": "SomeShow", "id": 42})
    tmdb.get_external_ids = AsyncMock(return_value={})
    tmdb.get_episode_groups = AsyncMock(return_value={"results": []})

    async def capture(level: str, msg: str, ctx: object = None) -> None:
        if events is not None:
            events.append((level, msg))

    return PathImportOrchestrator(session, tmdb, on_event=capture), session


@pytest.fixture
def pi_patches():
    """Patch episode sync (class level) and alias generation for path import."""
    with (
        patch.object(TMDBOrchestrator, "sync_show_episodes", new=AsyncMock()) as sync,
        patch(_LAZY_ALIASES, new=AsyncMock()) as aliases,
    ):
        yield {"sync": sync, "aliases": aliases}


async def test_path_import_success_call_sequence_and_events(pi_patches) -> None:
    events: list[tuple[str, str]] = []
    orch, session = _pi_orch(events)
    order: list[str] = []
    session.add.side_effect = lambda _o: order.append("add")
    session.flush.side_effect = lambda: order.append("flush")
    session.commit.side_effect = lambda: order.append("commit")
    session.rollback.side_effect = lambda: order.append("rollback")
    pi_patches["sync"].side_effect = lambda _s: order.append("sync")
    pi_patches["aliases"].side_effect = lambda *a, **k: order.append("aliases")

    show, action = await orch._tmdb_create_show("SomeShow")

    assert action == "created" and show is not None
    assert order == ["add", "flush", "commit", "sync", "aliases", "flush"]
    tail = [e for e in events if e[1].startswith(("Created", "Syncing", "Synced", "Generated"))]
    assert [m for _, m in tail] == [
        "Created show 'SomeShow' (id=" + str(show.id) + ", tmdb_id=42)",
        "Syncing episodes for 'SomeShow' from TMDB",
        "Synced 10 episodes for 'SomeShow'",
        "Generated aliases for 'SomeShow'",
    ]


async def test_path_import_sync_db_error_is_swallowed_with_rollback(pi_patches) -> None:
    events: list[tuple[str, str]] = []
    orch, session = _pi_orch(events)
    pi_patches["sync"].side_effect = _db_error()

    show, action = await orch._tmdb_create_show("SomeShow")

    assert action == "created" and show is not None
    session.rollback.assert_awaited_once()
    errors = [m for lvl, m in events if lvl == "error"]
    assert len(errors) == 1 and errors[0].startswith("Episode sync failed for 'SomeShow': ")
    pi_patches["aliases"].assert_awaited_once()
    assert not any(m.startswith("Synced") for _, m in events)


async def test_path_import_episode_count_failure_after_sync_is_treated_as_sync_failure(
    pi_patches,
) -> None:
    events: list[tuple[str, str]] = []
    orch, session = _pi_orch(events)
    session.scalar.side_effect = _db_error()

    show, action = await orch._tmdb_create_show("SomeShow")

    assert action == "created" and show is not None
    pi_patches["sync"].assert_awaited_once()
    session.rollback.assert_awaited_once()
    assert next(m for lvl, m in events if lvl == "error").startswith(
        "Episode sync failed for 'SomeShow': "
    )


async def test_path_import_alias_db_error_is_swallowed_with_rollback(pi_patches) -> None:
    events: list[tuple[str, str]] = []
    orch, session = _pi_orch(events)
    pi_patches["aliases"].side_effect = _db_error()

    show, action = await orch._tmdb_create_show("SomeShow")

    assert action == "created" and show is not None
    session.rollback.assert_awaited_once()
    assert not any(m.startswith("Generated aliases") for _, m in events)


async def test_path_import_alias_flush_failure_rolls_back(pi_patches) -> None:
    orch, session = _pi_orch()
    session.flush.side_effect = [None, RuntimeError("flush failed")]

    show, action = await orch._tmdb_create_show("SomeShow")

    assert action == "created" and show is not None
    session.rollback.assert_awaited_once()


async def test_path_import_sync_and_alias_failures_each_roll_back(pi_patches) -> None:
    orch, session = _pi_orch()
    pi_patches["sync"].side_effect = RuntimeError("sync failed")
    pi_patches["aliases"].side_effect = RuntimeError("alias failed")

    await orch._tmdb_create_show("SomeShow")

    assert session.rollback.await_count == 2


async def test_path_import_race_uses_title_lookup_and_does_not_commit(pi_patches) -> None:
    events: list[tuple[str, str]] = []
    orch, session = _pi_orch(events)
    session.flush.side_effect = IntegrityError("stmt", {}, Exception("dup"))
    existing = MagicMock(spec=Show)
    existing.id = 99
    existing.title = "SomeShow"
    finder = AsyncMock(return_value=existing)

    with patch.object(orch, "_db_find_show", finder):
        show, action = await orch._tmdb_create_show("SomeShow")

    assert (show, action) == (existing, "found")
    finder.assert_awaited_once_with("SomeShow")
    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()
    pi_patches["aliases"].assert_not_awaited()
    assert ("info", "Show 'SomeShow' already existed (concurrent create)") in events


@pytest.mark.parametrize(
    ("failing_prefix", "expected_error_prefix"),
    [
        ("Synced", "Episode sync failed for 'SomeShow': "),
        ("Generated aliases", None),
    ],
)
async def test_path_import_raising_success_event_is_swallowed_with_rollback(
    pi_patches, failing_prefix: str, expected_error_prefix: str | None
) -> None:
    """A raising ``on_event`` for a step's success message counts as that step failing."""
    events: list[tuple[str, str]] = []

    async def flaky(level: str, msg: str, ctx: object = None) -> None:
        if msg.startswith(failing_prefix):
            raise RuntimeError("sink broke")
        events.append((level, msg))

    base, session = _pi_orch()
    orch = PathImportOrchestrator(session, base.tmdb, on_event=flaky)

    show, action = await orch._tmdb_create_show("SomeShow")

    assert action == "created" and show is not None
    session.rollback.assert_awaited_once()
    errors = [m for lvl, m in events if lvl == "error"]
    if expected_error_prefix is None:
        assert errors == []
        pi_patches["aliases"].assert_awaited_once()
    else:
        assert len(errors) == 1 and errors[0].startswith(expected_error_prefix)
        assert "sink broke" in errors[0]
