"""Unit tests for the shared show-provisioning primitives."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

from jidou.models.show import Show
from jidou.orchestrators._show_provisioning import (
    generate_aliases_best_effort,
    insert_show_or_existing,
    sync_episodes_best_effort,
)

_PATCH_BASE = "jidou.orchestrators._show_provisioning"

# (reraise_db_errors, rollback_on_failure)
_FLAG_GRID = [(False, False), (False, True), (True, False), (True, True)]


def _session() -> MagicMock:
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.rollback = AsyncMock()
    return session


async def test_insert_show_or_existing_returns_created_on_success() -> None:
    session = _session()
    show = MagicMock(spec=Show)
    refind = AsyncMock()

    result = await insert_show_or_existing(session, show, refind=refind)

    assert result == (show, True)
    session.add.assert_called_once_with(show)
    session.flush.assert_awaited_once()
    session.rollback.assert_not_awaited()
    refind.assert_not_awaited()


async def test_insert_show_or_existing_uses_supplied_refind() -> None:
    session = _session()
    session.flush.side_effect = IntegrityError("stmt", {}, Exception("dup"))
    order: list[str] = []
    session.rollback.side_effect = lambda: order.append("rollback")
    refound = MagicMock(spec=Show)

    async def refind() -> Show:
        order.append("refind")
        return refound

    result = await insert_show_or_existing(session, MagicMock(spec=Show), refind=refind)

    assert result == (refound, False)
    assert order == ["rollback", "refind"]


async def test_insert_show_or_existing_returns_none_when_refind_finds_nothing() -> None:
    session = _session()
    session.flush.side_effect = IntegrityError("stmt", {}, Exception("dup"))

    result = await insert_show_or_existing(
        session, MagicMock(spec=Show), refind=AsyncMock(return_value=None)
    )

    assert result == (None, False)


async def test_insert_show_or_existing_propagates_refind_error() -> None:
    session = _session()
    session.flush.side_effect = IntegrityError("stmt", {}, Exception("dup"))

    async def refind() -> Show:
        raise  # re-raises the IntegrityError being handled, as the callers do

    with pytest.raises(IntegrityError):
        await insert_show_or_existing(session, MagicMock(spec=Show), refind=refind)

    session.rollback.assert_awaited_once()


async def test_insert_show_or_existing_does_not_catch_other_flush_errors() -> None:
    session = _session()
    session.flush.side_effect = OperationalError("stmt", {}, Exception("conn lost"))
    refind = AsyncMock()

    with pytest.raises(OperationalError):
        await insert_show_or_existing(session, MagicMock(spec=Show), refind=refind)

    session.rollback.assert_not_awaited()
    refind.assert_not_awaited()


@pytest.mark.parametrize(("reraise", "rollback"), _FLAG_GRID)
@pytest.mark.parametrize(
    ("error", "is_db_error"),
    [(OperationalError("stmt", {}, Exception("x")), True), (RuntimeError("boom"), False)],
)
async def test_sync_episodes_best_effort_flag_matrix(
    reraise: bool, rollback: bool, error: Exception, is_db_error: bool
) -> None:
    session = _session()
    show = MagicMock(spec=Show)
    tmdb = MagicMock()
    with patch(f"{_PATCH_BASE}.TMDBOrchestrator") as orch_cls:
        orch_cls.return_value.sync_show_episodes = AsyncMock(side_effect=error)
        if reraise and is_db_error:
            with pytest.raises(SQLAlchemyError) as excinfo:
                await sync_episodes_best_effort(
                    session, tmdb, show, reraise_db_errors=reraise, rollback_on_failure=rollback
                )
            assert excinfo.value is error
            # A re-raised DB error is never rolled back here: the caller owns the dead transaction.
            session.rollback.assert_not_awaited()
        else:
            result = await sync_episodes_best_effort(
                session, tmdb, show, reraise_db_errors=reraise, rollback_on_failure=rollback
            )
            assert result is error
            assert session.rollback.await_count == (1 if rollback else 0)
    orch_cls.assert_called_once_with(session, tmdb)
    orch_cls.return_value.sync_show_episodes.assert_awaited_once_with(show)


async def test_sync_episodes_best_effort_returns_none_on_success() -> None:
    session = _session()
    with patch(f"{_PATCH_BASE}.TMDBOrchestrator") as orch_cls:
        orch_cls.return_value.sync_show_episodes = AsyncMock()
        result = await sync_episodes_best_effort(
            session,
            MagicMock(),
            MagicMock(spec=Show),
            reraise_db_errors=True,
            rollback_on_failure=True,
        )

    assert result is None
    session.rollback.assert_not_awaited()


@pytest.mark.parametrize(("reraise", "rollback"), _FLAG_GRID)
@pytest.mark.parametrize(
    ("error", "is_db_error"),
    [(OperationalError("stmt", {}, Exception("x")), True), (RuntimeError("boom"), False)],
)
async def test_generate_aliases_best_effort_flag_matrix(
    reraise: bool, rollback: bool, error: Exception, is_db_error: bool
) -> None:
    session = _session()
    show = MagicMock(spec=Show)
    tmdb = MagicMock()
    llm = MagicMock()
    with patch(f"{_PATCH_BASE}.generate_aliases", new=AsyncMock(side_effect=error)) as gen:
        if reraise and is_db_error:
            with pytest.raises(SQLAlchemyError) as excinfo:
                await generate_aliases_best_effort(
                    session,
                    tmdb,
                    llm,
                    show,
                    reraise_db_errors=reraise,
                    rollback_on_failure=rollback,
                )
            assert excinfo.value is error
            session.rollback.assert_not_awaited()
        else:
            result = await generate_aliases_best_effort(
                session, tmdb, llm, show, reraise_db_errors=reraise, rollback_on_failure=rollback
            )
            assert result is error
            assert session.rollback.await_count == (1 if rollback else 0)
    gen.assert_awaited_once_with(show, tmdb, llm=llm)
    session.flush.assert_not_awaited()


async def test_generate_aliases_best_effort_flushes_and_returns_none_on_success() -> None:
    session = _session()
    order: list[str] = []
    session.flush.side_effect = lambda: order.append("flush")
    gen = AsyncMock(side_effect=lambda *a, **k: order.append("generate"))
    with patch(f"{_PATCH_BASE}.generate_aliases", new=gen):
        result = await generate_aliases_best_effort(
            session,
            MagicMock(),
            None,
            MagicMock(spec=Show),
            reraise_db_errors=False,
            rollback_on_failure=False,
        )

    assert result is None
    assert order == ["generate", "flush"]


@pytest.mark.parametrize(("reraise", "rollback"), _FLAG_GRID)
async def test_generate_aliases_best_effort_flush_failure_follows_policy(
    reraise: bool, rollback: bool
) -> None:
    session = _session()
    error = RuntimeError("flush failed")
    session.flush.side_effect = error
    with patch(f"{_PATCH_BASE}.generate_aliases", new=AsyncMock()):
        result = await generate_aliases_best_effort(
            session,
            MagicMock(),
            None,
            MagicMock(spec=Show),
            reraise_db_errors=reraise,
            rollback_on_failure=rollback,
        )

    assert result is error
    assert session.rollback.await_count == (1 if rollback else 0)
