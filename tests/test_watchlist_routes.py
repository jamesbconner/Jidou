"""Tests for the /watchlist API routes."""

from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from jidou.main import app
from jidou.models.show import Show
from jidou.models.watchlist import WatchlistEntry, WatchlistStatus


def _make_show(*, id: int = 1) -> MagicMock:
    """Build a minimal Show mock."""
    from datetime import UTC, datetime

    s = MagicMock(spec=Show)
    s.id = id
    s.tmdb_id = 100 + id
    s.title = f"Test Show {id}"
    s.media_type = "tv"
    s.overview = None
    s.poster_path = None
    s.backdrop_path = None
    s.vote_average = None
    s.vote_count = 0
    s.release_date = None
    s.original_language = None
    s.cached = False
    s.local_path = None
    s.created_at = datetime.now(UTC)
    s.updated_at = datetime.now(UTC)
    return s


def _make_entry(
    *,
    id: int = 1,
    show_id: int = 1,
    status: str = "planned",
    notes: str | None = None,
    position: int = 0,
) -> MagicMock:
    """Build a minimal WatchlistEntry mock."""
    from datetime import UTC, datetime

    e = MagicMock(spec=WatchlistEntry)
    e.id = id
    e.show_id = show_id
    e.status = status
    e.notes = notes
    e.position = position
    e.created_at = datetime.now(UTC)
    e.updated_at = datetime.now(UTC)
    e.show = _make_show(id=show_id)
    return e


def _make_begin_nested(*, flush_side_effect: object = None) -> MagicMock:
    """Return a mock for session.begin_nested() that works as an async context manager.

    Args:
        flush_side_effect: Optionally override session.flush side_effect inside the savepoint.
    """
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=None)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=ctx)


def _session_override(
    single: MagicMock | None = None,
    many: list[MagicMock] | None = None,
    execute_side_effect: list[MagicMock] | None = None,
) -> "type[AsyncMock]":
    """Build a mock session factory.

    Args:
        single: Value for scalar_one_or_none().
        many: Value for scalars().all().
        execute_side_effect: List of mock results to return on successive execute() calls.
    """

    async def _mock_session() -> AsyncMock:
        session = AsyncMock()
        session.add = MagicMock()  # add() is not awaitable; must not be AsyncMock
        session.flush = AsyncMock()
        session.delete = AsyncMock()
        session.begin_nested = _make_begin_nested()

        if execute_side_effect is not None:
            session.execute = AsyncMock(side_effect=execute_side_effect)
        else:
            result = MagicMock()
            result.scalar_one_or_none.return_value = single
            result.scalars.return_value.all.return_value = many or ([single] if single else [])
            session.execute = AsyncMock(return_value=result)

        yield session

    return _mock_session  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# GET /api/watchlist
# ---------------------------------------------------------------------------


def test_list_watchlist_empty() -> None:
    """GET /api/watchlist returns an empty list when no entries exist."""
    from jidou.database import get_session

    app.dependency_overrides[get_session] = _session_override(many=[])
    try:
        response = TestClient(app).get("/api/watchlist")
        assert response.status_code == 200
        assert response.json() == []
    finally:
        app.dependency_overrides.clear()


def test_list_watchlist_returns_entries() -> None:
    """GET /api/watchlist returns existing watchlist entries."""
    from jidou.database import get_session

    entry = _make_entry()
    app.dependency_overrides[get_session] = _session_override(many=[entry])
    try:
        response = TestClient(app).get("/api/watchlist")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == 1
        assert data[0]["show_id"] == 1
        assert data[0]["status"] == "planned"
    finally:
        app.dependency_overrides.clear()


def test_list_watchlist_filter_by_status() -> None:
    """GET /api/watchlist?status=watching returns only matching entries."""
    from jidou.database import get_session

    entry = _make_entry(status="watching")
    app.dependency_overrides[get_session] = _session_override(many=[entry])
    try:
        response = TestClient(app).get("/api/watchlist?status=watching")
        assert response.status_code == 200
        assert response.json()[0]["status"] == "watching"
    finally:
        app.dependency_overrides.clear()


