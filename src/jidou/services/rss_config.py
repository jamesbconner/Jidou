"""Pure functions for parsing, composing, and diffing YaRSS2 RSS config files.

The remote config uses a non-standard format: two concatenated JSON objects
with no separator between them.  ``json.loads()`` rejects this; we use
``json.JSONDecoder.raw_decode()`` to parse each object in turn.

All functions are pure (no I/O) and fully unit-testable.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jidou.models.rss import RssSubscription

logger = logging.getLogger(__name__)

# Remote fields that the downloader manages; remote wins on reconcile.
_REMOTE_OWNED_FIELDS: frozenset[str] = frozenset({"last_match", "last_update", "active"})


@dataclass
class ReconcileDelta:
    """Output of :func:`compute_subscription_deltas`.

    Attributes:
        to_create: Remote subscription dicts not present in the DB.
        to_update: Pairs of (db_row, merged_dict) where the remote and DB
            copies diverged.  The merged dict has remote-owned fields from
            remote and all other fields from the DB row.
        remote_deleted_keys: remote_key strings present in DB rows but absent
            from the remote config (may indicate out-of-band deletion).
    """

    to_create: list[dict[str, object]] = field(default_factory=list)
    to_update: list[tuple[RssSubscription, dict[str, object]]] = field(default_factory=list)
    remote_deleted_keys: list[str] = field(default_factory=list)


def parse_rss_config(raw_content: str) -> tuple[dict[str, object], dict[str, object]]:
    """Parse a YaRSS2 config string into its two component dicts.

    The file format is two JSON objects concatenated with no separator::

        {"file":N,"format":1}{"cookies":{}, "subscriptions":{...}, ...}

    Args:
        raw_content: Raw text content of the remote config file.

    Returns:
        A ``(header, body)`` tuple where *header* is the small metadata object
        and *body* is the main config object containing ``subscriptions``,
        ``rssfeeds``, etc.

    Raises:
        ValueError: If the content cannot be parsed as two consecutive JSON
            objects.
    """
    decoder = json.JSONDecoder()
    try:
        header, offset = decoder.raw_decode(raw_content.strip())
        body, _ = decoder.raw_decode(raw_content.strip(), offset)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse RSS config: {exc}") from exc

    if not isinstance(header, dict) or not isinstance(body, dict):
        raise ValueError("RSS config must consist of two JSON objects")

    return header, body


def compose_rss_config(header: dict[str, object], body: dict[str, object]) -> str:
    """Serialise header and body back into the YaRSS2 two-object format.

    Both objects are serialised as compact JSON (no extra whitespace) and
    concatenated with no separator — matching the format the remote tool
    expects.

    Args:
        header: The small metadata dict (e.g. ``{"file": 1, "format": 1}``).
        body: The main config dict containing ``subscriptions``, ``rssfeeds``,
            etc.

    Returns:
        A string with both objects concatenated.
    """
    return json.dumps(header, separators=(",", ":")) + json.dumps(body, separators=(",", ":"))


def extract_max_subscription_key(body: dict[str, object]) -> int:
    """Return the highest integer subscription key currently in the config.

    Subscription keys are monotonically increasing integer strings (``"0"``,
    ``"1"``, …).  This function returns the maximum so the publisher can
    assign keys for new subscriptions without collisions.

    Args:
        body: The parsed body dict from :func:`parse_rss_config`.

    Returns:
        The maximum key as an ``int``, or ``-1`` if ``subscriptions`` is empty
        or absent (so that ``max + 1`` yields ``0`` as the first valid key).
    """
    subs: dict[str, object] = body.get("subscriptions", {})  # type: ignore[assignment]
    if not subs:
        return -1  # no existing keys; caller should use max+1=0 as first key
    int_keys = [int(k) for k in subs if k.isdigit()]
    return max(int_keys, default=-1)


def compute_subscription_deltas(
    db_subs: list[RssSubscription],
    remote_subs_dict: dict[str, dict[str, object]],
) -> ReconcileDelta:
    """Diff DB subscriptions against the remote config.

    Reconciliation strategy:
    - **Remote wins** for ``last_match``, ``last_update``, ``active`` —
      the downloader updates these out-of-band.
    - **Jidou wins** for all other fields (regex, feed, paths, etc.).
    - Rows with ``remote_key=None`` (Jidou stubs) are ignored; they have no
      remote counterpart to compare against.

    Args:
        db_subs: All ``RssSubscription`` rows from the database.
        remote_subs_dict: The ``subscriptions`` dict from the parsed body
            (keys are string integers, values are subscription dicts).

    Returns:
        :class:`ReconcileDelta` with three lists:
        ``to_create``, ``to_update``, ``remote_deleted_keys``.
    """
    delta = ReconcileDelta()

    db_by_key: dict[str, RssSubscription] = {
        sub.remote_key: sub for sub in db_subs if sub.remote_key is not None
    }

    for key, remote_sub in remote_subs_dict.items():
        if key not in db_by_key:
            # Put remote_key last so it always wins over any remote_key inside remote_sub
            delta.to_create.append({**remote_sub, "remote_key": key})
        else:
            db_row = db_by_key[key]
            merged = dict(remote_sub)
            # Jidou wins for everything except remote-owned fields
            for field_name, db_val in _db_row_fields(db_row).items():
                if field_name not in _REMOTE_OWNED_FIELDS:
                    merged[field_name] = db_val
            delta.to_update.append((db_row, merged))

    # Keys in DB but absent from remote
    for key in db_by_key:
        if key not in remote_subs_dict:
            delta.remote_deleted_keys.append(key)
            logger.warning(
                "Subscription remote_key=%r exists in DB but not in remote config "
                "(possible out-of-band deletion)",
                key,
            )

    return delta


def _db_row_fields(sub: RssSubscription) -> dict[str, object]:
    """Extract the reconcilable scalar fields from a DB subscription row.

    Only fields that Jidou owns (i.e., not remote-managed) are returned.
    Relationship attributes and SQLAlchemy internals are excluded.

    Args:
        sub: An ``RssSubscription`` ORM instance.

    Returns:
        Dict of field name → current DB value.
    """
    return {
        "name": sub.name,
        "regex_include": sub.regex_include,
        "regex_exclude": sub.regex_exclude,
        "regex_include_ignorecase": sub.regex_include_ignorecase,
        "regex_exclude_ignorecase": sub.regex_exclude_ignorecase,
        "download_location": sub.download_location,
        "move_completed": sub.move_completed,
        "label": sub.label,
        # extra_config preserves round-trip remote fields added by Jidou on prior imports
        "extra_config": sub.extra_config,
        # enabled_in_config is Jidou-only; the import orchestrator handles it explicitly
        # and must not merge it into the YaRSS2 subscription dict
    }
