"""Orchestrator for generating and persisting show aliases from TMDB and LLM."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jidou.models.show import Show
    from jidou.services.llm_service import LLMService
    from jidou.services.tmdb import TMDBService

logger = logging.getLogger(__name__)

_PROMPT_FILE = Path(__file__).parent.parent / "services" / "prompts" / "alias_normalize.txt"
_ALIAS_SYSTEM: str = _PROMPT_FILE.read_text(encoding="utf-8")

# TMDB country codes whose alternative titles are included verbatim on the
# no-LLM path.  JP covers Japanese originals; US/GB cover English titles;
# KR covers Korean dramas.
_VERBATIM_COUNTRIES = {"JP", "US", "GB", "KR"}

# Title type keywords that signal a useful transliteration.
_TRANSLITERATION_KEYWORDS = {"romaji", "hepburn", "romanization", "transliteration"}


def _extract_tmdb_aliases(raw: dict[str, object], show_title: str) -> list[str]:
    """Extract and normalize alias strings from a TMDB alternative_titles response.

    Args:
        raw: Raw TMDB ``/alternative_titles`` response dict.
        show_title: Canonical show title used to filter out exact self-matches.

    Returns:
        Deduplicated list of lowercase alias strings.
    """
    # TV uses "results"; movies use "titles".
    entries: list[dict[str, str]] = raw.get("results") or raw.get("titles") or []  # type: ignore[assignment]
    canonical = show_title.strip().lower()
    seen: set[str] = {canonical}
    aliases: list[str] = []
    for entry in entries:
        title: str = (entry.get("title") or "").strip()
        if not title:
            continue
        country: str = (entry.get("iso_3166_1") or "").upper()
        kind: str = (entry.get("type") or "").lower()
        # Include titles from priority countries OR recognised transliteration types.
        is_transliteration = any(kw in kind for kw in _TRANSLITERATION_KEYWORDS)
        if country not in _VERBATIM_COUNTRIES and not is_transliteration:
            continue
        normalised = title.lower()
        if normalised not in seen:
            seen.add(normalised)
            aliases.append(normalised)
    return aliases


async def _llm_aliases(
    show_title: str,
    tmdb_aliases: list[str],
    llm: LLMService,
) -> list[str]:
    """Ask the LLM for additional aliases beyond what TMDB provides.

    Args:
        show_title: Canonical show title.
        tmdb_aliases: Already-extracted TMDB aliases (passed to avoid duplicates).
        llm: Configured LLM service instance.

    Returns:
        List of additional lowercase alias strings, or empty on failure.
    """
    tmdb_list_str = "\n".join(f"- {a}" for a in tmdb_aliases) if tmdb_aliases else "(none)"
    prompt = (
        f"Show title: {show_title}\n\n"
        f"TMDB alternative titles:\n{tmdb_list_str}\n\n"
        "Generate additional aliases."
    )
    response = await llm.complete(prompt=prompt, system=_ALIAS_SYSTEM, max_tokens=512)
    if response is None:
        logger.warning("LLM returned no response for alias generation of %r", show_title)
        return []

    text = response.content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text).rstrip("`").strip()

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("LLM returned invalid JSON for alias generation of %r: %r", show_title, text)
        return []

    if not isinstance(result, list):
        logger.warning("LLM alias response was not a list for %r", show_title)
        return []

    return [str(a).strip().lower() for a in result if isinstance(a, str) and a.strip()]


def _build_flat_aliases(sources: dict[str, list[str]]) -> list[str] | None:
    """Merge all alias sources into a deduplicated flat list.

    Args:
        sources: Dict with keys ``tmdb``, ``llm``, ``user``.

    Returns:
        Deduplicated list or ``None`` when all sources are empty.
    """
    seen: set[str] = set()
    merged: list[str] = []
    for key in ("tmdb", "llm", "user"):
        for alias in sources.get(key) or []:
            if alias and alias not in seen:
                seen.add(alias)
                merged.append(alias)
    return merged or None


async def generate_aliases(
    show: Show,
    tmdb: TMDBService,
    llm: LLMService | None = None,
) -> None:
    """Fetch TMDB alternative titles, optionally augment with LLM aliases, and
    update ``show.aliases_sources`` and ``show.aliases`` in place.

    Existing user-defined aliases are always preserved.  TMDB and LLM sources
    are replaced on each call.  Does NOT flush or commit — the caller is
    responsible for persisting the changes.

    Args:
        show: Show ORM object to update in place.
        tmdb: TMDB service instance.
        llm: Optional LLM service; if ``None`` or unavailable the LLM source
            is cleared and only TMDB aliases are generated.
    """
    # 1. Fetch TMDB alternative titles (cached by TMDBService).
    try:
        raw = await tmdb.get_alternative_titles(show.tmdb_id, media_type=show.media_type)
    except Exception:
        logger.warning(
            "Failed to fetch alternative titles for show id=%d tmdb_id=%d",
            show.id,
            show.tmdb_id,
            exc_info=True,
        )
        raw = {}

    # 2. Extract TMDB aliases.
    tmdb_aliases = _extract_tmdb_aliases(raw, show.title)

    # 3. LLM aliases (optional).
    llm_aliases: list[str] = []
    if llm is not None and llm.is_available():
        try:
            llm_aliases = await _llm_aliases(show.title, tmdb_aliases, llm)
        except Exception:
            logger.warning(
                "LLM alias generation failed for show id=%d; skipping LLM source",
                show.id,
                exc_info=True,
            )

    # 4. Preserve existing user aliases.
    existing: dict[str, list[str]] = show.aliases_sources or {}
    user_aliases: list[str] = existing.get("user") or []

    # 5. Build new sources dict and flat union.
    new_sources: dict[str, list[str]] = {
        "tmdb": tmdb_aliases,
        "llm": llm_aliases,
        "user": user_aliases,
    }
    show.aliases_sources = new_sources
    show.aliases = _build_flat_aliases(new_sources)

    logger.info(
        "Aliases generated for show id=%d: tmdb=%d llm=%d user=%d",
        show.id,
        len(tmdb_aliases),
        len(llm_aliases),
        len(user_aliases),
    )
