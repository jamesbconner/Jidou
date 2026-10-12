"""Shared fuzzy title matching used when linking names to shows or subscriptions."""

import logging
from collections.abc import Sequence
from typing import Final

from rapidfuzz import fuzz, process

logger = logging.getLogger(__name__)

# Minimum token-set-ratio score (0-100) for two names to count as the same title.
FUZZY_THRESHOLD: Final = 85


def unambiguous_title_match(
    query: str, candidates: Sequence[str], *, threshold: int = FUZZY_THRESHOLD
) -> int | None:
    """Return the index of the one candidate that matches *query*, exact first.

    An exact case-insensitive match wins even when a fuzzy candidate scores as
    high or is listed earlier. Two or more exact matches are ambiguous and give
    None, the same as a fuzzy tie: they do not fall through to the fuzzy step,
    which would otherwise pick a weaker near-miss over a title that matched
    exactly. With no exact match the fuzzy fallback decides.

    Args:
        query: Name to look up.
        candidates: Names to compare against.
        threshold: Minimum fuzzy score (inclusive) used when nothing matches exactly.

    Returns:
        Index into *candidates* of the match, or None when nothing qualifies or the
        best match is shared by more than one candidate.
    """
    query_lower = query.lower()
    exact = [i for i, c in enumerate(candidates) if c.lower() == query_lower]
    if len(exact) == 1:
        return exact[0]
    if exact:
        logger.debug(
            "unambiguous_title_match: %d candidates match %r exactly - ambiguous",
            len(exact),
            query,
        )
        return None
    return unambiguous_best_match(query, candidates, threshold=threshold)


def unambiguous_best_match(
    query: str, candidates: Sequence[str], *, threshold: int = FUZZY_THRESHOLD
) -> int | None:
    """Return the index of the single best fuzzy match for *query*.

    Both sides are lowercased and scored with ``token_set_ratio``. Callers run
    their own exact-match step first; this is only the fuzzy fallback.

    Args:
        query: Name to look up.
        candidates: Names to compare against.
        threshold: Minimum score (inclusive) a candidate needs to qualify.

    Returns:
        Index into *candidates* of the best match, or None when nothing meets the
        threshold or two candidates share the top score (linking either would be
        a guess).
    """
    # Fetch the top two so a tie at the best score is detectable.
    results = process.extract(
        query.lower(),
        [c.lower() for c in candidates],
        scorer=fuzz.token_set_ratio,
        score_cutoff=threshold,
        limit=2,
    )
    if not results:
        return None
    if len(results) > 1 and results[0][1] == results[1][1]:
        logger.debug(
            "unambiguous_best_match: ambiguous match for %r - %d candidates at score %d",
            query,
            len(results),
            results[0][1],
        )
        return None
    return int(results[0][2])
