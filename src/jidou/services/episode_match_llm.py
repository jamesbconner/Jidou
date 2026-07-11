"""LLM-assisted matching helpers for path-list import.

Three narrowly-scoped LLM calls used when DB-only lookups fail to resolve
a file during path-list import:

- ``llm_parse_episode`` — extract season/episode numbers from a bare
  filename when regex parsing found no episode number.
- ``llm_pick_candidate`` — disambiguate a TMDB search result when no
  candidate's title exactly matches the source directory name.
- ``llm_match_episode`` — match a filename against a show's full episode
  list when no season/episode number could be extracted at all.

Extracted from ``PathImportOrchestrator`` to separate prompt/schema
details from pipeline sequencing.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.episode import Episode
from jidou.services.llm_json import parse_llm_json, sanitize_for_prompt
from jidou.services.llm_service import LLMService

if TYPE_CHECKING:
    from jidou.services.path_parser import ParsedPathEntry

logger = logging.getLogger(__name__)

OnEvent = Callable[[str, str, dict[str, object] | None], Awaitable[None]]

_LLM_EPISODE_PARSE_SYSTEM = (
    "You are a TV episode filename parser. Extract only the season and "
    "episode numbers from the filename.\n\n"
    "Rules:\n"
    "- A bare trailing number with no other marker is the episode number, "
    'never the season (e.g. "Show 09" -> episode 9, season null).\n'
    "- Only set season when it is explicitly marked (S02, Season 2, "
    "2nd Season, etc.). Never infer season from a bare number.\n"
    '- Version suffixes like "01v2" mean episode 1.\n'
    "- Tokens like NCED, NCOP, OP, ED, PV, CM, SP, OVA, or OAD indicate "
    "non-episode bonus content, not a numbered episode, unless an explicit "
    "SxxEyy or E## marker is also present — set episode to null for these.\n"
    "- If you cannot determine the episode with confidence, set episode to "
    "null rather than guessing.\n\n"
    "Reply with ONLY a compact JSON object: "
    '{"season": <integer or null>, "episode": <integer or null>}. '
    "No other text, no markdown, no explanation."
)

_LLM_EPISODE_PARSE_RESPONSE_FORMAT: dict[str, object] = {
    "type": "json_schema",
    "json_schema": {
        "name": "episode_parse",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "season": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                "episode": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
            },
            "required": ["season", "episode"],
            "additionalProperties": False,
        },
    },
}

_LLM_SHOW_MATCH_SYSTEM = (
    "You are a TV show title matcher. "
    "Given a directory name and a numbered list of TMDB candidates, "
    "identify which candidate is the same show as the directory. "
    'Directories often omit articles ("Marvel\'s", "The") or franchise subtitles '
    '("Born Again") that appear in TMDB titles — treat those as matches. '
    "A sequel or spin-off with a shared word is NOT a match unless the directory "
    "clearly refers to that specific entry. "
    'Example: "Daredevil" matches "Marvel\'s Daredevil" but NOT "Daredevil: Born Again". '
    'Reply with ONLY a compact JSON object: {"match": <candidate number (1, 2, 3, ...) or null>}. '
    "Use null if no candidate matches. No other text, no markdown, no explanation."
)

_LLM_SHOW_MATCH_RESPONSE_FORMAT: dict[str, object] = {
    "type": "json_schema",
    "json_schema": {
        "name": "show_match",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "match": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
            },
            "required": ["match"],
            "additionalProperties": False,
        },
    },
}

_LLM_SYSTEM = (
    "You are a filename-to-episode matcher. "
    "Given a show title, a filename, and a numbered episode list, "
    "identify which episode the file belongs to. "
    "Reply with ONLY a compact JSON object: "
    '{"season": <integer or null>, "episode": <integer or null>}. '
    "Use null for season or episode if you cannot determine the match. "
    "No other text, no markdown, no explanation."
)

_LLM_MATCH_RESPONSE_FORMAT: dict[str, object] = {
    "type": "json_schema",
    "json_schema": {
        "name": "episode_match",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "season": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                "episode": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
            },
            "required": ["season", "episode"],
            "additionalProperties": False,
        },
    },
}


async def _emit(
    on_event: OnEvent | None, level: str, msg: str, ctx: dict[str, object] | None = None
) -> None:
    if on_event:
        await on_event(level, msg, ctx)


async def llm_parse_episode(
    llm: LLMService | None,
    filename: str,
    known_season: int | None = None,
    *,
    on_event: OnEvent | None = None,
) -> tuple[int | None, int | None]:
    """Use the LLM to extract season and episode numbers from a filename.

    Called when regex parsing in :mod:`~jidou.services.path_parser` returns
    ``episode=None``.  Uses a lightweight prompt that asks only for season
    and episode — the show is already known from the directory.

    Args:
        llm: LLMService instance, or None to skip (returns immediately).
        filename: Basename of the episode file.
        known_season: Season already inferred from the directory path, if any.
            Passed as a grounding hint to reduce hallucination.
        on_event: Optional async callback(level, message, ctx) for
            structured event log entries.

    Returns:
        ``(season, episode)`` tuple; either value may be None.
    """
    if llm is None or not llm.is_available():
        return None, None

    hint = f"\nKnown season from directory: {known_season}" if known_season is not None else ""
    try:
        response = await llm.complete(
            prompt=f"Filename: {sanitize_for_prompt(filename)}{hint}",
            system=_LLM_EPISODE_PARSE_SYSTEM,
            response_format=_LLM_EPISODE_PARSE_RESPONSE_FORMAT,
        )
    except Exception as exc:
        logger.warning("LLM episode-parse failed for %r", filename)
        await _emit(on_event, "warn", f"LLM episode-parse failed for '{filename}': {exc}")
        return None, None

    if response is None:
        await _emit(on_event, "warn", f"LLM episode-parse returned no response for '{filename}'")
        return None, None

    parsed = parse_llm_json(response.content)
    if parsed is None:
        logger.warning(
            "LLM returned invalid JSON for episode parse of %r: %r", filename, response.content
        )
        await _emit(
            on_event,
            "warn",
            f"LLM episode-parse returned invalid JSON for '{filename}': {response.content!r}",
        )
        return None, None

    if not isinstance(parsed, dict):
        logger.warning(
            "LLM returned non-dict JSON for episode parse of %r: %r", filename, response.content
        )
        content = response.content
        await _emit(
            on_event,
            "warn",
            f"LLM episode-parse returned non-object JSON for '{filename}': {content!r}",
        )
        return None, None

    raw_season = parsed.get("season")
    raw_episode = parsed.get("episode")
    try:
        season = int(raw_season) if raw_season is not None else None
        episode = int(raw_episode) if raw_episode is not None else None
    except (TypeError, ValueError):
        logger.warning("LLM returned non-integer S/E for %r: %r", filename, parsed)
        await _emit(
            on_event,
            "warn",
            f"LLM episode-parse returned non-integer season/episode for '{filename}'",
        )
        return None, None

    logger.debug("LLM episode-parse: %r → season=%s episode=%s", filename, season, episode)
    await _emit(
        on_event,
        "info",
        f"LLM episode-parse: '{filename}' -> season={season} episode={episode}",
        {"filename": filename, "season": season, "episode": episode},
    )
    return season, episode


async def llm_pick_candidate(
    llm: LLMService | None,
    show_dir: str,
    candidates: list[dict[str, Any]],
    *,
    on_event: OnEvent | None = None,
) -> dict[str, Any] | None:
    """Ask the LLM to pick the best TMDB candidate for show_dir.

    Only called when exact normalized matching fails across all candidates.
    Handles cases like "Daredevil" → "Marvel's Daredevil" where the directory
    omits a leading article or franchise tag that TMDB includes in the title.

    Args:
        llm: LLMService instance, or None to skip (returns immediately).
        show_dir: Show directory name to match.
        candidates: TMDB search result dicts, each with at least ``"name"``.
        on_event: Optional async callback(level, message, ctx) for
            structured event log entries.

    Returns:
        The chosen candidate dict, or None if the LLM is unavailable or
        cannot determine a match.
    """
    if llm is None or not llm.is_available():
        return None

    shortlist = candidates[:10]
    lines = [
        f"{i + 1}. {c.get('name')} ({str(c.get('first_air_date') or '')[:4] or '?'})"
        for i, c in enumerate(shortlist)
    ]
    prompt = f'Directory: "{sanitize_for_prompt(show_dir)}"\n\nCandidates:\n' + "\n".join(lines)

    try:
        response = await llm.complete(
            prompt=prompt,
            system=_LLM_SHOW_MATCH_SYSTEM,
            response_format=_LLM_SHOW_MATCH_RESPONSE_FORMAT,
        )
    except Exception as exc:
        logger.warning("LLM show-match failed for %r", show_dir)
        await _emit(on_event, "warn", f"LLM show-match failed for '{show_dir}': {exc}")
        return None

    if response is None:
        await _emit(on_event, "warn", f"LLM show-match returned no response for '{show_dir}'")
        return None

    parsed = parse_llm_json(response.content)
    if parsed is None:
        logger.warning(
            "LLM returned invalid JSON for show-match of %r: %r", show_dir, response.content
        )
        await _emit(
            on_event,
            "warn",
            f"LLM show-match returned invalid JSON for '{show_dir}': {response.content!r}",
        )
        return None

    raw_match = parsed.get("match") if isinstance(parsed, dict) else None
    if raw_match is None:
        await _emit(on_event, "warn", f"LLM show-match could not pick a candidate for '{show_dir}'")
        return None

    try:
        idx = int(raw_match) - 1
    except (TypeError, ValueError):
        logger.warning("LLM returned non-integer match %r for show dir %r", raw_match, show_dir)
        await _emit(
            on_event, "warn", f"LLM show-match returned a non-integer pick for '{show_dir}'"
        )
        return None

    if 0 <= idx < len(shortlist):
        await _emit(
            on_event,
            "info",
            f"LLM show-match: '{show_dir}' -> '{shortlist[idx].get('name')}'",
            {"show_dir": show_dir, "picked": shortlist[idx].get("name")},
        )
        return shortlist[idx]

    logger.warning("LLM returned out-of-range index %d for show dir %r", idx + 1, show_dir)
    await _emit(on_event, "warn", f"LLM show-match returned an out-of-range pick for '{show_dir}'")
    return None


async def llm_match_episode(
    session: AsyncSession,
    llm: LLMService | None,
    show_id: int,
    show_title: str,
    entry: "ParsedPathEntry",
    *,
    on_event: OnEvent | None = None,
) -> tuple[Episode | None, int | None, int | None]:
    """Ask the LLM to identify the episode from the filename.

    Only called after all DB-based lookup strategies have failed.

    Args:
        session: Active async SQLAlchemy session.
        llm: LLMService instance, or None to skip (returns immediately).
        show_id: Database ID of the parent show.
        show_title: Show title for prompt context.
        entry: Parsed entry with the raw file path.
        on_event: Optional async callback(level, message, ctx) for
            structured event log entries.

    Returns:
        ``(episode, season, episode_number)`` where ``episode`` is the
        matching :class:`Episode` or None (LLM unavailable, unconfident,
        or its proposed season/episode has no matching DB row), and
        ``season``/``episode_number`` are the values the LLM actually
        proposed — None if it never got far enough to propose any — so
        callers can log what was attempted even on a miss.
    """
    if llm is None or not llm.is_available():
        return None, None, None

    eps = list(
        (
            await session.execute(
                select(Episode)
                .where(Episode.show_id == show_id)
                .order_by(Episode.season_number, Episode.episode_number)
            )
        )
        .scalars()
        .all()
    )
    if not eps:
        return None, None, None

    ep_list = "\n".join(
        f"S{ep.season_number:02d}E{ep.episode_number:02d}: {ep.name}" for ep in eps[:500]
    )
    filename = entry.raw_path.replace("\\", "/").rsplit("/", 1)[-1]
    prompt = (
        f"Show: {sanitize_for_prompt(show_title)}\n"
        f"Filename: {sanitize_for_prompt(filename)}\n\n"
        f"Episodes:\n{ep_list}"
    )

    try:
        response = await llm.complete(
            prompt=prompt,
            system=_LLM_SYSTEM,
            response_format=_LLM_MATCH_RESPONSE_FORMAT,
        )
    except Exception as exc:
        logger.warning("LLM match failed for %r in show %r", filename, show_title)
        await _emit(on_event, "warn", f"LLM episode-list match failed for '{filename}': {exc}")
        return None, None, None

    if response is None:
        await _emit(
            on_event, "warn", f"LLM episode-list match returned no response for '{filename}'"
        )
        return None, None, None

    parsed = parse_llm_json(response.content)
    if parsed is None:
        content = response.content
        logger.warning("LLM returned invalid JSON for match of %r: %r", filename, content)
        await _emit(
            on_event,
            "warn",
            f"LLM episode-list match returned invalid JSON for '{filename}': {content!r}",
        )
        return None, None, None

    if not isinstance(parsed, dict):
        logger.warning("LLM returned non-dict JSON for match of %r: %r", filename, response.content)
        content = response.content
        await _emit(
            on_event,
            "warn",
            f"LLM episode-list match returned non-object JSON for '{filename}': {content!r}",
        )
        return None, None, None

    raw_season = parsed.get("season")
    raw_episode = parsed.get("episode")
    if raw_season is None or raw_episode is None:
        await _emit(
            on_event,
            "warn",
            f"LLM episode-list match could not identify '{filename}' among episodes",
        )
        return None, None, None

    try:
        season, episode_num = int(raw_season), int(raw_episode)
    except (TypeError, ValueError):
        logger.warning("LLM returned non-integer S/E for %r: %r", filename, parsed)
        await _emit(
            on_event,
            "warn",
            f"LLM episode-list match returned non-integer season/episode for '{filename}'",
        )
        return None, None, None

    stmt = select(Episode).where(
        Episode.show_id == show_id,
        Episode.season_number == season,
        Episode.episode_number == episode_num,
    )
    ep = (await session.execute(stmt)).scalar_one_or_none()
    if ep is not None:
        logger.info(
            "LLM matched %r -> S%02dE%02d for show %r",
            filename,
            season,
            episode_num,
            show_title,
        )
        await _emit(
            on_event,
            "info",
            f"LLM episode-list match: '{filename}' -> S{season:02d}E{episode_num:02d}",
            {"filename": filename, "season": season, "episode": episode_num},
        )
    else:
        await _emit(
            on_event,
            "warn",
            f"LLM episode-list match proposed S{season:02d}E{episode_num:02d} for "
            f"'{filename}' but no such episode exists in the DB",
            {"filename": filename, "season": season, "episode": episode_num},
        )
    return ep, season, episode_num
