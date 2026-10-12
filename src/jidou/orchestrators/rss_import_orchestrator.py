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
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.rss import RssConfigSnapshot, RssFeed, RssSubscription
from jidou.models.show import Show
from jidou.orchestrators._events import log_only_event
from jidou.services.callbacks import OnEvent
from jidou.services.fuzzy_match import unambiguous_best_match
from jidou.services.rss_config import compute_subscription_deltas, parse_rss_config
from jidou.services.sftp_service import SFTPService

logger = logging.getLogger(__name__)


def _fuzzy_show_id(name: str, show_by_lower_title: dict[str, int]) -> int | None:
    """Return a show_id for name using exact then token-set-ratio fuzzy match.

    Args:
        name: Subscription name from the remote config.
        show_by_lower_title: Mapping of lowercase show title → show_id.

    Returns:
        Matched show_id, or None if no match meets the threshold.
    """
    exact = show_by_lower_title.get(name.lower())
    if exact is not None:
        return exact
    titles = list(show_by_lower_title.keys())
    index = unambiguous_best_match(name, titles)
    if index is None:
        return None
    logger.debug("_fuzzy_show_id: fuzzy-matched %r -> %r", name, titles[index])
    return show_by_lower_title[titles[index]]


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

# Placeholder feed_id for a brand-new feed in dry-run mode. The real ID only
# exists once the row is actually flushed, but subscription-resolution
# warnings need to tell "this feed key will exist once the real run creates
# it" apart from "this feed key is genuinely unresolvable" -- both currently
# look identical (missing from feed_key_to_id) without this sentinel. Never
# persisted: every write path that uses a resolved feed_id is itself gated
# behind `if not self._dry_run`, so this value never reaches the database.
_DRY_RUN_PENDING_FEED_ID = -1


def _column_values(sub_dict: dict[str, object]) -> dict[str, object]:
    """Return only the recognised column fields from a remote subscription dict."""
    return {k: sub_dict[k] for k in _SUBSCRIPTION_COLUMNS if k in sub_dict}


def _extra_config_for(sub_dict: dict[str, object]) -> dict[str, object] | None:
    """Return the non-column remainder of a remote subscription dict, or None if empty.

    Everything that is not a recognised column (or a key we set explicitly) is
    stashed in ``extra_config`` so it round-trips on the next publish.
    """
    skip = _SUBSCRIPTION_COLUMNS | {"remote_key", "feed_id", "show_id"}
    extra_keys = set(sub_dict.keys()) - skip
    return {k: sub_dict[k] for k in extra_keys} or None


@dataclass
class _LinkIndex:
    """Lookups used to link remote subscriptions to shows and local stubs."""

    show_by_lower_title: dict[str, int]
    stubs_by_show_id: dict[int, RssSubscription]
    stubs_by_lower_name: dict[str, RssSubscription]

    def find_stub(self, name: str, show_id: int | None) -> RssSubscription | None:
        """Return the local stub matching a remote subscription, preferring show_id."""
        return (self.stubs_by_show_id.get(show_id) if show_id else None) or (
            self.stubs_by_lower_name.get(name.lower())
        )

    def evict_stub(self, stub: RssSubscription) -> None:
        """Remove *stub* from both lookups so it can only be promoted once."""
        if stub.show_id is not None:
            self.stubs_by_show_id.pop(stub.show_id, None)
        self.stubs_by_lower_name.pop(stub.name.lower(), None)


