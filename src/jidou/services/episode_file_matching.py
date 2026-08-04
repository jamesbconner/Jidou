"""Match a parsed episode file entry to an Episode row.

Extracted from :class:`~jidou.orchestrators.path_import_orchestrator.PathImportOrchestrator`
so both bulk text-import and the show-scoped local-directory scan
(``POST /shows/{show_id}/scan-local-files``) share one matching pipeline
instead of maintaining two copies of the same lookup chain.
"""

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.episode import Episode
from jidou.services.episode_group_mapping import resolve_declared_season
from jidou.services.episode_lookup import resolve_episode
from jidou.services.episode_match_llm import llm_match_episode, llm_parse_episode
from jidou.services.llm_service import LLMService
from jidou.services.path_parser import ParsedPathEntry

OnEvent = Callable[[str, str, dict[str, object] | None], Awaitable[None]]


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
        if llm_episode is None:
            # No number anywhere in the filename, and the LLM couldn't parse
            # one either — last resort: match by title against the show's
            # full episode list before giving up entirely.
            fallback_season = season if season is not None else llm_season
            llm_ep, llm_match_season, llm_match_episode_num = await llm_match_episode(
                session, llm, show_id, show_title, filename, on_event=on_event
            )
            return (
                llm_ep,
                llm_match_season if llm_match_season is not None else fallback_season,
                llm_match_episode_num,
            )
        episode = llm_episode
        if season is None:
            season = llm_season

    absolute_guess = entry.absolute_candidate if entry.absolute_candidate is not None else episode

    if season is not None:
        ep = await resolve_episode(session, show_id, season, episode)
        if ep is not None:
            return ep, season, episode
        if season > 1:
            remapped = resolve_declared_season(episode_group_map, season, episode)
            if remapped is not None:
                real_season, real_episode = remapped
                remapped_ep = await resolve_episode(session, show_id, real_season, real_episode)
                if remapped_ep is not None:
                    return remapped_ep, real_season, real_episode
            # Before giving up to the LLM, try the absolute-number column —
            # the show's real data may use absolute numbering (or this
            # season/episode pair may itself be an ambiguous compact-code
            # guess whose raw number is the correct absolute episode).
            abs_ep = await resolve_episode(session, show_id, None, absolute_guess)
            if abs_ep is not None:
                return abs_ep, season, episode
            llm_ep, llm_match_season, llm_match_episode_num = await llm_match_episode(
                session, llm, show_id, show_title, filename, on_event=on_event
            )
            return (
                llm_ep,
                llm_match_season if llm_match_season is not None else season,
                llm_match_episode_num if llm_match_episode_num is not None else episode,
            )
        # Season 1 directory: the episode number may still be a continuous
        # absolute count (e.g. a show with all 148 episodes in Season 01).
        # Fall through to the absolute-number lookup before the LLM.

    # No season info — this is an absolute episode number.
    abs_ep = await resolve_episode(session, show_id, None, absolute_guess)
    if abs_ep is not None:
        return abs_ep, season, episode

    llm_ep, llm_match_season, llm_match_episode_num = await llm_match_episode(
        session, llm, show_id, show_title, filename, on_event=on_event
    )
    return (
        llm_ep,
        llm_match_season if llm_match_season is not None else season,
        llm_match_episode_num if llm_match_episode_num is not None else episode,
    )