def test_list_watchlist_invalid_status_returns_400() -> None:
    """GET /api/watchlist?status=<bad> returns 400."""
    from jidou.database import get_session

    app.dependency_overrides[get_session] = _session_override(many=[])
    try:
        response = TestClient(app).get("/api/watchlist?status=invalid_status")
        assert response.status_code == 400
        assert "Invalid status" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_list_watchlist_ordered_by_position() -> None:
    """GET /api/watchlist returns entries ordered by position ascending."""
    from jidou.database import get_session

    entry_a = _make_entry(id=1, position=10)
    entry_b = _make_entry(id=2, position=1)
    entry_c = _make_entry(id=3, position=5)
    # Simulate DB returning already-ordered results
    app.dependency_overrides[get_session] = _session_override(many=[entry_b, entry_c, entry_a])
    try:
        response = TestClient(app).get("/api/watchlist")
        assert response.status_code == 200
        positions = [e["position"] for e in response.json()]
        assert positions == [1, 5, 10]
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /api/watchlist
# ---------------------------------------------------------------------------


def test_create_watchlist_entry() -> None:
    """POST /api/watchlist creates and returns a new entry."""
    from datetime import UTC, datetime

    from jidou.database import get_session

    show = _make_show(id=1)

    show_result = MagicMock()
    show_result.scalar_one_or_none.return_value = show
    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = None

    no_sub_result = MagicMock()
    no_sub_result.scalar_one_or_none.return_value = None  # no existing RSS subscription
    no_unlinked_result = MagicMock()
    no_unlinked_result.scalars.return_value.all.return_value = []

    async def _mock_session() -> AsyncMock:
        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[show_result, existing_result, no_sub_result, no_unlinked_result]
        )

        # Simulate DB populating auto-generated fields on flush
        def _add_with_defaults(obj: object) -> None:
            obj.id = 10  # type: ignore[attr-defined]
            obj.created_at = datetime.now(UTC)  # type: ignore[attr-defined]
            obj.updated_at = datetime.now(UTC)  # type: ignore[attr-defined]

        def _refresh_with_show(obj: object, attrs: list[str] | None = None) -> None:
            if attrs is not None and "show" in attrs:
                obj.show = show  # type: ignore[attr-defined]

        session.add = MagicMock(side_effect=_add_with_defaults)
        session.flush = AsyncMock()
        session.refresh = AsyncMock(side_effect=_refresh_with_show)
        session.begin_nested = _make_begin_nested()
        yield session

    app.dependency_overrides[get_session] = _mock_session
    try:
        response = TestClient(app).post("/api/watchlist", json={"show_id": 1})
        assert response.status_code == 201
        assert response.json()["id"] == 10
        assert response.json()["show_id"] == 1
    finally:
        app.dependency_overrides.clear()


def test_create_watchlist_entry_show_not_found() -> None:
    """POST /api/watchlist returns 404 when the show does not exist."""
    from jidou.database import get_session

    show_result = MagicMock()
    show_result.scalar_one_or_none.return_value = None
    app.dependency_overrides[get_session] = _session_override(execute_side_effect=[show_result])
    try:
        response = TestClient(app).post("/api/watchlist", json={"show_id": 9999})
        assert response.status_code == 404
        assert "Show not found" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_create_watchlist_entry_idempotent() -> None:
    """POST /api/watchlist with an existing show returns the existing entry."""
    from jidou.database import get_session

    show = _make_show(id=1)
    entry = _make_entry(id=5, show_id=1)

    show_result = MagicMock()
    show_result.scalar_one_or_none.return_value = show
    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = entry
    no_sub_result = MagicMock()
    no_sub_result.scalar_one_or_none.return_value = None  # no existing RSS subscription
    no_unlinked_result = MagicMock()
    no_unlinked_result.scalars.return_value.all.return_value = []

    app.dependency_overrides[get_session] = _session_override(
        execute_side_effect=[show_result, existing_result, no_sub_result, no_unlinked_result]
    )
    try:
        response = TestClient(app).post("/api/watchlist", json={"show_id": 1})
        # Route returns 201 status_code regardless (FastAPI response_model status_code)
        # but the entry must be the existing one
        assert response.status_code == 201
        assert response.json()["id"] == 5
    finally:
        app.dependency_overrides.clear()