@dataclass
class RssImportResult:
    """Summary of a completed RSS config import."""

    feeds_created: int = 0
    feeds_updated: int = 0
    subscriptions_created: int = 0
    subscriptions_updated: int = 0
    subscriptions_remote_deleted: int = 0
    stubs_promoted: int = 0
    shows_linked: int = 0
    snapshot_id: int | None = None
    raw_content: str | None = None
    dry_run: bool = False
    errors: list[str] = field(default_factory=list)


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
        on_event: OnEvent | None = None,
        snapshot_type: str = "import",
    ) -> None:
        self._session = session
        self._sftp = sftp
        self._remote_path = remote_path
        self._dry_run = dry_run
        self._on_event = on_event or log_only_event
        self._snapshot_type = snapshot_type

    async def run(self) -> RssImportResult:
        """Execute the full import sequence.

        Returns:
            :class:`RssImportResult` summarising what was created/updated.
        """
        result = RssImportResult(dry_run=self._dry_run)

        # 1. Download raw config (always download; dry_run only skips writes)
        await self._on_event("info", f"Downloading RSS config from {self._remote_path}", None)
        raw_bytes = await self._sftp.download_bytes(self._remote_path)

        raw_str = raw_bytes.decode("utf-8")
        result.raw_content = raw_str

        # 2. Parse
        try:
            _header, body = parse_rss_config(raw_str)
        except ValueError as exc:
            msg = f"Failed to parse RSS config: {exc}"
            await self._on_event("error", msg, None)
            result.errors.append(msg)
            return result

        # 3. Snapshot (skipped in dry_run)
        if not self._dry_run:
            snapshot = RssConfigSnapshot(snapshot_type=self._snapshot_type, raw_content=raw_str)
            self._session.add(snapshot)
            await self._session.flush()
            result.snapshot_id = snapshot.id
            await self._on_event(
                "info",
                f"Stored config snapshot id={snapshot.id} ({len(raw_str)} bytes)",
                None,
            )
        else:
            await self._on_event(
                "info",
                f"[DRY RUN] Would store config snapshot ({len(raw_str)} bytes)",
                None,
            )

        # 4. Upsert feeds
        rssfeeds: dict[str, object] = body.get("rssfeeds") or {}  # type: ignore[assignment]
        feed_key_to_id = await self._upsert_feeds(rssfeeds, result)

        # 5. Upsert subscriptions
        remote_subs: dict[str, dict[str, object]] = body.get("subscriptions") or {}  # type: ignore[assignment]
        await self._upsert_subscriptions(remote_subs, feed_key_to_id, result)

        await self._on_event(
            "info",
            (
                f"Import complete — feeds: +{result.feeds_created}/~{result.feeds_updated}, "
                f"subscriptions: +{result.subscriptions_created}/~{result.subscriptions_updated}, "
                f"stubs promoted: {result.stubs_promoted}, "
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
            Mapping of remote_key → DB feed_id for foreign-key linking. In
            dry-run mode, a brand-new feed maps to
            :data:`_DRY_RUN_PENDING_FEED_ID` rather than a real id, since the
            row is never actually flushed.
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
                if not self._dry_run:
                    feed = RssFeed(remote_key=key, name=name, url=url, extra_config=extra)
                    self._session.add(feed)
                    await self._session.flush()
                    key_to_id[key] = feed.id
                else:
                    # No real ID exists yet, but the key is resolvable once a
                    # real run creates the feed -- record that with a
                    # placeholder so subscription resolution doesn't mistake
                    # this for a genuinely unresolvable feed key.
                    key_to_id[key] = _DRY_RUN_PENDING_FEED_ID
                result.feeds_created += 1
                logger.debug("Created RssFeed remote_key=%r name=%r", key, name)
            else:
                if not self._dry_run:
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

        logger.debug(
            "feed_key_to_id keys available for subscription linking: %s",
            list(feed_key_to_id.keys()),
        )

        index = await self._load_link_index(db_subs)

        # Create new subscriptions (or promote matching stubs)
        for sub_dict in delta.to_create:
            name = str(sub_dict.get("name", ""))
            show_id = _fuzzy_show_id(name, index.show_by_lower_title)

            stub = index.find_stub(name, show_id)
            if stub is not None:
                await self._promote_stub(stub, sub_dict, show_id, index, feed_key_to_id, result)
            else:
                await self._create_subscription(sub_dict, show_id, feed_key_to_id, result)

        if not self._dry_run:
            await self._session.flush()

        # Update existing subscriptions
        for db_row, merged in delta.to_update:
            await self._apply_update(db_row, merged, index, feed_key_to_id, result)

        if not self._dry_run:
            await self._session.flush()

        # Log remote-deleted keys (don't auto-delete)
        for key in delta.remote_deleted_keys:
            result.subscriptions_remote_deleted += 1
            await self._on_event(
                "warn",
                f"Subscription remote_key={key!r} no longer in remote config (not deleted from DB)",
                {"remote_key": key},
            )

    async def _load_link_index(self, db_subs: list[RssSubscription]) -> _LinkIndex:
        """Build the show-title and stub lookups used to link subscriptions.

        Args:
            db_subs: Every RssSubscription row currently in the database.

        Returns:
            A :class:`_LinkIndex` over the shows table and the local stubs.
        """
        shows_stmt = select(Show.id, Show.title)
        show_rows = (await self._session.execute(shows_stmt)).all()
        show_by_lower_title: dict[str, int] = {r.title.lower(): r.id for r in show_rows}

        # Stubs are rows with remote_key=None created by the watchlist integration.
        # When the remote has a subscription matching a stub (by show_id or name), we promote
        # the stub in-place rather than creating a duplicate row.
        stubs_by_show_id: dict[int, RssSubscription] = {
            sub.show_id: sub
            for sub in db_subs
            if sub.remote_key is None and sub.show_id is not None
        }
        stubs_by_lower_name: dict[str, RssSubscription] = {
            sub.name.lower(): sub for sub in db_subs if sub.remote_key is None
        }
        return _LinkIndex(show_by_lower_title, stubs_by_show_id, stubs_by_lower_name)

    async def _warn_unresolved_feed(
        self,
        remote_key: str | None,
        name: str,
        sub: dict[str, object],
        feed_key_to_id: dict[str, int],
        *,
        on_update: bool,
    ) -> None:
        """Emit the "could not resolve feed" warning event.

        The caller decides *whether* to warn (the conditions differ per path);
        this only owns the wording so the three call sites cannot drift.

        Args:
            remote_key: The subscription's remote key.
            name: The subscription's name.
            sub: Subscription dict (remote or merged) carrying ``rssfeed_key``.
            feed_key_to_id: remote_key → feed DB id mapping, listed in the message.
            on_update: ``True`` selects the "could not resolve feed on update" wording.
        """
        reason = "could not resolve feed on update" if on_update else "could not resolve feed"
        await self._on_event(
            "warn",
            f"Subscription {remote_key!r} ({name!r}): {reason} — "
            f"rssfeed_key={sub.get('rssfeed_key')!r}, "
            f"available feed keys={list(feed_key_to_id.keys())}",
            {"remote_key": remote_key, "rssfeed_key": sub.get("rssfeed_key")},
        )

    async def _promote_stub(
        self,
        stub: RssSubscription,
        sub_dict: dict[str, object],
        show_id: int | None,
        index: _LinkIndex,
        feed_key_to_id: dict[str, int],
        result: RssImportResult,
    ) -> None:
        """Apply a remote subscription onto a matching local stub in-place.

        Args:
            stub: The local stub row (``remote_key=None``) being promoted.
            sub_dict: The remote subscription dict (includes ``remote_key``).
            show_id: Show id fuzzy-matched from the subscription name, if any.
            index: Lookups the stub is evicted from.
            feed_key_to_id: remote_key → feed DB id mapping.
            result: Mutated in-place with promotion / show-link counts.
        """
        sub_key = str(sub_dict.get("remote_key", ""))
        name = str(sub_dict.get("name", ""))
        feed_id = self._resolve_feed_id(sub_dict, feed_key_to_id)

        # Evict from both lookups immediately so a second remote subscription that
        # matches the same stub doesn't overwrite it; that second entry gets a new row.
        index.evict_stub(stub)

        effective_feed_id = feed_id if feed_id is not None else stub.feed_id
        if not self._dry_run:
            stub.remote_key = sub_key
            stub.feed_id = effective_feed_id
            stub.enabled_in_config = True
            stub.extra_config = _extra_config_for(sub_dict)
            if show_id is not None and stub.show_id is None:
                stub.show_id = show_id
                result.shows_linked += 1
            for col, val in _column_values(sub_dict).items():
                setattr(stub, col, val)
        result.stubs_promoted += 1
        logger.debug("Promoted stub id=%d to remote_key=%r name=%r", stub.id, sub_key, name)
        # Only warn if the stub will still have no feed after promotion
        if effective_feed_id is None and feed_key_to_id:
            await self._warn_unresolved_feed(
                sub_key, name, sub_dict, feed_key_to_id, on_update=False
            )

    async def _create_subscription(
        self,
        sub_dict: dict[str, object],
        show_id: int | None,
        feed_key_to_id: dict[str, int],
        result: RssImportResult,
    ) -> None:
        """Create a new RssSubscription row for a remote subscription with no stub.

        Args:
            sub_dict: The remote subscription dict (includes ``remote_key``).
            show_id: Show id fuzzy-matched from the subscription name, if any.
            feed_key_to_id: remote_key → feed DB id mapping.
            result: Mutated in-place with creation / show-link counts.
        """
        sub_key = str(sub_dict.get("remote_key", ""))
        name = str(sub_dict.get("name", ""))
        feed_id = self._resolve_feed_id(sub_dict, feed_key_to_id)

        # Warn when a newly created row will have no feed link
        if feed_id is None and feed_key_to_id:
            await self._warn_unresolved_feed(
                sub_key, name, sub_dict, feed_key_to_id, on_update=False
            )
        new_sub = RssSubscription(
            remote_key=sub_key,
            feed_id=feed_id,
            show_id=show_id,
            extra_config=_extra_config_for(sub_dict),
            enabled_in_config=True,
            **_column_values(sub_dict),
        )
        if not self._dry_run:
            self._session.add(new_sub)
        result.subscriptions_created += 1
        if show_id:
            result.shows_linked += 1
        logger.debug("Created RssSubscription remote_key=%r name=%r", sub_key, name)

    async def _apply_update(
        self,
        db_row: RssSubscription,
        merged: dict[str, object],
        index: _LinkIndex,
        feed_key_to_id: dict[str, int],
        result: RssImportResult,
    ) -> None:
        """Apply the merged remote/DB values to an existing subscription row.

        Args:
            db_row: The existing subscription row.
            merged: Remote dict overlaid with Jidou-owned DB values.
            index: Show lookup used to auto-link a still-unlinked row.
            feed_key_to_id: remote_key → feed DB id mapping.
            result: Mutated in-place with update / show-link counts.
        """
        if not self._dry_run:
            await self._write_update(db_row, merged, feed_key_to_id)

        # Auto-link show: read db_row.show_id but only write in live run
        if db_row.show_id is None:
            name = str(merged.get("name", db_row.name))
            show_id = _fuzzy_show_id(name, index.show_by_lower_title)
            if show_id:
                if not self._dry_run:
                    db_row.show_id = show_id
                result.shows_linked += 1

        result.subscriptions_updated += 1

    async def _write_update(
        self,
        db_row: RssSubscription,
        merged: dict[str, object],
        feed_key_to_id: dict[str, int],
    ) -> None:
        """Write columns, feed link and rebuilt ``extra_config`` onto *db_row* (live run only).

        Args:
            db_row: The existing subscription row.
            merged: Remote dict overlaid with Jidou-owned DB values.
            feed_key_to_id: remote_key → feed DB id mapping.
        """
        for col in _SUBSCRIPTION_COLUMNS:
            if col in merged:
                setattr(db_row, col, merged[col])

        new_feed_id = self._resolve_feed_id(merged, feed_key_to_id)
        if new_feed_id is not None:
            db_row.feed_id = new_feed_id
        elif feed_key_to_id and db_row.feed_id is None:
            await self._warn_unresolved_feed(
                db_row.remote_key, db_row.name, merged, feed_key_to_id, on_update=True
            )

        # Rebuild extra_config: preserve old DB value, overlay with remote
        # non-column fields (e.g. last_update, last_match, active, etc.)
        _extra_skip = _SUBSCRIPTION_COLUMNS | {"remote_key", "feed_id", "extra_config"}
        old_extra = merged.get("extra_config") or {}
        if not isinstance(old_extra, dict):
            old_extra = {}
        remote_extras = {k: merged[k] for k in merged if k not in _extra_skip}
        db_row.extra_config = {**old_extra, **remote_extras} or None

    @staticmethod
    def _resolve_feed_id(
        sub_dict: dict[str, object],
        feed_key_to_id: dict[str, int],
    ) -> int | None:
        """Try to resolve a feed_id from a subscription dict.

        YaRSS2 subscriptions carry the feed key in ``rssfeed_key``.  We look
        up that key in our upserted feed mapping.

        Args:
            sub_dict: Subscription dict (may be remote or merged).
            feed_key_to_id: remote_key → DB id from the feed upsert pass. In
                dry-run mode this may map to :data:`_DRY_RUN_PENDING_FEED_ID`
                for a feed that would be created by a real run.

        Returns:
            DB feed id, or ``None`` if not resolvable.
        """
        raw = sub_dict.get("rssfeed_key")
        if raw is not None and raw != "" and raw is not False:
            feed_key = str(raw)
            if feed_key in feed_key_to_id:
                return feed_key_to_id[feed_key]
            logger.debug(
                "_resolve_feed_id: rssfeed_key=%r not in feed_key_to_id %s",
                feed_key,
                list(feed_key_to_id.keys()),
            )
        else:
            logger.debug(
                "_resolve_feed_id: sub has no rssfeed_key; sub keys=%s",
                [k for k in sub_dict if k != "remote_key"],
            )
        return None
