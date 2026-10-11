"""Onboard a show and an RSS subscription from one feed group in a single step.

Coordinates three existing capabilities that previously needed three separate
user flows (add the show from the Shows page, then add an RSS subscription from
Show Details, then teach the feed's naming):

1. resolve or create the library show (shared TMDB creation service);
2. teach the feed's parsed name as an alias of that show, so later files and
   entries named that way match it directly;
3. create the feed subscription, or adopt an unlinked stub left by an RSS
   import rather than creating a duplicate.

It never publishes to YaRSS2; the user's existing Publish action does that.
"""

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.rss import RssFeed, RssSubscription
from jidou.models.show import Show
from jidou.schemas.rss_schema import FeedAddShowRequest
from jidou.services.alias_handling import add_alias, sanitize_alias
from jidou.services.llm_service import LLMService
from jidou.services.rss_config import fill_missing_yarss2_defaults
from jidou.services.show_creation import get_or_create_show_from_tmdb
from jidou.services.tmdb import TMDBService

logger = logging.getLogger(__name__)


class FeedOnboardingError(Exception):
    """The onboarding request cannot be satisfied.

    Attributes:
        status_code: HTTP status the route layer should answer with.
        detail: User-safe explanation.
    """

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class OnboardingOutcome:
    """What an onboarding call did (or, for a dry run, would do).

    Attributes:
        show: The show, or None when a dry run would create it.
        show_created: The show was (or would be) newly created.
        subscription_id: The subscription's id, or None when a dry run would
            create it.
        subscription_created: A new subscription was (or would be) created.
        adopted_stub: An existing unlinked subscription was (or would be)
            linked to the feed instead of creating a new one.
        alias_added: The parsed name was (or would be) added as a show alias.
        dry_run: Nothing was written.
    """

    show: Show | None
    show_created: bool
    subscription_id: int | None
    subscription_created: bool
    adopted_stub: bool
    alias_added: bool
    dry_run: bool