def test_create_watchlist_entry_creates_rss_stub() -> None:
    """POST /api/watchlist adds an RssSubscription stub when no sub exists for the show."""
    from datetime import UTC, datetime

    from jidou.database import get_session
    from jidou.models.rss import RssSubscription

    show = _make_show(id=1)

    show_result = MagicMock()
    show_result.scalar_one_or_none.return_value = show
    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = None
    no_sub_result = MagicMock()
    no_sub_result.scalar_one_or_none.return_value = None
    no_unlinked_result = MagicMock()
    no_unlinked_result.scalars.return_value.all.return_value = []

    added_objects: list[object] = []

    async def _mock_session() -> AsyncMock:
        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[show_result, existing_result, no_sub_result, no_unlinked_result]
        )

        def _add(obj: object) -> None:
            obj.id = 10  # type: ignore[attr-defined]
            obj.created_at = datetime.now(UTC)  # type: ignore[attr-defined]
            obj.updated_at = datetime.now(UTC)  # type: ignore[attr-defined]
            added_objects.append(obj)

        def _refresh_with_show(obj: object, attrs: list[str] | None = None) -> None:
            if attrs is not None and "show" in attrs:
                obj.show = show  # type: ignore[attr-defined]

        session.add = MagicMock(side_effect=_add)
        session.flush = AsyncMock()
        session.refresh = AsyncMock(side_effect=_refresh_with_show)
        session.begin_nested = _make_begin_nested()
        yield session

    app.dependency_overrides[get_session] = _mock_session
    try:
        response = TestClient(app).post("/api/watchlist", json={"show_id": 1})
        assert response.status_code == 201
        rss_stubs = [o for o in added_objects if isinstance(o, RssSubscription)]
        assert len(rss_stubs) == 1
        assert rss_stubs[0].show_id == 1
        assert rss_stubs[0].name == show.title
        assert rss_stubs[0].enabled_in_config is False
    finally:
        app.dependency_overrides.clear()


def test_create_watchlist_entry_skips_stub_if_sub_exists() -> None:
    """POST /api/watchlist does not create an RSS stub when one already exists for the show."""
    from datetime import UTC, datetime

    from jidou.database import get_session
    from jidou.models.rss import RssSubscription

    show = _make_show(id=1)
    existing_sub = MagicMock(spec=RssSubscription)
    existing_sub.show_id = 1

    show_result = MagicMock()
    show_result.scalar_one_or_none.return_value = show
    no_entry_result = MagicMock()
    no_entry_result.scalar_one_or_none.return_value = None
    sub_exists_result = MagicMock()
    sub_exists_result.scalar_one_or_none.return_value = existing_sub

    added_objects: list[object] = []

    async def _mock_session() -> AsyncMock:
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[show_result, no_entry_result, sub_exists_result])

        def _add(obj: object) -> None:
            obj.id = 10  # type: ignore[attr-defined]
            obj.created_at = datetime.now(UTC)  # type: ignore[attr-defined]
            obj.updated_at = datetime.now(UTC)  # type: ignore[attr-defined]
            added_objects.append(obj)

        def _refresh_with_show(obj: object, attrs: list[str] | None = None) -> None:
            if attrs is not None and "show" in attrs:
                obj.show = show  # type: ignore[attr-defined]

        session.add = MagicMock(side_effect=_add)
        session.flush = AsyncMock()
        session.refresh = AsyncMock(side_effect=_refresh_with_show)
        session.begin_nested = _make_begin_nested()
        yield session

    app.dependency_overrides[get_session] = _mock_session
    try:
        response = TestClient(app).post("/api/watchlist", json={"show_id": 1})
        assert response.status_code == 201
        rss_stubs = [o for o in added_objects if isinstance(o, RssSubscription)]
        assert len(rss_stubs) == 0
    finally:
        app.dependency_overrides.clear()


