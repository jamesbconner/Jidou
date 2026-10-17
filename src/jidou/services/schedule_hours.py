"""Parse and normalise a comma-separated list of UTC schedule hours (e.g. ``"2,14"``).

Shared by the settings API (validating user input) and the scheduled job
(deciding whether the current hour is due), so both agree on what is valid.
"""

from datetime import UTC, datetime

_MIN_HOUR = 0
_MAX_HOUR = 23


def parse_schedule_hours(raw: str) -> list[int]:
    """Parse a comma-separated hour list into sorted, unique UTC hours.

    Whitespace around entries and empty entries (``"4,,16"``) are tolerated.

    Args:
        raw: Comma-separated hours, each ``0``-``23``.

    Returns:
        The distinct hours in ascending order.

    Raises:
        ValueError: If an entry is not a whole number from 0 to 23, or no hour
            is given at all.

    Examples:
        >>> parse_schedule_hours("16, 4")
        [4, 16]
    """
    hours: set[int] = set()
    for segment in (part.strip() for part in raw.split(",")):
        if not segment:
            continue
        if not (segment.isascii() and segment.isdigit()):
            raise ValueError(f"Invalid hour {segment!r}: use whole numbers from 0 to 23")
        hour = int(segment)
        if not _MIN_HOUR <= hour <= _MAX_HOUR:
            raise ValueError(f"Invalid hour {segment!r}: must be between 0 and 23")
        hours.add(hour)
    if not hours:
        raise ValueError("Schedule needs at least one hour, e.g. '4' or '2,14'")
    return sorted(hours)


def normalize_schedule_hours(raw: str) -> str:
    """Return *raw* in canonical form: sorted, unique, comma-separated, no padding.

    Args:
        raw: Comma-separated hours, as accepted by :func:`parse_schedule_hours`.

    Returns:
        E.g. ``" 16, 04 ,4"`` becomes ``"4,16"``.

    Raises:
        ValueError: If *raw* is not a valid hour list.
    """
    return ",".join(str(hour) for hour in parse_schedule_hours(raw))


def is_hour_due(hours: str, now: datetime) -> bool:
    """Whether *now* falls in one of the scheduled UTC hours.

    An invalid hour list is treated as "not due" rather than raising, so a
    hand-edited bad value makes the hourly tick skip quietly instead of failing.

    Args:
        hours: Comma-separated hours, as accepted by :func:`parse_schedule_hours`.
        now: A timezone-aware time; compared in UTC, minutes ignored.

    Returns:
        ``True`` if ``now``'s UTC hour is one of *hours*.
    """
    try:
        return now.astimezone(UTC).hour in parse_schedule_hours(hours)
    except ValueError:
        return False