class FeedOnboardingOrchestrator:
    """Create a show + feed subscription from one feed group.

    Args:
        session: Active async SQLAlchemy session.
        tmdb: TMDB service, used if the show must be created.
        llm: LLM service, used for alias generation on a newly created show.
    """

    def __init__(self, session: AsyncSession, tmdb: TMDBService, llm: LLMService) -> None:
        self.session = session
        self.tmdb = tmdb
        self.llm = llm

    async def add_show_from_feed(
        self, feed: RssFeed, request: FeedAddShowRequest
    ) -> OnboardingOutcome:
        """Resolve the show, teach its alias, and create or adopt the subscription.

        Idempotent: a subscription already linking the show to *feed* is
        returned unchanged, so a retry after a partial failure is safe. The
        show is committed by the creation service before the subscription is
        written; if a later step fails the show remains and a retry reuses it.

        Args:
            feed: The feed the group came from.
            request: The validated onboarding request.

        Returns:
            What was done. With ``request.dry_run`` nothing is written.

        Raises:
            FeedOnboardingError: 404 if ``request.show_id`` does not exist.
        """
        if request.dry_run:
            return await self._plan(feed, request)

        show, created = await self._resolve_show(request)
        alias_added = self._teach_alias(show, request.parsed_name)
        sub, sub_created, adopted = await self._ensure_subscription(feed, show, request)
        await self.session.flush()

        logger.info(
            "Onboarded from feed feed_id=%d show_id=%d show_created=%s "
            "subscription_id=%d subscription_created=%s adopted_stub=%s alias_added=%s",
            feed.id,
            show.id,
            created,
            sub.id,
            sub_created,
            adopted,
            alias_added,
        )
        return OnboardingOutcome(
            show=show,
            show_created=created,
            subscription_id=sub.id,
            subscription_created=sub_created,
            adopted_stub=adopted,
            alias_added=alias_added,
            dry_run=False,
        )

    # -- steps ---------------------------------------------------------------

    async def _load_show(self, show_id: int) -> Show:
        show = (
            await self.session.execute(select(Show).where(Show.id == show_id))
        ).scalar_one_or_none()
        if show is None:
            raise FeedOnboardingError(404, "Show not found")
        return show

    async def _resolve_show(self, request: FeedAddShowRequest) -> tuple[Show, bool]:
        if request.show_id is not None:
            return await self._load_show(request.show_id), False
        assert request.show is not None  # guaranteed by the request validator
        result = await get_or_create_show_from_tmdb(
            self.session, self.tmdb, request.show, llm=self.llm
        )
        return result.show, result.created

    @staticmethod
    def _teach_alias(show: Show, parsed_name: str) -> bool:
        """Add the feed's parsed name as a user alias; True if it was new.

        Skipped when it equals the show's title. The user explicitly picked
        this show for the group, which is the same explicit decision a manual
        file match records.
        """
        name = parsed_name.strip()
        if not name or sanitize_alias(name) == sanitize_alias(show.title):
            return False
        already = sanitize_alias(name) in (show.aliases or [])
        add_alias(show, name)
        return not already

    async def _show_subscriptions(self, show_id: int) -> list[RssSubscription]:
        stmt = (
            select(RssSubscription)
            .where(RssSubscription.show_id == show_id)
            .order_by(RssSubscription.id)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    @staticmethod
    def _find_reusable(
        subs: list[RssSubscription], feed_id: int
    ) -> tuple[RssSubscription | None, bool]:
        """Return ``(subscription, is_unlinked_stub)`` to reuse, if any."""
        for sub in subs:
            if sub.feed_id == feed_id:
                return sub, False
        for sub in subs:
            if sub.feed_id is None:
                return sub, True
        return None, False

    async def _ensure_subscription(
        self, feed: RssFeed, show: Show, request: FeedAddShowRequest
    ) -> tuple[RssSubscription, bool, bool]:
        """Return ``(subscription, created, adopted_stub)``."""
        reusable, is_stub = self._find_reusable(await self._show_subscriptions(show.id), feed.id)

        if reusable is not None and not is_stub:
            return reusable, False, False

        if reusable is not None and is_stub:
            # Adopt the unlinked stub (typically left by an RSS import) rather
            # than creating a duplicate. Only fill what is missing; never
            # overwrite a filter the user already has.
            reusable.feed_id = feed.id
            if not reusable.regex_include:
                reusable.regex_include = request.regex_include
                reusable.regex_include_ignorecase = request.regex_include_ignorecase
            if not reusable.regex_exclude:
                reusable.regex_exclude = request.regex_exclude
                reusable.regex_exclude_ignorecase = request.regex_exclude_ignorecase
            reusable.active = reusable.active or request.enabled
            reusable.enabled_in_config = reusable.enabled_in_config or request.enabled
            return reusable, False, True

        sub = RssSubscription(
            feed_id=feed.id,
            show_id=show.id,
            name=request.name or show.title,
            regex_include=request.regex_include,
            regex_exclude=request.regex_exclude,
            regex_include_ignorecase=request.regex_include_ignorecase,
            regex_exclude_ignorecase=request.regex_exclude_ignorecase,
            # Locations stay unset: publish falls back to the feed's defaults.
            active=request.enabled,
            enabled_in_config=request.enabled,
            extra_config=fill_missing_yarss2_defaults(None),
        )
        self.session.add(sub)
        return sub, True, False

    # -- dry run -------------------------------------------------------------

    async def _plan(self, feed: RssFeed, request: FeedAddShowRequest) -> OnboardingOutcome:
        """Report what :meth:`add_show_from_feed` would do, writing nothing."""
        show: Show | None
        if request.show_id is not None:
            show = await self._load_show(request.show_id)
        else:
            assert request.show is not None  # guaranteed by the request validator
            show = (
                await self.session.execute(select(Show).where(Show.tmdb_id == request.show.tmdb_id))
            ).scalar_one_or_none()

        title = show.title if show is not None else (request.show.title if request.show else "")
        name = request.parsed_name.strip()
        known = {sanitize_alias(a) for a in (show.aliases or [])} if show is not None else set()
        alias_added = bool(name) and sanitize_alias(name) not in known | {sanitize_alias(title)}

        sub_id: int | None = None
        sub_created, adopted = True, False
        if show is not None:
            reusable, is_stub = self._find_reusable(
                await self._show_subscriptions(show.id), feed.id
            )
            if reusable is not None:
                sub_id = reusable.id
                sub_created, adopted = False, is_stub

        return OnboardingOutcome(
            show=show,
            show_created=show is None,
            subscription_id=sub_id,
            subscription_created=sub_created,
            adopted_stub=adopted,
            alias_added=alias_added,
            dry_run=True,
        )
