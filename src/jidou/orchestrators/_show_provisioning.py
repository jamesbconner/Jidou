"""Primitives shared by the orchestrators that create or link shows.

Three flows add a show on demand: ``get_or_create_show_from_tmdb`` (POST /api/shows and feed
onboarding), ``ManualMatchOrchestrator`` (match-by-TMDB-id) and ``PathImportOrchestrator``
(directory import). Each used to carry its own copy of the same three steps: insert and recover
from a lost ``tmdb_id`` race, sync episodes best-effort, and generate aliases best-effort. The
copies differed only in how they treated database errors and whether they rolled back, so those
two choices are explicit flags here.

None of these functions log or emit events: log wording, ``on_event`` messages and HTTP text
differ per caller and stay with the caller, which decides what to say from the returned error.
"""

from collections.abc import Awaitable, Callable

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.show import Show
from jidou.orchestrators.alias_orchestrator import generate_aliases
from jidou.orchestrators.tmdb_orchestrator import TMDBOrchestrator
from jidou.services.llm_service import LLMService
from jidou.services.tmdb import TMDBService


async def insert_show_or_existing[T: Show | None](
    session: AsyncSession,
    show: Show,
    *,
    refind: Callable[[], Awaitable[T]],
) -> tuple[Show | T, bool]:
    """Add and flush a new show, recovering when a concurrent request inserted it first.

    Args:
        session: Active DB session.
        show: The new, unsaved show.
        refind: Looks up the show that won the race. It is awaited after the session has been
            rolled back. It may return ``None`` (the caller decides what that means) or raise,
            for example a bare ``raise`` to surface the original ``IntegrityError``.

    Returns:
        ``(show, True)`` when this call inserted the show, else ``(await refind(), False)``.

    Raises:
        Exception: Whatever ``refind`` raises.
    """
    session.add(show)
    try:
        await session.flush()
    except IntegrityError:
        # The failed flush poisons the transaction; roll back before querying for the winner.
        await session.rollback()
        return await refind(), False
    return show, True


async def _swallow(
    session: AsyncSession,
    exc: Exception,
    *,
    reraise_db_errors: bool,
    rollback_on_failure: bool,
) -> Exception:
    """Apply a best-effort step's failure policy to ``exc``.

    Args:
        session: Active DB session.
        exc: The failure raised by the step.
        reraise_db_errors: Re-raise ``exc`` when it is a ``SQLAlchemyError``.
        rollback_on_failure: Roll the session back when ``exc`` is swallowed.

    Returns:
        ``exc``, once it has been swallowed.

    Raises:
        SQLAlchemyError: ``exc`` itself, when ``reraise_db_errors`` is set.
    """
    if reraise_db_errors and isinstance(exc, SQLAlchemyError):
        # A DB failure inside the step leaves the transaction broken; callers that cannot
        # recover from that must see it rather than keep querying a dead transaction.
        raise exc
    if rollback_on_failure:
        await session.rollback()
    return exc


async def sync_episodes_best_effort(
    session: AsyncSession,
    tmdb: TMDBService,
    show: Show,
    *,
    reraise_db_errors: bool,
    rollback_on_failure: bool,
) -> Exception | None:
    """Sync a show's episodes from TMDB, swallowing failures per the given policy.

    Args:
        session: Active DB session.
        tmdb: TMDB service.
        show: The show whose episodes to sync.
        reraise_db_errors: Re-raise ``SQLAlchemyError`` before the generic handler runs.
        rollback_on_failure: Await ``session.rollback()`` on a swallowed error.

    Returns:
        The swallowed error, or ``None`` when the sync succeeded.

    Raises:
        SQLAlchemyError: Only when ``reraise_db_errors`` is set.
    """
    try:
        await TMDBOrchestrator(session, tmdb).sync_show_episodes(show)
    except Exception as exc:
        return await _swallow(
            session,
            exc,
            reraise_db_errors=reraise_db_errors,
            rollback_on_failure=rollback_on_failure,
        )
    return None


async def generate_aliases_best_effort(
    session: AsyncSession,
    tmdb: TMDBService,
    llm: LLMService | None,
    show: Show,
    *,
    reraise_db_errors: bool,
    rollback_on_failure: bool,
) -> Exception | None:
    """Generate a show's aliases and flush them, swallowing failures per the given policy.

    Args:
        session: Active DB session.
        tmdb: TMDB service.
        llm: LLM service for alias generation, or ``None`` to skip LLM aliases.
        show: The show to generate aliases for.
        reraise_db_errors: Re-raise ``SQLAlchemyError`` before the generic handler runs.
        rollback_on_failure: Await ``session.rollback()`` on a swallowed error.

    Returns:
        The swallowed error, or ``None`` when generation and the flush succeeded.

    Raises:
        SQLAlchemyError: Only when ``reraise_db_errors`` is set.
    """
    try:
        await generate_aliases(show, tmdb, llm=llm)
        await session.flush()
    except Exception as exc:
        return await _swallow(
            session,
            exc,
            reraise_db_errors=reraise_db_errors,
            rollback_on_failure=rollback_on_failure,
        )
    return None
