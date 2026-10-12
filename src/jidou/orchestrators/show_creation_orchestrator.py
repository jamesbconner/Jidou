"""Create a library show from TMDB data (shared by every "add a show" flow).

Extracted from ``POST /api/shows`` so other flows, such as onboarding a show
from an RSS feed, reuse one implementation instead of copying the upsert,
metadata fetch, content-type inference and episode sync.
"""

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.show import Show
from jidou.orchestrators._show_provisioning import (
    generate_aliases_best_effort,
    insert_show_or_existing,
    sync_episodes_best_effort,
)
from jidou.orchestrators.tmdb_orchestrator import TMDBOrchestrator
from jidou.schemas.show_schema import ShowCreate
from jidou.services.llm_service import LLMService
from jidou.services.show_creation import auto_local_path, infer_content_type
from jidou.services.sys_name import sanitize_sys_name
from jidou.services.tmdb import TMDBService
from jidou.services.tmdb_mapping import build_show_fields, fetch_show_metadata

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ShowCreationResult:
    """Outcome of :func:`get_or_create_show_from_tmdb`.

    Attributes:
        show: The existing or newly created show.
        created: True when this call inserted the show.
    """

    show: Show
    created: bool


async def _existing_show(session: AsyncSession, tmdb: TMDBService, tmdb_id: int) -> Show | None:
    """Look up a show by TMDB ID and make sure its episode-group map is present.

    Used both for the first lookup and after a lost concurrent-insert race, so
    both paths treat an already-present show identically.

    Args:
        session: Active DB session.
        tmdb: TMDB service.
        tmdb_id: TMDB ID to look up.

    Returns:
        The existing show, or ``None`` when no show has this TMDB ID.
    """
    stmt = select(Show).where(Show.tmdb_id == tmdb_id)
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is None:
        return None
    logger.debug("Show tmdb_id=%d already exists (id=%d)", tmdb_id, existing.id)
    await TMDBOrchestrator(session, tmdb).ensure_episode_group_map(existing)
    return existing


async def _sync_episodes_best_effort(session: AsyncSession, tmdb: TMDBService, show: Show) -> None:
    """Sync a new show's episodes from TMDB, tolerating non-database failures.

    Args:
        session: Active DB session.
        tmdb: TMDB service.
        show: The newly created, flushed show.

    Raises:
        SQLAlchemyError: If the sync's internal flush fails; the session's
            transaction is broken at that point, so it must propagate so the
            caller gets a 500 rather than silently issuing more queries
            against a dead transaction.
    """
    error = await sync_episodes_best_effort(
        session, tmdb, show, reraise_db_errors=True, rollback_on_failure=False
    )
    if error is None:
        logger.info("Auto-synced episodes for show id=%d tmdb_id=%d", show.id, show.tmdb_id)
        return
    logger.warning(
        "Episode sync failed for new show id=%d tmdb_id=%d — user can retry via Sync Episodes",
        show.id,
        show.tmdb_id,
        exc_info=error,
    )


async def _generate_aliases_best_effort(
    session: AsyncSession, tmdb: TMDBService, llm: LLMService, show: Show
) -> None:
    """Generate aliases for a new show, logging instead of raising on failure.

    Args:
        session: Active DB session.
        tmdb: TMDB service.
        llm: LLM service used for alias generation.
        show: The newly created and committed show.
    """
    error = await generate_aliases_best_effort(
        session, tmdb, llm, show, reraise_db_errors=False, rollback_on_failure=False
    )
    if error is not None:
        logger.warning(
            "Alias generation failed for new show id=%d tmdb_id=%d"
            " — aliases can be regenerated via POST /shows/{id}/aliases/regenerate",
            show.id,
            show.tmdb_id,
            exc_info=error,
        )


async def get_or_create_show_from_tmdb(
    session: AsyncSession,
    tmdb: TMDBService,
    payload: ShowCreate,
    *,
    llm: LLMService,
) -> ShowCreationResult:
    """Add a show to the database (upsert by TMDB ID).

    If the show already exists it is returned unchanged.  ``sys_name`` is
    auto-derived from the title if not provided.  The payload is typically a
    TMDB search/trending card, which only carries a sparse field set
    (``genre_ids`` rather than full ``genres`` objects, no
    ``external_ids``/``episode_groups``/etc.) — a full TMDB details fetch is
    attempted so the created show gets complete metadata, matching what the
    manual-match and path-import show-creation paths already do.  A TMDB
    episode sync is then attempted inline so the show detail page shows
    episodes immediately.  Both TMDB steps are best-effort: failures are
    logged but do not abort — the show is still returned, falling back to the
    sparse search-card fields if the details fetch itself fails.

    The show (and any synced episodes) is committed before alias generation,
    so alias generation failing cannot undo it.

    Args:
        session: Active DB session.
        tmdb: TMDB service.
        payload: Show data from a TMDB search/trending result.
        llm: LLM service used for alias generation.

    Returns:
        The show and whether this call created it.

    Raises:
        SQLAlchemyError: If a database operation fails other than the benign
            concurrent-insert race, which resolves to the existing show.
    """
    existing = await _existing_show(session, tmdb, payload.tmdb_id)
    if existing is not None:
        return ShowCreationResult(show=existing, created=False)

    data = payload.model_dump()
    sys_name = data.get("sys_name") or sanitize_sys_name(payload.title)
    content_type = data.get("content_type") or infer_content_type(payload)
    local_path = data.get("local_path") or auto_local_path(content_type, sys_name)
    # genre_ids only feeds infer_content_type above; Show has no such column.
    # sys_name/content_type/local_path are applied explicitly below instead,
    # so drop all four here to keep `data` a plain TMDB-field fallback dict.
    for key in ("genre_ids", "sys_name", "content_type", "local_path"):
        data.pop(key, None)

    try:
        tmdb_data = await fetch_show_metadata(tmdb, payload.tmdb_id, payload.media_type)
        fields = build_show_fields(
            tmdb_data, payload.tmdb_id, payload.media_type, title_fallback=payload.title
        )
    except Exception:
        logger.warning(
            "TMDB details fetch failed for tmdb_id=%d; creating show from search-card "
            "fields only (genres/external_ids/etc. will be incomplete)",
            payload.tmdb_id,
            exc_info=True,
        )
        fields = data
    # build_show_fields derives its own sys_name from the fetched title;
    # the caller-computed one (payload-provided, or derived above) is the
    # one actually used, so it doesn't fight the explicit kwarg below.
    fields.pop("sys_name", None)

    show = Show(
        **fields,
        content_type=content_type,
        local_path=local_path,
        sys_name=sys_name,
        cached=False,
        track_missing_episodes=True,
    )

    async def refind() -> Show:
        winner = await _existing_show(session, tmdb, payload.tmdb_id)
        if winner is None:
            # No winner to return: surface the original IntegrityError.
            raise
        return winner

    show, inserted = await insert_show_or_existing(session, show, refind=refind)
    if not inserted:
        return ShowCreationResult(show=show, created=False)

    logger.info("Added show tmdb_id=%d title=%r (id=%d)", show.tmdb_id, show.title, show.id)

    if show.media_type != "movie":
        await _sync_episodes_best_effort(session, tmdb, show)

    # Commit the show (and any synced episodes) now, independent of alias
    # generation below. sync_show_episodes only flushes, so without this
    # commit a later DB-level failure in alias generation would roll back
    # an already-successful sync too -- both steps are meant to be
    # independently best-effort, not able to undo each other.
    await session.commit()

    await _generate_aliases_best_effort(session, tmdb, llm, show)

    await session.refresh(show)
    return ShowCreationResult(show=show, created=True)