def test_create_watchlist_entry_idempotent_creates_rss_stub() -> None:
    """POST /api/watchlist on an existing show still creates a stub if no RSS sub exists."""
    from jidou.database import get_session
    from jidou.models.rss import RssSubscription

    show = _make_show(id=1)
    entry = _make_entry(id=5, show_id=1)

    show_result = MagicMock()
    show_result.scalar_one_or_none.return_value = show
    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = entry
    no_sub_result = MagicMock()
    no_sub_result.scalar_one_or_none.return_value = None
    no_unlinked_result = MagicMock()
    no_unlinked_result.scalars.return_value.all.return_value = []

    added_objects: list[object] = []

    async def _mock_session() -> AsyncMock:
        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[show_result, existing_result, no_sub_result, no_unlinked_result]
        )
        session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
        session.flush = AsyncMock()
        session.begin_nested = _make_begin_nested()
        yield session

    app.dependency_overrides[get_session] = _mock_session
    try:
        response = TestClient(app).post("/api/watchlist", json={"show_id": 1})
        assert response.status_code == 201
        rss_stubs = [o for o in added_objects if isinstance(o, RssSubscription)]
        assert len(rss_stubs) == 1
        assert rss_stubs[0].enabled_in_config is False
    finally:
        app.dependency_overrides.clear()


def test_create_watchlist_entry_concurrent_stub_insert_ignored() -> None:
    """POST /api/watchlist tolerates an IntegrityError on the stub insert (TOCTOU race).

    When the savepoint flush raises IntegrityError, the stub must be expunged from
    the session so the final commit does not re-flush it and blow up the transaction.
    """
    from datetime import UTC, datetime

    from sqlalchemy.exc import IntegrityError

    from jidou.database import get_session
    from jidou.models.rss import RssSubscription

    show = _make_show(id=1)

    show_result = MagicMock()
    show_result.scalar_one_or_none.return_value = show
    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = None
    no_sub_result = MagicMock()
    no_sub_result.scalar_one_or_none.return_value = None  # both concurrent requests see no sub
    no_unlinked_result = MagicMock()
    no_unlinked_result.scalars.return_value.all.return_value = []
    concurrent_stub_result = MagicMock()
    concurrent_stub_result.scalar_one.return_value = MagicMock(spec=RssSubscription)

    expunged_objects: list[object] = []

    async def _mock_session() -> AsyncMock:
        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                show_result,
                existing_result,
                no_sub_result,
                no_unlinked_result,
                concurrent_stub_result,
            ]
        )

        def _add(obj: object) -> None:
            obj.id = 10  # type: ignore[attr-defined]
            obj.created_at = datetime.now(UTC)  # type: ignore[attr-defined]
            obj.updated_at = datetime.now(UTC)  # type: ignore[attr-defined]

        def _refresh_with_show(obj: object, attrs: list[str] | None = None) -> None:
            if attrs is not None and "show" in attrs:
                obj.show = show  # type: ignore[attr-defined]

        session.add = MagicMock(side_effect=_add)
        session.expunge = MagicMock(side_effect=expunged_objects.append)
        # Flush #1 succeeds (WatchlistEntry); flush #2 (stub inside savepoint) raises
        session.flush = AsyncMock(
            side_effect=[None, IntegrityError("stmt", {}, Exception("duplicate key"))]
        )
        session.refresh = AsyncMock(side_effect=_refresh_with_show)
        session.begin_nested = _make_begin_nested()
        yield session

    app.dependency_overrides[get_session] = _mock_session
    try:
        response = TestClient(app).post("/api/watchlist", json={"show_id": 1})
        assert response.status_code == 201
        # The stub must have been expunged so commit() won't re-flush it
        rss_expunged = [o for o in expunged_objects if isinstance(o, RssSubscription)]
        assert len(rss_expunged) == 1
    finally:
        app.dependency_overrides.clear()


