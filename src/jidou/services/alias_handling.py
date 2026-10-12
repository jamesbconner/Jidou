"""Normalise aliases, compare names to shows, and add aliases to a show record."""

import re

from jidou.models.show import Show

# Anything that is neither a word character nor whitespace. ``\w`` is Unicode-aware,
# so accented and full-width letters and digits (and ``_``) are kept.
_PUNCT = re.compile(r"[^\w\s]")


def sanitize_alias(name: str) -> str:
    """Normalise an alias name for case-insensitive storage and lookup.

    Args:
        name: Raw alias text.

    Returns:
        The name stripped of surrounding whitespace and lowercased.
    """
    return name.strip().lower()


def normalize_name(name: str) -> str:
    """Reduce a title or alias to its case- and punctuation-insensitive key.

    Every character that is not a word character or whitespace becomes a
    space, the text is lowercased, and runs of whitespace collapse to one
    space. Nothing else is folded: there is no Unicode normalisation (so
    "Pokémon" != "Pokemon" and full-width letters stay distinct from ASCII),
    ``&`` is not treated as "and", apostrophes become spaces ("Don't" ->
    "don t"), and leading articles are kept.

    Args:
        name: Raw title, alias or extracted show name.

    Returns:
        The normalised key; empty when *name* has no word characters.

    Examples:
        >>> normalize_name("Daredevil: Born Again")
        'daredevil born again'
    """
    return re.sub(r"\s+", " ", _PUNCT.sub(" ", name).lower()).strip()


def names_agree(name: str, show: Show) -> bool:
    """Return True when *name* is the same name as the show's title or an alias.

    The one name-agreement rule: case- and punctuation-insensitive equality
    (see :func:`normalize_name`) against ``show.title`` or any entry of
    ``show.aliases``. It never matches on a substring, so "Daredevil" does
    not agree with "Daredevil: Born Again", while "Daredevil Born Again" does.

    Names with no word characters (for example "!!!") normalise to the empty
    string; they are compared by their stripped, lowercased text instead so
    that two different punctuation-only names never agree.

    Args:
        name: Name to check, for example a parsed or directory-derived title.
        show: The show to check against.

    Returns:
        True if *name* equals the title or an alias under the rule above.
    """
    key = normalize_name(name)
    candidates = [show.title, *(show.aliases or [])]
    if not key:
        raw = sanitize_alias(name)
        return any(sanitize_alias(c) == raw for c in candidates)
    return any(normalize_name(c) == key for c in candidates)


def add_alias(show: Show, alias: str) -> None:
    """Add a normalised alias to ``show.aliases`` and ``aliases_sources`` in place.

    Mirrors the alias into ``aliases_sources["user"]`` so the structured
    ``PUT /shows/{id}/aliases`` endpoint does not silently drop it when the
    user next edits aliases via the UI (which reads from ``aliases_sources``).
    Adding an alias that is already present is a no-op.

    Callers decide *whether* a name should be added; this only stores it.
    The parse pipeline must not add fuzzy substring hits, while a manual
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
