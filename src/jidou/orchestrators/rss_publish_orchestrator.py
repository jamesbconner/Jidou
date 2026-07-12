"""Orchestrator for publishing a composed YaRSS2 config back to the remote server.

Run sequence:
1. Run RssImportOrchestrator with snapshot_type="pre_publish" to reconcile out-of-band
   changes and capture a pre-publish snapshot.
2. Parse the pre-publish snapshot's raw_content to extract (header, old_body) for round-trip.
3. Back up the current remote file by uploading raw bytes to a timestamped path.
4. Build new rssfeeds dict from DB RssFeed rows that have a remote_key.
5. Build new subscriptions dict from RssSubscription rows with enabled_in_config=True.
   - Rows with remote_key: use it as the dict key.
   - New stubs (no remote_key): assign keys sequentially from max_existing_key + 1;
     persist keys back to DB unless dry_run.
   - download_location / move_completed fall back to feed defaults when not set on the sub.
6. Assemble new body preserving all non-managed sections from old_body verbatim.
7. compose_rss_config(header, new_body) → upload via sftp.upload_bytes().
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from jidou.models.rss import RssFeed, RssSubscription
from jidou.orchestrators.rss_import_orchestrator import (
    RssImportOrchestrator,
    _default_on_event,
)
from jidou.services.rss_config import (
    compose_rss_config,
    extract_max_subscription_key,
    fill_missing_yarss2_defaults,
    parse_rss_config,
)
from jidou.services.sftp_service import SFTPService

logger = logging.getLogger(__name__)

_OnEvent = Callable[[str, str, "dict[str, object] | None"], Awaitable[None]]

# Sections from old_body that Jidou does not manage; everything else is rebuilt from DB.
_MANAGED_SECTIONS = frozenset({"rssfeeds", "subscriptions"})


@dataclass
class RssPublishResult:
    """Summary of a completed RSS config publish."""

    feeds_published: int = 0
    subscriptions_published: int = 0
    new_keys_assigned: int = 0
    snapshot_id: int | None = None
    backup_path: str | None = None
    dry_run: bool = False
    errors: list[str] = field(default_factory=list)


class RssPublishOrchestrator:
    """Composes and uploads a new YaRSS2 config from the Jidou database.

    Args:
        session: Active async SQLAlchemy session.
        sftp: Configured SFTP service pointing at the remote host.
        remote_path: Full remote path to the YaRSS2 config file.
        dry_run: When ``True``, compute the new config without uploading.
        on_event: Optional async callback ``(level, message, ctx)`` for
            structured log events surfaced to the task event log.
        deluge_stop_command: Optional shell command run over SSH before the
            backup/upload so Deluge's own autosave cannot clobber the write.
            If it fails, the publish aborts before touching any remote files.
        deluge_restart_command: Optional shell command run over SSH after the
            backup/upload, in a ``finally`` block, so Deluge always comes back
            up and reloads the new config — even if the upload itself failed.
    """

    def __init__(
        self,
        session: AsyncSession,
        sftp: SFTPService | None,
        remote_path: str,
        dry_run: bool = False,
        on_event: _OnEvent | None = None,
        deluge_stop_command: str | None = None,
        deluge_restart_command: str | None = None,
    ) -> None:
        self._session = session
        self._sftp = sftp
        self._remote_path = remote_path
        self._dry_run = dry_run
        self._on_event = on_event or _default_on_event
        if bool(deluge_stop_command) != bool(deluge_restart_command):
            raise ValueError(
                "deluge_stop_command and deluge_restart_command must be set together "
                "— a stop command with no restart command would leave Deluge down"
            )
        self._deluge_stop_command = deluge_stop_command
        self._deluge_restart_command = deluge_restart_command

    async def run(self) -> RssPublishResult:
        """Execute the full publish sequence.

        Returns:
            :class:`RssPublishResult` summarising what was published.

        Raises:
            ValueError: If constructed with only one of deluge_stop_command /
                deluge_restart_command set, or if this instance was constructed
                without an sftp service — valid for a compose_config()-only
                instance (e.g.
                the download-preview route), but run() needs real SFTP
                access for import reconciliation, backup, and upload.
        """
        if self._sftp is None:
            raise ValueError("run() requires an sftp service; this instance was built without one")
        result = RssPublishResult(dry_run=self._dry_run)

        # 1. Reconcile out-of-band changes and store a pre_publish snapshot.
        # Always run live (dry_run=False) so the DB reflects remote state before we
        # build the publish payload. The dry_run flag only governs uploads (steps 3 & 7).
        await self._on_event("info", "Running pre-publish import reconciliation", None)
        import_orc = RssImportOrchestrator(
            session=self._session,
            sftp=self._sftp,
            remote_path=self._remote_path,
            dry_run=False,
            on_event=self._on_event,
            snapshot_type="pre_publish",
        )
        import_result = await import_orc.run()
        if import_result.errors:
            result.errors.extend(import_result.errors)
            return result
        result.snapshot_id = import_result.snapshot_id

        # 2. Parse the downloaded content to get header and old_body for round-trip
        raw_str = import_result.raw_content or ""
        try:
            header, old_body = parse_rss_config(raw_str)
        except ValueError as exc:
            msg = f"Failed to re-parse config for publish: {exc}"
            await self._on_event("error", msg, None)
            result.errors.append(msg)
            return result

        # 3. Stop the remote Deluge service so it cannot clobber this write with its
        # own autosave, and so it re-reads the config fresh once restarted. If the
        # stop command fails, abort before touching any remote files — Deluge's
        # state is unknown and there is nothing to restart.
        if self._deluge_stop_command:
            if not self._dry_run:
                await self._on_event("info", "Stopping remote Deluge service", None)
                try:
                    await self._sftp.run_command(self._deluge_stop_command)
                except Exception as exc:
                    msg = f"Failed to stop remote Deluge service; aborting publish: {exc}"
                    logger.error(msg)
                    result.errors.append(msg)
                    await self._on_event("error", msg, None)
                    return result
            else:
                await self._on_event("info", "[DRY RUN] Would stop remote Deluge service", None)

        try:
            # 4. Back up the current remote file
            ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            remote = PurePosixPath(self._remote_path)
            backup_path = str(remote.with_name(f"{remote.stem}_backup_{ts}{remote.suffix}"))
            result.backup_path = backup_path
            if not self._dry_run:
                await self._sftp.upload_bytes(raw_str.encode("utf-8"), backup_path)
                await self._on_event("info", f"Backed up current config to {backup_path}", None)
            else:
                await self._on_event(
                    "info", f"[DRY RUN] Would back up current config to {backup_path}", None
                )

            # 5-7. Build feeds + subscriptions dicts from DB and assemble the new body.
            composed, compose_result = await self.compose_config(
                header, old_body, upload=not self._dry_run
            )
            result.feeds_published = compose_result.feeds_published
            result.subscriptions_published = compose_result.subscriptions_published
            result.new_keys_assigned = compose_result.new_keys_assigned

            # 8. Upload
            if not self._dry_run:
                await self._sftp.upload_bytes(composed.encode("utf-8"), self._remote_path)
                await self._on_event(
                    "info",
                    (
                        f"Published config to {self._remote_path} — "
                        f"{result.feeds_published} feeds, "
                        f"{result.subscriptions_published} subscriptions "
                        f"({result.new_keys_assigned} new keys assigned)"
                    ),
                    None,
                )
            else:
                await self._on_event(
                    "info",
                    (
                        f"[DRY RUN] Would publish config to {self._remote_path} — "
                        f"{result.feeds_published} feeds, "
                        f"{result.subscriptions_published} subscriptions "
                        f"({result.new_keys_assigned} new keys assigned)"
                    ),
                    None,
                )
        finally:
            # 9. Always try to bring Deluge back up if we stopped it — even if the
            # backup/compose/upload above raised.
            if self._deluge_restart_command:
                if not self._dry_run:
                    await self._on_event("info", "Restarting remote Deluge service", None)
                    try:
                        await self._sftp.run_command(self._deluge_restart_command)
                    except Exception as exc:
                        msg = f"Failed to restart remote Deluge service: {exc}"
                        logger.error(msg)
                        result.errors.append(msg)
                        await self._on_event("error", msg, None)
                else:
                    await self._on_event(
                        "info", "[DRY RUN] Would restart remote Deluge service", None
                    )

        return result

    async def compose_config(
        self,
        header: dict[str, object],
        old_body: dict[str, object],
        *,
        upload: bool,
    ) -> tuple[str, RssPublishResult]:
        """Build feeds + subscriptions from DB and assemble the full config text.

        Shared by :meth:`run` (composing what will actually be uploaded) and
        the ``GET /rss/download`` route (composing a preview/download that
        never uploads) — the single implementation of "what would Jidou
        publish right now", so the two can no longer drift out of sync.

        Args:
            header: Config header block, preserved verbatim.
            old_body: Previously-parsed config body; used to seed the max
                subscription key and to preserve all non-managed sections.
            upload: When True, persist newly-assigned subscription
                remote_key values to the DB (this composition is about to
                be uploaded). When False (a preview/download), compute
                keys without persisting them.

        Returns:
            ``(composed_text, result)`` where *result*'s feeds_published /
            subscriptions_published / new_keys_assigned counts reflect
            this call only.
        """
        result = RssPublishResult(dry_run=not upload)

        new_feeds = await self._build_feeds_dict(result)

        # Seed max_key from both the remote body and all existing DB remote_keys so
        # that remote-deleted subscriptions (still in DB with a remote_key but absent
        # from old_body) cannot collide with keys assigned to new stubs.
        remote_max_key = extract_max_subscription_key(old_body)
        all_keys_stmt = select(RssSubscription.remote_key).where(
            RssSubscription.remote_key.is_not(None)
        )
        all_key_rows = (await self._session.execute(all_keys_stmt)).scalars().all()
        db_max_key = max(
            (int(k) for k in all_key_rows if k and k.isdigit()),
            default=-1,
        )
        max_key = max(remote_max_key, db_max_key)
        new_subs = await self._build_subscriptions_dict(max_key, result, upload=upload)

        # Commit new remote_key assignments before uploading so they are durable even
        # if the remote upload succeeds but a subsequent session operation rolls back.
        if result.new_keys_assigned > 0 and upload:
            await self._session.commit()

        new_body: dict[str, object] = {
            k: v for k, v in old_body.items() if k not in _MANAGED_SECTIONS
        }
        new_body["rssfeeds"] = new_feeds
        new_body["subscriptions"] = new_subs

        composed = compose_rss_config(header, new_body)
        return composed, result

    async def _build_feeds_dict(self, result: RssPublishResult) -> dict[str, object]:
        """Build the rssfeeds dict from DB RssFeed rows that have a remote_key.

        Active feeds are always included.  Inactive feeds are also included if
        at least one enabled subscription still references them — omitting them
        would leave dangling rssfeed_key values in the subscriptions output.
        A warning is logged for each such feed.

        Args:
            result: Mutated in-place with feeds_published count.

        Returns:
            Dict of remote_key → feed dict for the new config.
        """
        # Collect feed IDs referenced by enabled subscriptions
        ref_stmt = select(RssSubscription.feed_id).where(
            RssSubscription.enabled_in_config.is_(True),
            RssSubscription.feed_id.is_not(None),
        )
        referenced_feed_ids: set[int] = {
            int(fid)
            for fid in (await self._session.execute(ref_stmt)).scalars().all()
            if fid is not None
        }

        stmt = select(RssFeed).where(RssFeed.remote_key.is_not(None))
        feeds = list((await self._session.execute(stmt)).scalars().all())
        new_feeds: dict[str, object] = {}
        for feed in feeds:
            if feed.remote_key is None:
                continue
            if not feed.active:
                if feed.id not in referenced_feed_ids:
                    continue
                logger.warning(
                    "Feed id=%d remote_key=%r is inactive but referenced by enabled "
                    "subscriptions — including in publish to avoid orphaned rssfeed_key values",
                    feed.id,
                    feed.remote_key,
                )
            feed_dict: dict[str, object] = {}
            if feed.extra_config:
                feed_dict.update(feed.extra_config)
            # DB column values overlay extra_config (DB wins)
            feed_dict["name"] = feed.name
            feed_dict["url"] = feed.url
            feed_dict["active"] = feed.active
            new_feeds[feed.remote_key] = feed_dict
            result.feeds_published += 1
        return new_feeds

    async def _build_subscriptions_dict(
        self,
        max_key: int,
        result: RssPublishResult,
        *,
        upload: bool,
    ) -> dict[str, object]:
        """Build the subscriptions dict from rows with enabled_in_config=True.

        Stubs without a remote_key are assigned sequential integer keys starting
        from max_key + 1.  Keys are persisted back to the DB row when *upload*
        is True.

        Args:
            max_key: Highest existing integer key from the old config body.
            result: Mutated in-place with subscriptions_published and new_keys_assigned.
            upload: When True, persist newly-assigned remote_key values to
                the DB. When False (a preview/download), compute keys
                without persisting them.

        Returns:
            Dict of remote_key → subscription dict for the new config.
        """
        stmt = (
            select(RssSubscription)
            .where(RssSubscription.enabled_in_config.is_(True))
            .options(selectinload(RssSubscription.feed))
            .order_by(RssSubscription.id.asc())
        )
        subs = list((await self._session.execute(stmt)).scalars().all())

        new_subs: dict[str, object] = {}
        next_key = max_key + 1

        for sub in subs:
            if sub.remote_key:
                key = sub.remote_key
            else:
                key = str(next_key)
                next_key += 1
                if upload:
                    sub.remote_key = key
                result.new_keys_assigned += 1

            new_subs[key] = self.build_sub_dict(sub, key)
            result.subscriptions_published += 1

        if result.new_keys_assigned > 0 and upload:
            await self._session.flush()

        return new_subs

    @staticmethod
    def build_sub_dict(sub: RssSubscription, key: str) -> dict[str, object]:
        """Serialise one RssSubscription row to a YaRSS2 subscription dict.

        Starts with the standard YaRSS2 torrent-option defaults (so a
        freshly Jidou-created subscription still carries every key YaRSS2's
        own UI would write), then extra_config to round-trip a real
        subscription's remote values over those defaults, then overlays DB
        column values so Jidou's values always win.  download_location and
        move_completed fall back to feed-level defaults when not set on the
        sub.

        Args:
            sub: The subscription row (feed relationship must be pre-loaded).
            key: This subscription's key in the published config's
                subscriptions dict -- also embedded in the subscription
                dict itself, mirroring what YaRSS2's own UI writes.

        Returns:
            Dict representing the subscription in YaRSS2 format.
        """
        sub_dict = fill_missing_yarss2_defaults(sub.extra_config)

        # DB column values always win
        sub_dict["key"] = key
        sub_dict["name"] = sub.name
        sub_dict["regex_include_ignorecase"] = sub.regex_include_ignorecase
        sub_dict["regex_exclude_ignorecase"] = sub.regex_exclude_ignorecase
        sub_dict["active"] = sub.active
        if sub.regex_include is not None:
            sub_dict["regex_include"] = sub.regex_include
        if sub.regex_exclude is not None:
            sub_dict["regex_exclude"] = sub.regex_exclude
        if sub.label is not None:
            sub_dict["label"] = sub.label
        if sub.last_match is not None:
            sub_dict["last_match"] = sub.last_match

        # download_location / move_completed: row value, then feed default
        dl_loc = sub.download_location or (sub.feed.default_download_location if sub.feed else None)
        mv_loc = sub.move_completed or (sub.feed.default_move_completed if sub.feed else None)
        if dl_loc is not None:
            sub_dict["download_location"] = dl_loc
        if mv_loc is not None:
            sub_dict["move_completed"] = mv_loc

        if sub.feed is not None and sub.feed.remote_key is not None:
            sub_dict["rssfeed_key"] = sub.feed.remote_key

        return sub_dict