def test_create_watchlist_entry_links_exact_name_unlinked_sub() -> None:
    """POST /api/watchlist links an unlinked sub by exact name instead of creating a stub."""
    from datetime import UTC, datetime

    from jidou.database import get_session
    from jidou.models.rss import RssSubscription

    show = _make_show(id=1)

    unlinked_sub = MagicMock(spec=RssSubscription)
    unlinked_sub.id = 99
    unlinked_sub.show_id = None
    unlinked_sub.name = show.title  # exact match

    show_result = MagicMock()
    show_result.scalar_one_or_none.return_value = show
    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = None
    no_show_id_result = MagicMock()
    no_show_id_result.scalar_one_or_none.return_value = None
    unlinked_result = MagicMock()
    unlinked_result.scalars.return_value.all.return_value = [unlinked_sub]

    added_objects: list[object] = []

    async def _mock_session() -> AsyncMock:
        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[show_result, existing_result, no_show_id_result, unlinked_result]
        )

        def _add(obj: object) -> None:
            obj.id = 10  # type: ignore[attr-defined]
            obj.created_at = datetime.now(UTC)  # type: ignore[attr-defined]
            obj.updated_at = datetime.now(UTC)  # type: ignore[attr-defined]
            added_objects.append(obj)

        def _refresh_with_show(obj: object, attrs: list[str] | None = None) -> None:
            if attrs is not None and "show" in attrs:
                obj.show = show  # type: ignore[attr-defined]

        session.add = MagicMock(side_effect=_add)
        session.flush = AsyncMock()
        session.refresh = AsyncMock(side_effect=_refresh_with_show)
        session.begin_nested = _make_begin_nested()
        yield session

    app.dependency_overrides[get_session] = _mock_session
    try:
        response = TestClient(app).post("/api/watchlist", json={"show_id": 1})
        assert response.status_code == 201
        rss_stubs = [o for o in added_objects if isinstance(o, RssSubscription)]
        assert len(rss_stubs) == 0  # no new stub created
        assert unlinked_sub.show_id == 1  # existing sub was linked
    finally:
        app.dependency_overrides.clear()


def test_create_watchlist_entry_links_fuzzy_name_unlinked_sub() -> None:
    """POST /api/watchlist links an unlinked sub via fuzzy name match (title prefix mismatch)."""
    from jidou.database import get_session
    from jidou.models.rss import RssSubscription

    show = _make_show(id=7)
    show.title = "Marvel's Daredevil"

    unlinked_sub = MagicMock(spec=RssSubscription)
    unlinked_sub.id = 88
    unlinked_sub.show_id = None
    unlinked_sub.name = "Daredevil"  # fuzzy matches "Marvel's Daredevil"

    show_result = MagicMock()
    show_result.scalar_one_or_none.return_value = show
    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = None
    no_show_id_result = MagicMock()
    no_show_id_result.scalar_one_or_none.return_value = None
    unlinked_result = MagicMock()
    unlinked_result.scalars.return_value.all.return_value = [unlinked_sub]

    added_objects: list[object] = []

    async def _mock_session() -> AsyncMock:
        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[show_result, existing_result, no_show_id_result, unlinked_result]
        )

        def _add(obj: object) -> None:
            from datetime import UTC, datetime

            obj.id = 20  # type: ignore[attr-defined]
            obj.created_at = datetime.now(UTC)  # type: ignore[attr-defined]
            obj.updated_at = datetime.now(UTC)  # type: ignore[attr-defined]
            added_objects.append(obj)

        def _refresh_with_show(obj: object, attrs: list[str] | None = None) -> None:
            if attrs is not None and "show" in attrs:
                obj.show = show  # type: ignore[attr-defined]

        session.add = MagicMock(side_effect=_add)
        session.flush = AsyncMock()
        session.refresh = AsyncMock(side_effect=_refresh_with_show)
        session.begin_nested = _make_begin_nested()
        yield session

    app.dependency_overrides[get_session] = _mock_session
    try:
        response = TestClient(app).post("/api/watchlist", json={"show_id": 7})
        assert response.status_code == 201
        rss_stubs = [o for o in added_objects if isinstance(o, RssSubscription)]
        assert len(rss_stubs) == 0  # no new stub — fuzzy match linked the existing sub
        assert unlinked_sub.show_id == 7
    finally:
        app.dependency_overrides.clear()


