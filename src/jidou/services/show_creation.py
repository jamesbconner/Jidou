"""Create a library show from TMDB data (shared by every "add a show" flow).

Extracted from ``POST /api/shows`` so other flows, such as onboarding a show
from an RSS feed, reuse one implementation instead of copying the upsert,
metadata fetch, content-type inference and episode sync.
"""

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.show import Show
from jidou.schemas.show_schema import ShowCreate
from jidou.services.llm_service import LLMService
from jidou.services.path_resolution import resolve_show_local_path
from jidou.services.sys_name import sanitize_sys_name
from jidou.services.tmdb import TMDBService

logger = logging.getLogger(__name__)

# TMDB genre ID 16 = Animation
_ANIMATION_GENRE_ID = 16


@dataclass(frozen=True)
class ShowCreationResult:
    """Outcome of :func:`get_or_create_show_from_tmdb`.

    Attributes:
        show: The existing or newly created show.
        created: True when this call inserted the show.
    """

    show: Show
    created: bool


def infer_content_type(payload: ShowCreate) -> str:
    """Infer routing content type from TMDB metadata.

    Rules (applied in order):
    - ``movie`` media type → ``"movie"``
    - Animation genre AND (Japanese language OR JP origin) → ``"anime"``
    - Everything else → ``"tv"``

    Accepts both TMDB response shapes:
    - Search/trending cards supply ``genre_ids: [16, 18]`` (flat int list).
    - Detail endpoints supply ``genres: [{"id": 16, "name": "Animation"}]``.

    Args:
        payload: Show creation payload containing TMDB metadata.

    Returns:
        One of ``"movie"``, ``"anime"``, or ``"tv"``.
    """
    if payload.media_type == "movie":
        return "movie"
    # Collect genre IDs from whichever field the caller populated.
    ids_from_objects = {g.get("id") for g in (payload.genres or [])}
    ids_from_list = set(payload.genre_ids or [])
    all_genre_ids = ids_from_objects | ids_from_list
    is_animated = _ANIMATION_GENRE_ID in all_genre_ids
    is_japanese = payload.original_language == "ja" or "JP" in (payload.origin_country or [])
    if is_animated and is_japanese:
        return "anime"
    return "tv"


def auto_local_path(content_type: str, sys_name: str) -> str:
    """Compute the default local path for a new show from configured media roots.

    Args:
        content_type: One of ``"anime"``, ``"movie"``, or ``"tv"``.
        sys_name: Filesystem-safe show directory name.

    Returns:
        Absolute container-side path string.
    """
    from jidou.config import settings

    return resolve_show_local_path(
        content_type=content_type,
        media_type=None,
        sys_name=sys_name,
        local_tv_path=settings.local_tv_path,
        local_anime_path=settings.local_anime_path,
        local_movie_path=settings.local_movie_path,
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
    from jidou.orchestrators.tmdb_orchestrator import TMDBOrchestrator
    from jidou.services.tmdb_mapping import build_show_fields, fetch_show_metadata

    stmt = select(Show).where(Show.tmdb_id == payload.tmdb_id)
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        logger.debug("Show tmdb_id=%d already exists (id=%d)", payload.tmdb_id, existing.id)
        await TMDBOrchestrator(session, tmdb).ensure_episode_group_map(existing)
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
    session.add(show)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        stmt = select(Show).where(Show.tmdb_id == payload.tmdb_id)
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            logger.debug(
                "Show tmdb_id=%d inserted concurrently, returning existing (id=%d)",
                payload.tmdb_id,
                existing.id,
            )
            await TMDBOrchestrator(session, tmdb).ensure_episode_group_map(existing)
            return ShowCreationResult(show=existing, created=False)
        raise

    logger.info("Added show tmdb_id=%d title=%r (id=%d)", show.tmdb_id, show.title, show.id)

    if show.media_type != "movie":
        try:
            await TMDBOrchestrator(session, tmdb).sync_show_episodes(show)
            logger.info("Auto-synced episodes for show id=%d tmdb_id=%d", show.id, show.tmdb_id)
        except SQLAlchemyError:
            # DB failure during sync's internal flush leaves the session's
            # transaction in a broken state; propagate so the caller gets a
            # 500 rather than silently issuing more queries against a dead
            # transaction.
            raise
        except Exception:
            logger.warning(
                "Episode sync failed for new show id=%d tmdb_id=%d"
                " — user can retry via Sync Episodes",
                show.id,
                show.tmdb_id,
                exc_info=True,
            )

    # Commit the show (and any synced episodes) now, independent of alias
    # generation below. sync_show_episodes only flushes, so without this
    # commit a later DB-level failure in alias generation would roll back
    # an already-successful sync too -- both steps are meant to be
    # independently best-effort, not able to undo each other.
    await session.commit()

    try:
        from jidou.orchestrators.alias_orchestrator import generate_aliases

        await generate_aliases(show, tmdb, llm=llm)
        await session.flush()
    except Exception:
        logger.warning(
            "Alias generation failed for new show id=%d tmdb_id=%d"
            " — aliases can be regenerated via POST /shows/{id}/aliases/regenerate",
            show.id,
            show.tmdb_id,
            exc_info=True,
        )

    await session.refresh(show)
    return ShowCreationResult(show=show, created=True)
