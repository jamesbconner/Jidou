"""Fetch TMDB show metadata and map it onto Show fields.

Consolidates three previously-duplicated implementations (manual file
matching, path-list import, and show rematch) into one fetch step and one
mapping step, so the three no longer drift out of sync with each other.
"""

import logging
from typing import Any

from jidou.models.show import Show
from jidou.services.sys_name import sanitize_sys_name
from jidou.services.tmdb import TMDBService

logger = logging.getLogger(__name__)


async def fetch_episode_groups_list(tmdb: TMDBService, tmdb_id: int) -> list[dict[str, Any]]:
    """Fetch and unwrap the episode_groups summary for a TV show.

    Encapsulates the ``get_episode_groups`` → ``results`` unwrap so the
    pattern isn't duplicated across ``fetch_show_metadata`` and
    ``TMDBOrchestrator._apply_episode_group_map``.

    Args:
        tmdb: Configured TMDBService instance.
        tmdb_id: The TMDB identifier of the TV show.

    Returns:
        List of episode group summary dicts, or empty list on failure.

    Raises:
        Exception: Propagates any TMDB fetch error to the caller (the caller
            decides whether to swallow or re-raise).
    """
    groups_response = await tmdb.get_episode_groups(tmdb_id)
    return list(groups_response.get("results") or [])


async def fetch_show_metadata(tmdb: TMDBService, tmdb_id: int, media_type: str) -> dict[str, Any]:
    """Fetch TMDB show details plus supplemental external_ids and episode_groups.

    ``get_details()`` alone never returns ``external_ids`` or
    ``episode_groups`` — they live behind their own endpoints. Both
    supplemental calls are best-effort: a transient failure falls back to
    an empty value rather than aborting the whole fetch, since they're
    supplementary metadata, not required for a show to exist.

    Args:
        tmdb: Configured TMDBService instance.
        tmdb_id: The TMDB identifier to fetch.
        media_type: ``"tv"`` or ``"movie"``. ``episode_groups`` is only
            fetched for TV — movies have no episode groups.

    Returns:
        The ``get_details()`` response dict, with ``"external_ids"`` and
        ``"episode_groups"`` always present (populated from their own
        endpoints, not left absent as in the raw response).
    """
    data = await tmdb.get_details(tmdb_id, media_type=media_type)

    external_ids: dict[str, Any] = {}
    try:
        external_ids = await tmdb.get_external_ids(tmdb_id, media_type=media_type)
    except Exception:
        logger.debug("get_external_ids failed for tmdb_id=%d", tmdb_id)

    episode_groups: list[dict[str, Any]] = []
    if media_type == "tv":
        try:
            episode_groups = await fetch_episode_groups_list(tmdb, tmdb_id)
        except Exception:
            logger.debug("get_episode_groups failed for tmdb_id=%d", tmdb_id)

    return {**data, "external_ids": external_ids, "episode_groups": episode_groups}


def build_show_fields(
    data: dict[str, Any],
    tmdb_id: int,
    media_type: str,
    *,
    existing: Show | None = None,
    title_fallback: str = "",
) -> dict[str, Any]:
    """Map a TMDB detail response to Show field values.

    Args:
        data: TMDB response dict, ideally from :func:`fetch_show_metadata`
            so ``external_ids``/``episode_groups`` are populated.
        tmdb_id: The TMDB identifier *data* was fetched for.
        media_type: ``"tv"`` or ``"movie"``.
        existing: The Show being updated, if this is a refresh of an
            existing row rather than a new one. When given and
            ``existing.tmdb_id == tmdb_id`` (a same-entity metadata
            refresh, not an identity change), an omitted ``"adult"``
            field falls back to the existing value instead of clearing
            it — TMDB TV detail responses often omit ``"adult"``
            entirely, and a genuine identity change must not carry the
            old entity's flag over. Also used as the title fallback when
            neither the response nor *title_fallback* has one.
        title_fallback: Title to use when *data* has neither ``"name"``
            nor ``"title"`` and *existing* is None (a new show) — e.g. the
            source directory name for a path-based import.

    Returns:
        Dict of field name -> value. Construct a new ``Show(**fields, ...)``
        or apply onto an existing row via ``setattr`` per key. Does not
        include fields that are caller-specific context rather than
        TMDB-derived (``content_type``, ``local_path``, ``aliases``,
        ``aliases_sources``, ``cached``).
    """
    title: str = (
        data.get("name") or data.get("title") or (existing.title if existing else title_fallback)
    )
    release_date: str | None = data.get("first_air_date") or data.get("release_date")
    ep_runtimes: list[int] = data.get("episode_run_time") or []
    runtime: int | None = data.get("runtime") or (ep_runtimes[0] if ep_runtimes else None)

    # TV: origin_country is a flat ISO-code list. Movie: production_countries
    # is a list of {"iso_3166_1": ..., ...} objects — guard against a
    # malformed (non-dict) entry rather than letting it raise.
    tv_countries: list[str] = data.get("origin_country") or []
    movie_countries: list[str] = [
        c["iso_3166_1"]
        for c in (data.get("production_countries") or [])
        if isinstance(c, dict) and "iso_3166_1" in c
    ]
    origin_country = tv_countries or movie_countries

    is_same_entity = existing is not None and existing.tmdb_id == tmdb_id
    adult_fallback = existing.adult if (existing is not None and is_same_entity) else None

    return {
        "tmdb_id": tmdb_id,
        "media_type": media_type,
        "title": title,
        "overview": data.get("overview"),
        "poster_path": data.get("poster_path"),
        "backdrop_path": data.get("backdrop_path"),
        "vote_average": data.get("vote_average"),
        "vote_count": data.get("vote_count", 0),
        "release_date": release_date,
        "original_language": data.get("original_language"),
        "sys_name": sanitize_sys_name(title),
        "genres": data.get("genres") or [],
        "origin_country": origin_country,
        "last_air_date": data.get("last_air_date"),
        "last_episode_to_air": data.get("last_episode_to_air"),
        "next_episode_to_air": data.get("next_episode_to_air"),
        "homepage": data.get("homepage"),
        "external_ids": data.get("external_ids") or {},
        "episode_groups": data.get("episode_groups") or [],
        "status": data.get("status"),
        "in_production": data.get("in_production"),
        "number_of_seasons": data.get("number_of_seasons"),
        "number_of_episodes": data.get("number_of_episodes"),
        "networks": data.get("networks") or [],
        "show_type": data.get("type"),
        "runtime": runtime,
        "tagline": data.get("tagline"),
        "adult": data.get("adult", adult_fallback),
    }