def test_create_watchlist_entry_skips_link_when_fuzzy_ambiguous() -> None:
    """POST /api/watchlist creates a stub when multiple unlinked subs tie on fuzzy score."""
    from datetime import UTC, datetime

    from jidou.database import get_session
    from jidou.models.rss import RssSubscription

    show = _make_show(id=7)
    show.title = "Daredevil"

    # Both subs score 100 on token_set_ratio vs "Daredevil"
    sub_a = MagicMock(spec=RssSubscription)
    sub_a.id = 10
    sub_a.show_id = None
    sub_a.name = "Marvel's Daredevil"

    sub_b = MagicMock(spec=RssSubscription)
    sub_b.id = 11
    sub_b.show_id = None
    sub_b.name = "Daredevil Born Again"  # no colon — scores 100, not 60

    show_result = MagicMock()
    show_result.scalar_one_or_none.return_value = show
    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = None
    no_show_id_result = MagicMock()
    no_show_id_result.scalar_one_or_none.return_value = None
    unlinked_result = MagicMock()
    unlinked_result.scalars.return_value.all.return_value = [sub_a, sub_b]

    added_objects: list[object] = []

    async def _mock_session() -> AsyncMock:
        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[show_result, existing_result, no_show_id_result, unlinked_result]
        )

        def _add(obj: object) -> None:
            obj.id = 20  # type: ignore[attr-defined]
            obj.created_at = datetime.now(UTC)  # type: ignore[attr-defined]
            obj.updated_at = datetime.now(UTC)  # type: ignore[attr-defined]
            added_objects.append(obj)

        def _refresh_with_show(obj: object, attrs: list[str] | None = None) -> None:
            if attrs is not None and "show" in attrs:
                obj.show = show  # type: ignore[attr-defined]

        session.add = MagicMock(side_effect=_add)
        session.flush = AsyncMock()
        session.refresh = AsyncMock(side_effect=_refresh_with_show)
        session.begin_nested = _make_begin_nested()
        yield session

    app.dependency_overrides[get_session] = _mock_session
    try:
        response = TestClient(app).post("/api/watchlist", json={"show_id": 7})
        assert response.status_code == 201
        # Ambiguous — neither sub linked; a new stub is created instead
        rss_stubs = [o for o in added_objects if isinstance(o, RssSubscription)]
        assert len(rss_stubs) == 1
        assert sub_a.show_id is None
        assert sub_b.show_id is None
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /api/watchlist/{entry_id}
# ---------------------------------------------------------------------------


def test_get_watchlist_entry() -> None:
    """GET /api/watchlist/{id} returns the correct entry."""
    from jidou.database import get_session

    entry = _make_entry(id=7, show_id=3, status="watching")
    app.dependency_overrides[get_session] = _session_override(single=entry)
    try:
        response = TestClient(app).get("/api/watchlist/7")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 7
        assert data["show_id"] == 3
        assert data["status"] == "watching"
    finally:
        app.dependency_overrides.clear()


def test_get_watchlist_entry_not_found() -> None:
    """GET /api/watchlist/{id} returns 404 when the entry does not exist."""
    from jidou.database import get_session

    app.dependency_overrides[get_session] = _session_override(single=None)
    try:
        response = TestClient(app).get("/api/watchlist/9999")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# PATCH /api/watchlist/{entry_id}
# ---------------------------------------------------------------------------


def test_patch_watchlist_entry_status() -> None:
    """PATCH /api/watchlist/{id} updates the status field."""
    from jidou.database import get_session

    entry = _make_entry(id=1, status="planned")
    app.dependency_overrides[get_session] = _session_override(single=entry)
    try:
        response = TestClient(app).patch("/api/watchlist/1", json={"status": "watching"})
        assert response.status_code == 200
        assert entry.status == WatchlistStatus.WATCHING
    finally:
        app.dependency_overrides.clear()


