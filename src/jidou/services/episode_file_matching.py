"""Match a parsed episode file entry to an Episode row.

Extracted from :class:`~jidou.orchestrators.path_import_orchestrator.PathImportOrchestrator`
so both bulk text-import and the show-scoped local-directory scan
(``POST /shows/{show_id}/scan-local-files``) share one matching pipeline
instead of maintaining two copies of the same lookup chain.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.episode import Episode
from jidou.services.callbacks import OnEvent
from jidou.services.episode_group_mapping import resolve_declared_season
from jidou.services.episode_lookup import resolve_episode
from jidou.services.episode_match_llm import llm_match_episode, llm_parse_episode
from jidou.services.llm_service import LLMService
from jidou.services.path_parser import ParsedPathEntry


async def _llm_list_fallback(
    session: AsyncSession,
    llm: LLMService | None,
    show_id: int,
    show_title: str,
    filename: str,
    *,
    default_season: int | None,
    default_episode: int | None,
    on_event: OnEvent | None,
) -> tuple[Episode | None, int | None, int | None]:
    """Run the LLM episode-list match and fill gaps in its answer with defaults.

    The LLM may propose only part of a season/episode (or nothing); the
    caller's best-effort values are kept for whichever half it left empty so
    the "No match" diagnostics still say what was attempted.

    Args:
        session: Active async SQLAlchemy session.
        llm: Optional LLMService; None or unavailable yields no proposal.
        show_id: Database ID of the parent show.
        show_title: Show title for the LLM prompt context.
        filename: Basename (or path) of the file being matched.
        default_season: Season reported when the LLM proposes none.
        default_episode: Episode number reported when the LLM proposes none.
        on_event: Optional async callback for progress/log reporting.

    Returns:
        ``(episode, season, episode_number)`` with defaults applied.
    """
    ep, llm_season, llm_episode = await llm_match_episode(
        session, llm, show_id, show_title, filename, on_event=on_event
    )
    return (
        ep,
        llm_season if llm_season is not None else default_season,
        llm_episode if llm_episode is not None else default_episode,
    )


async def _resolve_via_group_remap(
    session: AsyncSession,
    show_id: int,
    episode_group_map: dict[str, object] | None,
    season: int,
    episode: int,
) -> tuple[Episode, int, int] | None:
    """Resolve a declared season/episode TMDB does not have via its episode groups.

    Args:
        session: Active async SQLAlchemy session.
        show_id: Database ID of the parent show.
        episode_group_map: The show's stored episode-group map, or None.
        season: Declared season (> 1) that missed a direct lookup.
        episode: Declared episode number.

    Returns:
        ``(episode_row, real_season, real_episode)`` on a hit, else None.
    """
    remapped = resolve_declared_season(episode_group_map, season, episode)
    if remapped is None:
        return None
    real_season, real_episode = remapped
    remapped_ep = await resolve_episode(session, show_id, real_season, real_episode)
    if remapped_ep is None:
        return None
    return remapped_ep, real_season, real_episode


async def _resolve_with_season(
    session: AsyncSession,
    show_id: int,
    episode_group_map: dict[str, object] | None,
    season: int,
    episode: int,
) -> tuple[Episode, int, int] | None:
    """Resolve a declared season/episode directly, then (season > 1) via episode groups.

    Args:
        session: Active async SQLAlchemy session.
        show_id: Database ID of the parent show.
        episode_group_map: The show's stored episode-group map, or None.
        season: Declared season.
        episode: Declared episode number.

    Returns:
        ``(episode_row, season, episode_number)`` on a hit, else None.
    """
    ep = await resolve_episode(session, show_id, season, episode)
    if ep is not None:
        return ep, season, episode
    if season > 1:
        return await _resolve_via_group_remap(session, show_id, episode_group_map, season, episode)
    return None


async def match_entry_to_episode(
    session: AsyncSession,
    llm: LLMService | None,
    show_id: int,
    show_title: str,
    entry: ParsedPathEntry,
    episode_group_map: dict[str, object] | None = None,
    on_event: OnEvent | None = None,
) -> tuple[Episode | None, int | None, int | None]:
    """Match a parsed path entry to an Episode row.

    Lookup priority:
    1. If regex gave no episode, ask the LLM to parse season/episode from
       the filename alone (lightweight prompt, no episode list needed).
       If that also finds no episode number, step 5 (episode-list title
       match) is tried immediately as a last resort before giving up.
    2. Season + episode DB match (standard S##E## lookup).
    3. On a season>1 miss: episode_groups-based remap — resolves a
       declared season/episode that doesn't exist in TMDB's real
       structure (e.g. a fansub cour-folder for a show TMDB tracks as one
       absolute season) via
       :func:`~jidou.services.episode_group_mapping.resolve_declared_season`.
    4. Absolute episode number column (populated from TMDB episode_groups
       during sync — see :mod:`~jidou.services.episode_group_mapping`).
    5. LLM episode-list match — filename + full episode list sent to the LLM.

    Steps 3-4 are only reachable past step 2's miss; step 4 is also tried
    directly when the entry carries no season at all, using
    ``entry.absolute_candidate`` when set (the raw joined number from an
    ambiguous compact-code guess, e.g. "212" guessed as S02E12) or the
    bare episode number otherwise.

    Args:
        session: Active async SQLAlchemy session.
        llm: Optional LLMService; without it (or if unavailable) only the
            heuristic/DB lookup paths run.
        show_id: Database ID of the parent show.
        show_title: Show title for the LLM prompt context.
        entry: Parsed entry describing the file's position.
        episode_group_map: The show's ``episode_group_map`` (from
            :func:`~jidou.services.episode_group_mapping.to_storage_map`),
            or None if never built.
        on_event: Optional async callback ``(level, msg, ctx)`` for
            progress/log reporting.

    Returns:
        ``(episode, season, episode_number)`` where ``episode`` is the
        matching :class:`Episode` or None, and ``season``/``episode_number``
        are the best-effort season/episode this attempt resolved to —
        including any LLM adjustment — for callers to log accurately even
        when no match was found.
    """
    season = entry.season
    episode = entry.episode
    filename = entry.raw_path.replace("\\", "/").rsplit("/", 1)[-1]

    if episode is None:
        llm_season, llm_episode = await llm_parse_episode(llm, filename, season, on_event=on_event)
        # The directory/regex season wins; the LLM's only fills a gap. Resolved
        # before the fallback so a title match that proposes no season still
        # reports the best season known so far.
        if season is None:
            season = llm_season
        if llm_episode is None:
            # No number anywhere in the filename, and the LLM couldn't parse
            # one either — last resort: match by title against the show's
            # full episode list before giving up entirely.
            return await _llm_list_fallback(
                session,
                llm,
                show_id,
                show_title,
                filename,
                default_season=season,
                default_episode=None,
                on_event=on_event,
            )
        episode = llm_episode

    absolute_guess = entry.absolute_candidate if entry.absolute_candidate is not None else episode

    if season is not None:
        season_hit = await _resolve_with_season(
            session, show_id, episode_group_map, season, episode
        )
        if season_hit is not None:
            return season_hit
        # Season 1 directory (or a season>1 miss the remap could not rescue): the
        # episode number may still be a continuous absolute count (e.g. a show
        # with all 148 episodes in Season 01), or the season/episode pair may
        # itself be an ambiguous compact-code guess whose raw number is the
        # correct absolute episode. Fall through to the absolute-number lookup
        # before the LLM.

    # No season info — this is an absolute episode number.
    abs_ep = await resolve_episode(session, show_id, None, absolute_guess)
    if abs_ep is not None:
        return abs_ep, season, episode

    return await _llm_list_fallback(
        session,
        llm,
        show_id,
        show_title,
        filename,
        default_season=season,
        default_episode=episode,
        on_event=on_event,
    )
