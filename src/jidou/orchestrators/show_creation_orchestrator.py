"""Create a library show from TMDB data (shared by every "add a show" flow).

Extracted from ``POST /api/shows`` so other flows, such as onboarding a show
from an RSS feed, reuse one implementation instead of copying the upsert,
metadata fetch, content-type inference and episode sync.
"""

import logging
from dataclasses import asdict, dataclass
from typing import Any, Self

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.show import ContentType, Show
from jidou.orchestrators._show_provisioning import (
    generate_aliases_best_effort,
    insert_show_or_existing,
    sync_episodes_best_effort,
)
from jidou.orchestrators.tmdb_orchestrator import TMDBOrchestrator
from jidou.schemas._base import MediaType
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


# Seed fields the orchestrator applies explicitly (or only uses to derive
# other values), so they are not part of the TMDB-field fallback dict.
# ``genre_ids`` only feeds content-type inference; ``Show`` has no such column.
_NON_FALLBACK_FIELDS = frozenset({"genre_ids", "sys_name", "content_type", "local_path"})


@dataclass(frozen=True)
class ShowSeed:
    """Immutable input to :func:`get_or_create_show_from_tmdb`.

    Mirrors :class:`~jidou.schemas.show_schema.ShowCreate` field-for-field so
    the orchestrator never touches the HTTP schema. Callers build it once at
    their boundary with :meth:`from_create`; a guard test keeps the two field
    sets identical so nothing is silently dropped.

    Attributes mirror the ``ShowCreate`` fields of the same name; see that
    schema for their meaning.
    """

    tmdb_id: int
    title: str
    media_type: MediaType = "tv"
    overview: str | None = None
    poster_path: str | None = None
    backdrop_path: str | None = None
    vote_average: float | None = None
    vote_count: int = 0
    release_date: str | None = None
    original_language: str | None = None
    genres: list[dict[str, object]] | None = None
    genre_ids: list[int] | None = None
    origin_country: list[str] | None = None
    last_air_date: str | None = None
    last_episode_to_air: dict[str, object] | None = None
    next_episode_to_air: dict[str, object] | None = None
    homepage: str | None = None
    external_ids: dict[str, object] | None = None
    episode_groups: list[dict[str, object]] | None = None
    status: str | None = None
    in_production: bool | None = None
    number_of_seasons: int | None = None
    number_of_episodes: int | None = None
    networks: list[dict[str, object]] | None = None
    show_type: str | None = None
    runtime: int | None = None
    tagline: str | None = None
    content_type: ContentType | None = None
    sys_name: str | None = None
    local_path: str | None = None
    adult: bool | None = None

    @classmethod
    def from_create(cls, payload: ShowCreate) -> Self:
        """Build a seed from the HTTP/RSS request schema (deep-copies nested data).

        Args:
            payload: Validated show-creation payload.

        Returns:
            A seed carrying every ``ShowCreate`` field.

        Raises:
            TypeError: If ``ShowCreate`` gains a field this class lacks, so the
                two can never drift apart silently.
        """
        return cls(**payload.model_dump())

    def search_card_fields(self) -> dict[str, Any]:
        """TMDB-field fallback used when the full details fetch fails.

        Returns:
            Field name -> value for every seed field that maps straight onto a
            ``Show`` column (excludes the explicitly-applied fields).
        """
        return {k: v for k, v in asdict(self).items() if k not in _NON_FALLBACK_FIELDS}


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
    payload: ShowSeed,
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
        payload: Show seed built from a TMDB search/trending result.
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

    sys_name = payload.sys_name or sanitize_sys_name(payload.title)
    content_type = payload.content_type or infer_content_type(payload)
    local_path = payload.local_path or auto_local_path(content_type, sys_name)

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
        fields = payload.search_card_fields()
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
