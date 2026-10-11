"""Tests for onboarding a show + subscription from a feed group."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jidou.models.rss import RssFeed, RssSubscription
from jidou.models.show import Show
from jidou.orchestrators.feed_onboarding_orchestrator import (
    FeedOnboardingError,
    FeedOnboardingOrchestrator,
)
from jidou.schemas.rss_schema import FeedAddShowRequest
from jidou.schemas.show_schema import ShowCreate
from jidou.services.show_creation import ShowCreationResult

CREATE_PATH = "jidou.orchestrators.feed_onboarding_orchestrator.get_or_create_show_from_tmdb"


def _show(*, id: int = 42, title: str = "Brand New Show", aliases: list[str] | None = None):
    s = MagicMock(spec=Show)
    s.id = id
    s.title = title
    s.aliases = aliases
    s.aliases_sources = None
    return s


def _sub(*, id: int = 1, feed_id: int | None = None, regex_include=None, regex_exclude=None):
    s = MagicMock(spec=RssSubscription)
    s.id = id
    s.feed_id = feed_id
    s.regex_include = regex_include
    s.regex_exclude = regex_exclude
    s.regex_include_ignorecase = True
    s.regex_exclude_ignorecase = True
    s.active = False
    s.enabled_in_config = False
    return s


def _feed(feed_id: int = 7) -> MagicMock:
    f = MagicMock(spec=RssFeed)
    f.id = feed_id
    return f


class _Session:
    """Routes ``select(Show)`` and ``select(RssSubscription)`` to canned rows."""

    def __init__(self, *, show: Show | None = None, subs: list[RssSubscription] | None = None):
        self.show = show
        self.subs = subs or []
        self.added: list[object] = []
        self.flush = AsyncMock()

    async def execute(self, stmt: object) -> MagicMock:
        sql = str(stmt)
        result = MagicMock()
        if RssSubscription.__tablename__ in sql.split("FROM", 1)[-1].split()[0]:
            result.scalars.return_value.all.return_value = list(self.subs)
        else:
            result.scalar_one_or_none.return_value = self.show
        return result

    def add(self, obj: object) -> None:
        obj.id = 100  # type: ignore[attr-defined]
        self.added.append(obj)


def _orch(session: _Session) -> FeedOnboardingOrchestrator:
    return FeedOnboardingOrchestrator(session, MagicMock(), MagicMock())  # type: ignore[arg-type]


def _req(**kw) -> FeedAddShowRequest:
    base = {"parsed_name": "brand new show (2024)", "show_id": 42}
    base.update(kw)
    return FeedAddShowRequest(**base)


@pytest.fixture
def create_show() -> Iterator[AsyncMock]:
    with patch(CREATE_PATH, new=AsyncMock()) as m:
        yield m


# --------------------------- request validation ---------------------------


def test_request_requires_exactly_one_show_source() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        FeedAddShowRequest(parsed_name="x")
    with pytest.raises(ValueError, match="exactly one"):
        FeedAddShowRequest(parsed_name="x", show_id=1, show=ShowCreate(tmdb_id=1, title="X"))


def test_request_rejects_uncompilable_regex() -> None:
    with pytest.raises(ValueError, match="Invalid regular expression"):
        _req(regex_include="(unclosed")


# --------------------------------- creation --------------------------------


async def test_existing_library_show_gets_a_new_subscription_and_alias() -> None:
    show = _show()
    session = _Session(show=show)

    out = await _orch(session).add_show_from_feed(
        _feed(),
        _req(regex_include="Brand.New.Show.*1080p", regex_exclude="FRENCH", enabled=True),
    )

    assert (out.show_created, out.subscription_created, out.adopted_stub) == (False, True, False)
    assert out.alias_added is True
    (sub,) = session.added
    assert isinstance(sub, RssSubscription)
    assert (sub.feed_id, sub.show_id, sub.name) == (7, 42, "Brand New Show")
    assert (sub.regex_include, sub.regex_exclude) == ("Brand.New.Show.*1080p", "FRENCH")
    assert sub.active is True and sub.enabled_in_config is True
    assert sub.download_location is None  # publish falls back to the feed defaults
    assert "brand new show (2024)" in show.aliases
    session.flush.assert_awaited()


async def test_not_enabled_keeps_the_subscription_out_of_publish() -> None:
    session = _Session(show=_show())

    await _orch(session).add_show_from_feed(_feed(), _req(enabled=False))

    (sub,) = session.added
    assert sub.active is False and sub.enabled_in_config is False


async def test_custom_subscription_name_is_used() -> None:
    session = _Session(show=_show())

    await _orch(session).add_show_from_feed(_feed(), _req(name="Custom Name"))

    assert session.added[0].name == "Custom Name"


async def test_new_tmdb_show_is_created_through_the_shared_service(create_show) -> None:
    created = _show(id=77, title="Fresh Show")
    create_show.return_value = ShowCreationResult(show=created, created=True)
    session = _Session(show=None)
    req = FeedAddShowRequest(
        parsed_name="Fresh.Show", show=ShowCreate(tmdb_id=555, title="Fresh Show")
    )

    out = await _orch(session).add_show_from_feed(_feed(), req)

    assert out.show_created is True
    assert out.show is created
    assert session.added[0].show_id == 77
    assert create_show.await_args.args[2].tmdb_id == 555


async def test_missing_library_show_is_404() -> None:
    with pytest.raises(FeedOnboardingError) as exc_info:
        await _orch(_Session(show=None)).add_show_from_feed(_feed(), _req(show_id=999))

    assert exc_info.value.status_code == 404


# ------------------------------- idempotency -------------------------------


async def test_existing_subscription_on_this_feed_is_returned_unchanged() -> None:
    existing = _sub(id=9, feed_id=7, regex_include="user-edited")
    session = _Session(show=_show(), subs=[existing])

    out = await _orch(session).add_show_from_feed(
        _feed(7), _req(regex_include="would-overwrite", enabled=True)
    )

    assert out.subscription_id == 9
    assert (out.subscription_created, out.adopted_stub) == (False, False)
    assert existing.regex_include == "user-edited"
    assert existing.active is False
    assert session.added == []


async def test_subscription_on_a_different_feed_does_not_block_a_new_one() -> None:
    session = _Session(show=_show(), subs=[_sub(id=3, feed_id=99, regex_include="other")])

    out = await _orch(session).add_show_from_feed(_feed(7), _req())

    assert out.subscription_created is True
    assert session.added[0].feed_id == 7


async def test_unlinked_import_stub_is_adopted_not_duplicated() -> None:
    stub = _sub(id=5, feed_id=None)
    session = _Session(show=_show(), subs=[stub])

    out = await _orch(session).add_show_from_feed(
        _feed(7), _req(regex_include="Brand.New.Show", enabled=True)
    )

    assert (out.subscription_created, out.adopted_stub, out.subscription_id) == (False, True, 5)
    assert stub.feed_id == 7
    assert stub.regex_include == "Brand.New.Show"
    assert stub.active is True and stub.enabled_in_config is True
    assert session.added == []


async def test_adopting_a_stub_never_overwrites_an_existing_filter() -> None:
    stub = _sub(id=5, feed_id=None, regex_include="mine", regex_exclude="mine-ex")
    stub.active = True
    session = _Session(show=_show(), subs=[stub])

    await _orch(session).add_show_from_feed(
        _feed(7), _req(regex_include="theirs", regex_exclude="theirs-ex", enabled=False)
    )

    assert (stub.regex_include, stub.regex_exclude) == ("mine", "mine-ex")
    assert stub.active is True  # not downgraded by enabled=False


# --------------------------------- aliases ---------------------------------


@pytest.mark.parametrize(
    ("parsed", "existing", "expected_added"),
    [
        ("Brand New Show", None, False),  # equals the title
        ("  BRAND new SHOW ", None, False),  # equals the title, ignoring case/space
        ("brand new show (2024)", ["brand new show (2024)"], False),  # already known
        ("Brand.New.Show", None, True),
    ],
)
async def test_alias_is_only_added_when_new(
    parsed: str, existing: list[str] | None, expected_added: bool
) -> None:
    show = _show(aliases=existing)
    session = _Session(show=show)

    out = await _orch(session).add_show_from_feed(_feed(), _req(parsed_name=parsed))

    assert out.alias_added is expected_added
    if expected_added:
        assert "brand.new.show" in show.aliases


# --------------------------------- dry run ---------------------------------


async def test_dry_run_reports_without_writing(create_show) -> None:
    show = _show()
    session = _Session(show=show)

    out = await _orch(session).add_show_from_feed(_feed(), _req(dry_run=True))

    assert out.dry_run is True
    assert (out.show_created, out.subscription_created) == (False, True)
    assert out.alias_added is True
    assert out.subscription_id is None
    assert session.added == []
    session.flush.assert_not_called()
    create_show.assert_not_called()
    assert show.aliases is None  # the alias was only reported, not applied


async def test_dry_run_for_unknown_tmdb_show_says_it_would_create_it(create_show) -> None:
    session = _Session(show=None)
    req = FeedAddShowRequest(
        parsed_name="Fresh.Show", show=ShowCreate(tmdb_id=555, title="Fresh Show"), dry_run=True
    )

    out = await _orch(session).add_show_from_feed(_feed(), req)

    assert (out.show, out.show_created, out.subscription_created) == (None, True, True)
    assert out.alias_added is True
    create_show.assert_not_called()


async def test_dry_run_sees_an_existing_subscription_and_a_stub() -> None:
    existing = _sub(id=9, feed_id=7)
    out = await _orch(_Session(show=_show(), subs=[existing])).add_show_from_feed(
        _feed(7), _req(dry_run=True)
    )
    assert (out.subscription_id, out.subscription_created, out.adopted_stub) == (9, False, False)

    stub = _sub(id=5, feed_id=None)
    out = await _orch(_Session(show=_show(), subs=[stub])).add_show_from_feed(
        _feed(7), _req(dry_run=True)
    )
    assert (out.subscription_id, out.subscription_created, out.adopted_stub) == (5, False, True)
