"""Orchestrator for importing a YaRSS2 RSS config file into the database.

Run sequence:
1. Download the raw config from the remote SFTP path.
2. Parse the two-object concatenated JSON format.
3. Store an ``RssConfigSnapshot`` for auditability.
4. Upsert ``RssFeed`` rows from the ``rssfeeds`` section.
5. Upsert ``RssSubscription`` rows from the ``subscriptions`` section using
   the reconciliation strategy in :func:`~jidou.services.rss_config.compute_subscription_deltas`.
6. Emit log events for keys that disappeared from the remote (not auto-deleted).
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.rss import RssConfigSnapshot, RssFeed, RssSubscription
from jidou.models.show import Show
from jidou.services.rss_config import compute_subscription_deltas, parse_rss_config
from jidou.services.sftp_service import SFTPService

logger = logging.getLogger(__name__)

_OnEvent = Callable[[str, str, "dict[str, object] | None"], Awaitable[None]]

# Fields carried from the parsed remote dict directly into a new DB row.
# Remote-owned fields (last_match, active) are included so the initial row
# reflects what the remote says at import time.
_SUBSCRIPTION_COLUMNS = frozenset(
    {
        "name",
        "regex_include",
        "regex_exclude",
        "regex_include_ignorecase",
        "regex_exclude_ignorecase",
        "download_location",
        "move_completed",
        "active",
        "label",
        "last_match",
    }
)


@dataclass
class RssImportResult:
    """Summary of a completed RSS config import."""

    feeds_created: int = 0
    feeds_updated: int = 0
    subscriptions_created: int = 0
    subscriptions_updated: int = 0
    subscriptions_remote_deleted: int = 0
    shows_linked: int = 0
    snapshot_id: int | None = None
    dry_run: bool = False
    errors: list[str] = field(default_factory=list)


async def _default_on_event(level: str, msg: str, ctx: dict[str, object] | None = None) -> None:
    """No-op event callback used when caller does not provide one."""
    logger.log(logging.INFO if level == "info" else logging.WARNING, "%s", msg)


class RssImportOrchestrator:
    """Imports a remote YaRSS2 config into the Jidou database.

    Args:
        session: Active async SQLAlchemy session.
        sftp: Configured SFTP service pointing at the remote host.
        remote_path: Full remote path to the YaRSS2 config file.
        dry_run: When ``True``, parse and reconcile without writing to the DB.
        on_event: Optional async callback ``(level, message, ctx)`` for
            structured log events surfaced to the task event log.
    """

    def __init__(
        self,
        session: AsyncSession,
        sftp: SFTPService,
        remote_path: str,
        dry_run: bool = False,
        on_event: _OnEvent | None = None,
    ) -> None:
        self._session = session
        self._sftp = sftp
        self._remote_path = remote_path
        self._dry_run = dry_run
        self._on_event = on_event or _default_on_event

    async def run(self) -> RssImportResult:
        """Execute the full import sequence.

        Returns:
            :class:`RssImportResult` summarising what was created/updated.
        """
        result = RssImportResult(dry_run=self._dry_run)

        # 1. Download raw config
        await self._on_event("info", f"Downloading RSS config from {self._remote_path}", None)
        raw_bytes = await self._sftp.download_bytes(self._remote_path, dry_run=self._dry_run)

        if self._dry_run:
            await self._on_event("info", "[DRY RUN] Skipping parse and DB writes", None)
            return result

        raw_str = raw_bytes.decode("utf-8")

        # 2. Parse
        try:
            _header, body = parse_rss_config(raw_str)
        except ValueError as exc:
            msg = f"Failed to parse RSS config: {exc}"
            await self._on_event("error", msg, None)
            result.errors.append(msg)
            return result

        # 3. Snapshot
        snapshot = RssConfigSnapshot(snapshot_type="import", raw_content=raw_str)
        self._session.add(snapshot)
        await self._session.flush()
        result.snapshot_id = snapshot.id
        await self._on_event(
            "info",
            f"Stored config snapshot id={snapshot.id} ({len(raw_str)} bytes)",
            None,
        )

        # 4. Upsert feeds
        rssfeeds: dict[str, object] = body.get("rssfeeds", {})  # type: ignore[assignment]
        feed_key_to_id = await self._upsert_feeds(rssfeeds, result)

        # 5. Upsert subscriptions
        remote_subs: dict[str, dict[str, object]] = body.get("subscriptions", {})  # type: ignore[assignment]
        await self._upsert_subscriptions(remote_subs, feed_key_to_id, result)

        await self._on_event(
            "info",
            (
                f"Import complete — feeds: +{result.feeds_created}/~{result.feeds_updated}, "
                f"subscriptions: +{result.subscriptions_created}/~{result.subscriptions_updated}, "
                f"remote-deleted: {result.subscriptions_remote_deleted}, "
                f"shows linked: {result.shows_linked}"
            ),
            None,
        )
        return result

    async def _upsert_feeds(
        self,
        rssfeeds: dict[str, object],
        result: RssImportResult,
    ) -> dict[str, int]:
        """Upsert RssFeed rows from the rssfeeds section.

        Args:
            rssfeeds: Dict of remote_key → feed dict from the parsed body.
            result: Mutated in-place with feed counts.

        Returns:
            Mapping of remote_key → DB feed_id for foreign-key linking.
        """
        key_to_id: dict[str, int] = {}

        for key, raw_feed in rssfeeds.items():
            feed_dict: dict[str, object] = raw_feed  # type: ignore[assignment]
            name = str(feed_dict.get("name", key))
            url = str(feed_dict.get("url", ""))

            stmt = select(RssFeed).where(RssFeed.remote_key == key)
            existing = (await self._session.execute(stmt)).scalar_one_or_none()

            # Build extra_config from non-column fields
            known = {"name", "url"}
            extra = {k: v for k, v in feed_dict.items() if k not in known} or None

            if existing is None:
                feed = RssFeed(
                    remote_key=key,
                    name=name,
                    url=url,
                    extra_config=extra,
                )
                self._session.add(feed)
                await self._session.flush()
                key_to_id[key] = feed.id
                result.feeds_created += 1
                logger.debug("Created RssFeed remote_key=%r name=%r", key, name)
            else:
                existing.name = name
                existing.url = url
                existing.extra_config = extra
                await self._session.flush()
                key_to_id[key] = existing.id
                result.feeds_updated += 1
                logger.debug("Updated RssFeed id=%d remote_key=%r", existing.id, key)

        return key_to_id

    async def _upsert_subscriptions(
        self,
        remote_subs: dict[str, dict[str, object]],
        feed_key_to_id: dict[str, int],
        result: RssImportResult,
    ) -> None:
        """Upsert RssSubscription rows using the reconciliation delta.

        Args:
            remote_subs: Dict of remote_key → subscription dict.
            feed_key_to_id: remote_key → feed DB id mapping.
            result: Mutated in-place with subscription counts.
        """
        db_subs_stmt = select(RssSubscription)
        db_subs = list((await self._session.execute(db_subs_stmt)).scalars().all())

        delta = compute_subscription_deltas(db_subs, remote_subs)

        # Build show title lookup for auto-linking
        shows_stmt = select(Show.id, Show.title)
        show_rows = (await self._session.execute(shows_stmt)).all()
        show_by_lower_title: dict[str, int] = {r.title.lower(): r.id for r in show_rows}

        # Create new subscriptions
        for sub_dict in delta.to_create:
            sub_key = str(sub_dict.get("remote_key", ""))
            name = str(sub_dict.get("name", ""))

            # Derive feed_id from the remote sub's feed reference (if any)
            feed_id = self._resolve_feed_id(sub_dict, feed_key_to_id)
            show_id = show_by_lower_title.get(name.lower())

            # Extract only recognised column fields; stash the rest in extra_config
            col_vals = {k: sub_dict[k] for k in _SUBSCRIPTION_COLUMNS if k in sub_dict}
            _skip = _SUBSCRIPTION_COLUMNS | {"remote_key", "feed_id", "show_id"}
            extra_keys = set(sub_dict.keys()) - _skip
            extra = {k: sub_dict[k] for k in extra_keys} or None

            new_sub = RssSubscription(
                remote_key=sub_key,
                feed_id=feed_id,
                show_id=show_id,
                extra_config=extra,
                **col_vals,
            )
            self._session.add(new_sub)
            result.subscriptions_created += 1
            if show_id:
                result.shows_linked += 1
            logger.debug("Created RssSubscription remote_key=%r name=%r", sub_key, name)

        await self._session.flush()

        # Update existing subscriptions
        for db_row, merged in delta.to_update:
            for col in _SUBSCRIPTION_COLUMNS:
                if col in merged:
                    setattr(db_row, col, merged[col])

            # Update feed linkage if we have a resolution
            new_feed_id = self._resolve_feed_id(merged, feed_key_to_id)
            if new_feed_id is not None:
                db_row.feed_id = new_feed_id

            # Auto-link show if not already linked
            if db_row.show_id is None:
                name = str(merged.get("name", db_row.name))
                show_id = show_by_lower_title.get(name.lower())
                if show_id:
                    db_row.show_id = show_id
                    result.shows_linked += 1

            # Preserve DB extra_config (already in merged from _db_row_fields)
            if "extra_config" in merged:
                raw_extra = merged["extra_config"]
                db_row.extra_config = raw_extra if isinstance(raw_extra, dict) else None

            result.subscriptions_updated += 1

        await self._session.flush()

        # Log remote-deleted keys (don't auto-delete)
        for key in delta.remote_deleted_keys:
            result.subscriptions_remote_deleted += 1
            await self._on_event(
                "warn",
                f"Subscription remote_key={key!r} no longer in remote config (not deleted from DB)",
                {"remote_key": key},
            )

    @staticmethod
    def _resolve_feed_id(
        sub_dict: dict[str, object],
        feed_key_to_id: dict[str, int],
    ) -> int | None:
        """Try to resolve a feed_id from a subscription dict.

        YaRSS2 subscriptions carry the feed key in a ``feedID`` or ``feed_key``
        field.  We look up that key in our upserted feed mapping.

        Args:
            sub_dict: Subscription dict (may be remote or merged).
            feed_key_to_id: remote_key → DB id from the feed upsert pass.

        Returns:
            DB feed id, or ``None`` if not resolvable.
        """
        for field_name in ("feedID", "feed_key", "feed_id"):
            raw = sub_dict.get(field_name)
            if raw is None:
                continue
            feed_key = str(raw)
            if feed_key in feed_key_to_id:
                return feed_key_to_id[feed_key]
        return None
