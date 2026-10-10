"""Teach a show a new alias so future parses of the same name match it."""

from jidou.models.show import Show


def sanitize_alias(name: str) -> str:
    """Normalise an alias name for case-insensitive storage and lookup.

    Args:
        name: Raw alias text.

    Returns:
        The name stripped of surrounding whitespace and lowercased.
    """
    return name.strip().lower()


def add_alias(show: Show, alias: str) -> None:
    """Add a normalised alias to ``show.aliases`` and ``aliases_sources`` in place.

    Mirrors the alias into ``aliases_sources["user"]`` so the structured
    ``PUT /shows/{id}/aliases`` endpoint does not silently drop it when the
    user next edits aliases via the UI (which reads from ``aliases_sources``).
    Adding an alias that is already present is a no-op.

    Callers decide *whether* a name should be taught; this only stores it.
    The parse pipeline must not teach fuzzy substring hits, while a manual
    match is an explicit user decision and may.

    Args:
        show: The show to update (mutated in place; not flushed or committed).
        alias: Alias text to add.
    """
    norm = sanitize_alias(alias)
    # Flat GIN-indexed column — used for fast show lookup during parsing.
    current: list[str] = list(show.aliases) if show.aliases else []
    if norm not in current:
        show.aliases = [*current, norm]
    # Structured source map — used by the UI and the PUT endpoint.
    sources: dict[str, list[str]] = dict(show.aliases_sources) if show.aliases_sources else {}
    if not show.aliases_sources and show.aliases:
        # First-time write on a legacy show: seed the user bucket from all
        # existing flat aliases so that generate_aliases or a UI save doesn't
        # orphan them when it rebuilds show.aliases from sources only.
        sources["user"] = list(show.aliases)
        show.aliases_sources = sources  # persist even if norm is already present
    user_aliases: list[str] = list(sources.get("user") or [])
    if norm not in user_aliases:
        sources["user"] = [*user_aliases, norm]
        show.aliases_sources = sources