def test_patch_watchlist_entry_invalid_status() -> None:
    """PATCH /api/watchlist/{id} with a bad status returns 422 (Pydantic pattern validation)."""
    from jidou.database import get_session

    entry = _make_entry(id=1)
    app.dependency_overrides[get_session] = _session_override(single=entry)
    try:
        response = TestClient(app).patch("/api/watchlist/1", json={"status": "not_a_status"})
        # Pydantic's pattern constraint on WatchlistUpdate.status rejects bad values
        # before the route handler runs, returning 422 Unprocessable Entity.
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_patch_watchlist_entry_notes_only() -> None:
    """PATCH /api/watchlist/{id} with only notes leaves status unchanged."""
    from jidou.database import get_session

    entry = _make_entry(id=1, status="planned", notes=None)
    original_status = entry.status
    app.dependency_overrides[get_session] = _session_override(single=entry)
    try:
        response = TestClient(app).patch("/api/watchlist/1", json={"notes": "great show"})
        assert response.status_code == 200
        assert entry.status == original_status
        assert entry.notes == "great show"
    finally:
        app.dependency_overrides.clear()


def test_patch_watchlist_entry_not_found() -> None:
    """PATCH /api/watchlist/{id} returns 404 for an unknown entry."""
    from jidou.database import get_session

    app.dependency_overrides[get_session] = _session_override(single=None)
    try:
        response = TestClient(app).patch("/api/watchlist/9999", json={"status": "watching"})
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /api/watchlist/reorder
# ---------------------------------------------------------------------------


def test_reorder_watchlist_updates_positions() -> None:
    """POST /api/watchlist/reorder updates positions for all provided entries."""
    from jidou.database import get_session

    entry_a = _make_entry(id=1, position=1)
    entry_b = _make_entry(id=2, position=2)

    result = MagicMock()
    result.scalars.return_value.all.return_value = [entry_a, entry_b]

    async def _mock_session() -> AsyncMock:
        session = AsyncMock()
        session.execute = AsyncMock(return_value=result)
        session.flush = AsyncMock()
        yield session

    app.dependency_overrides[get_session] = _mock_session
    try:
        response = TestClient(app).post(
            "/api/watchlist/reorder",
            json=[{"id": 1, "position": 2}, {"id": 2, "position": 1}],
        )
        assert response.status_code == 204
        assert entry_a.position == 2
        assert entry_b.position == 1
    finally:
        app.dependency_overrides.clear()


def test_reorder_watchlist_empty_payload() -> None:
    """POST /api/watchlist/reorder with empty list returns 204 immediately."""
    from jidou.database import get_session

    app.dependency_overrides[get_session] = _session_override(many=[])
    try:
        response = TestClient(app).post("/api/watchlist/reorder", json=[])
        assert response.status_code == 204
    finally:
        app.dependency_overrides.clear()


def test_reorder_watchlist_missing_entry_returns_404() -> None:
    """POST /api/watchlist/reorder returns 404 when an entry ID does not exist."""
    from jidou.database import get_session

    entry_a = _make_entry(id=1, position=1)
    result = MagicMock()
    result.scalars.return_value.all.return_value = [entry_a]

    async def _mock_session() -> AsyncMock:
        session = AsyncMock()
        session.execute = AsyncMock(return_value=result)
        session.flush = AsyncMock()
        yield session

    app.dependency_overrides[get_session] = _mock_session
    try:
        response = TestClient(app).post(
            "/api/watchlist/reorder",
            json=[{"id": 1, "position": 2}, {"id": 9999, "position": 1}],
        )
        assert response.status_code == 404
        assert "9999" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# DELETE /api/watchlist/{entry_id}
# ---------------------------------------------------------------------------


def test_delete_watchlist_entry() -> None:
    """DELETE /api/watchlist/{id} returns 204 and removes the entry."""
    from jidou.database import get_session

    entry = _make_entry(id=1)
    app.dependency_overrides[get_session] = _session_override(single=entry)
    try:
        response = TestClient(app).delete("/api/watchlist/1")
        assert response.status_code == 204
    finally:
        app.dependency_overrides.clear()


def test_delete_watchlist_entry_not_found() -> None:
    """DELETE /api/watchlist/{id} returns 404 when the entry does not exist."""
    from jidou.database import get_session

    app.dependency_overrides[get_session] = _session_override(single=None)
    try:
        response = TestClient(app).delete("/api/watchlist/9999")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
