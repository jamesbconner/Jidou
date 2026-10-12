"""Tests for the typed TMDB sub-objects (``genres``, ``networks``, episode refs).

These four fields are stored as raw TMDB JSON (JSONB columns) and used to be
typed as bare ``dict[str, object]`` in every response schema. DF-17 types them
with ``extra="allow"`` sub-models. The tests below pin two things:

* **Byte identity (characterization).** Every stored shape -- ``None``,
  ``[]``, ``{}``, a full TMDB object, an object missing a declared field, and
  an object carrying an unknown future TMDB key -- serializes to exactly the
  bytes the old ``dict[str, object]`` field produced. In particular no
  ``"id": null`` style keys are added and key order is kept. These pass on
  both the old and the new code.
* **Typing (new behaviour).** The response schemas validate the fields into
  ``TmdbGenre`` / ``TmdbNetwork`` / ``TmdbEpisodeRef`` and the OpenAPI document
  references those components.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, TypeAdapter

from jidou.main import app
from jidou.models.show import Show
from jidou.schemas.calendar_schema import CalendarEpisode
from jidou.schemas.dashboard_schema import DashboardShowSummary, RecentShowItem
from jidou.schemas.show_schema import ShowList, ShowRead

_NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)

# How the fields serialized before DF-17: the bare field annotations the
# schemas used, run through pydantic's own serializer.
_LEGACY_LIST = TypeAdapter(list[dict[str, object]] | None)
_LEGACY_OBJECT = TypeAdapter(dict[str, object] | None)

# --- Representative stored values -------------------------------------------
# Genre / network objects as TMDB returns them and as Postgres JSONB hands them
# back (JSONB orders keys by length, then bytewise: id, name, logo_path, ...).
_GENRE_VALUES: list[list[dict[str, object]] | None] = [
    None,
    [],
    [{"id": 16, "name": "Animation"}],
    [{"id": 16, "name": "Animation"}, {"id": 10765, "name": "Sci-Fi & Fantasy"}],
    # Missing a declared field (ShowCreate accepts arbitrary dicts, e.g. the
    # genre_ids-only shape used by infer_content_type tests).
    [{"id": 16}],
    [{"name": "Drama"}],
    [{}],
    # Non-canonical key order must survive.
    [{"name": "Animation", "id": 16}],
    # An unknown, future TMDB key must pass through untouched.
    [{"id": 16, "name": "Animation", "tmdb_future_key": {"nested": [1, None, "x"]}}],
]

_NETWORK_VALUES: list[list[dict[str, object]] | None] = [
    None,
    [],
    [
        {
            "id": 49,
            "name": "HBO",
            "logo_path": "/tuomPhY2UtuPTqqFnKMVHvSb724.png",
            "origin_country": "US",
        }
    ],
    [{"id": 1, "name": "Fuji TV", "logo_path": None, "origin_country": ""}],
    # Shape used by the DB-import round-trip fixture: no logo_path/origin_country.
    [{"id": 5, "name": "HBO"}],
    [{}],
    [{"id": 49, "name": "HBO", "logo_path": None, "origin_country": "US", "brand_new": True}],
]

_FULL_EPISODE_REF: dict[str, object] = {
    "id": 4_870_000,
    "name": "The Finale",
    "overview": "Everything ends. — 日本",
    "vote_average": 7.5,
    "vote_count": 2,
    "air_date": "2024-03-28",
    "episode_number": 12,
    "episode_type": "finale",
    "production_code": "",
    "runtime": 24,
    "season_number": 1,
    "show_id": 100,
    "still_path": None,
}

_EPISODE_REF_VALUES: list[dict[str, object] | None] = [
    None,
    {},
    _FULL_EPISODE_REF,
    # Same object, different key order (e.g. a raw TMDB payload, not JSONB).
    dict(reversed(list(_FULL_EPISODE_REF.items()))),
    # Partial shapes seen in existing fixtures.
    {"id": 1},
    {"id": 1, "episode_number": 12},
    {"air_date": "2030-01-01"},
    {"id": 2, "air_date": None, "runtime": None, "tmdb_future_key": [1, 2]},
]

# --- Minimal valid payloads per response schema -----------------------------
_BASES: dict[type[BaseModel], dict[str, Any]] = {
    ShowRead: {
        "id": 1,
        "tmdb_id": 100,
        "title": "Show",
        "media_type": "tv",
        "vote_count": 0,
        "cached": False,
        "created_at": _NOW,
        "updated_at": _NOW,
    },
    ShowList: {"id": 1, "tmdb_id": 100, "title": "Show", "media_type": "tv", "created_at": _NOW},
    CalendarEpisode: {
        "episode_id": 1,
        "show_id": 1,
        "show_title": "Show",
        "poster_path": None,
        "season_number": 1,
        "episode_number": 1,
        "name": "Ep",
        "air_date": date(2026, 1, 1),
        "status": "tracked",
        "track_missing_episodes": True,
        "has_active_rss_subscription": False,
    },
    RecentShowItem: {
        "id": 1,
        "tmdb_id": 100,
        "title": "Show",
        "media_type": "tv",
        "created_at": _NOW,
    },
    DashboardShowSummary: {"id": 1, "title": "Show", "media_type": "tv"},
}

# Every (schema, field) pair that carries one of the four TMDB sub-objects.
_LIST_FIELDS: list[tuple[type[BaseModel], str, list[list[dict[str, object]] | None]]] = [
    (ShowRead, "genres", _GENRE_VALUES),
    (ShowList, "genres", _GENRE_VALUES),
    (CalendarEpisode, "genres", _GENRE_VALUES),
    (RecentShowItem, "genres", _GENRE_VALUES),
    (DashboardShowSummary, "genres", _GENRE_VALUES),
    (ShowRead, "networks", _NETWORK_VALUES),
    (ShowList, "networks", _NETWORK_VALUES),
]
_OBJECT_FIELDS: list[tuple[type[BaseModel], str]] = [
    (ShowRead, "last_episode_to_air"),
    (ShowRead, "next_episode_to_air"),
    (ShowList, "last_episode_to_air"),
    (ShowList, "next_episode_to_air"),
]

_LIST_CASES = [
    pytest.param(schema, field, value, id=f"{schema.__name__}.{field}[{i}]")
    for schema, field, values in _LIST_FIELDS
    for i, value in enumerate(values)
]
_OBJECT_CASES = [
    pytest.param(schema, field, value, id=f"{schema.__name__}.{field}[{i}]")
    for schema, field in _OBJECT_FIELDS
    for i, value in enumerate(_EPISODE_REF_VALUES)
]


def _field_bytes(schema: type[BaseModel], field: str, value: object) -> bytes:
    """Serialize *value* through *schema*'s *field* and return that field's JSON."""
    model = schema.model_validate({**_BASES[schema], field: value})
    return model.model_dump_json(include={field}).encode()


def test_case_tables_are_populated() -> None:
    """Guard against the parametrized byte-identity tests silently running zero cases."""
    assert len(_LIST_CASES) >= 50
    assert len(_OBJECT_CASES) >= 30


@pytest.mark.parametrize(("schema", "field", "value"), _LIST_CASES)
def test_list_field_json_is_byte_identical_to_legacy_dict(
    schema: type[BaseModel], field: str, value: list[dict[str, object]] | None
) -> None:
    """``genres`` / ``networks`` serialize to the exact bytes the old dict field produced."""
    expected = b'{"' + field.encode() + b'":' + _LEGACY_LIST.dump_json(value) + b"}"
    assert _field_bytes(schema, field, value) == expected


@pytest.mark.parametrize(("schema", "field", "value"), _OBJECT_CASES)
def test_episode_ref_json_is_byte_identical_to_legacy_dict(
    schema: type[BaseModel], field: str, value: dict[str, object] | None
) -> None:
    """``last_episode_to_air`` / ``next_episode_to_air`` serialize byte-identically."""
    expected = b'{"' + field.encode() + b'":' + _LEGACY_OBJECT.dump_json(value) + b"}"
    assert _field_bytes(schema, field, value) == expected


def test_missing_declared_field_adds_no_null_key() -> None:
    """A sub-object missing a declared field must not gain ``"name": null`` etc."""
    body = _field_bytes(ShowRead, "genres", [{"id": 16}])
    assert body == b'{"genres":[{"id":16}]}'
    body = _field_bytes(ShowRead, "next_episode_to_air", {})
    assert body == b'{"next_episode_to_air":{}}'


# --- New behaviour: the fields are typed -------------------------------------


def test_response_schemas_type_the_tmdb_subobjects() -> None:
    """The four fields validate into the typed sub-models, keeping unknown keys."""
    from jidou.schemas._base import TmdbEpisodeRef, TmdbGenre, TmdbNetwork

    show = ShowRead.model_validate(
        {
            **_BASES[ShowRead],
            "genres": [{"id": 16, "name": "Animation", "tmdb_future_key": "kept"}],
            "networks": [{"id": 49, "name": "HBO", "logo_path": None, "origin_country": "US"}],
            "last_episode_to_air": _FULL_EPISODE_REF,
            "next_episode_to_air": {"id": 2, "air_date": "2030-01-01", "brand_new": 1},
        }
    )

    assert show.genres is not None
    assert isinstance(show.genres[0], TmdbGenre)
    assert show.genres[0].id == 16
    assert show.genres[0].name == "Animation"
    assert show.genres[0].model_extra == {"tmdb_future_key": "kept"}
    assert show.networks is not None
    assert isinstance(show.networks[0], TmdbNetwork)
    assert show.networks[0].origin_country == "US"
    assert isinstance(show.last_episode_to_air, TmdbEpisodeRef)
    assert show.last_episode_to_air.episode_number == 12
    assert isinstance(show.next_episode_to_air, TmdbEpisodeRef)
    assert show.next_episode_to_air.air_date == "2030-01-01"
    assert show.next_episode_to_air.model_extra == {"brand_new": 1}


def test_openapi_references_typed_tmdb_components() -> None:
    """The OpenAPI document exposes the sub-models and every carrying schema refs them."""
    schemas = app.openapi()["components"]["schemas"]

    for name, declared in (
        ("TmdbGenre", {"id", "name"}),
        ("TmdbNetwork", {"id", "name", "logo_path", "origin_country"}),
        ("TmdbEpisodeRef", {"id", "name", "air_date", "season_number", "episode_number"}),
    ):
        assert name in schemas, f"{name} missing from OpenAPI components"
        component = schemas[name]
        assert component.get("additionalProperties") is True
        assert declared <= set(component["properties"])
        # Nothing is required: stored TMDB objects may lack any key.
        assert "required" not in component

    def refs(schema: str, field: str) -> str:
        return str(schemas[schema]["properties"][field])

    carriers = [
        ("ShowRead", "genres", "TmdbGenre"),
        ("ShowList", "genres", "TmdbGenre"),
        ("CalendarEpisode", "genres", "TmdbGenre"),
        ("RecentShowItem", "genres", "TmdbGenre"),
        ("DashboardShowSummary", "genres", "TmdbGenre"),
        ("ShowRead", "networks", "TmdbNetwork"),
        ("ShowList", "networks", "TmdbNetwork"),
        ("ShowRead", "last_episode_to_air", "TmdbEpisodeRef"),
        ("ShowRead", "next_episode_to_air", "TmdbEpisodeRef"),
        ("ShowList", "last_episode_to_air", "TmdbEpisodeRef"),
        ("ShowList", "next_episode_to_air", "TmdbEpisodeRef"),
    ]
    for schema, field, component_name in carriers:
        assert f"#/components/schemas/{component_name}" in refs(schema, field), (schema, field)


# --- End to end through the real route serializer ----------------------------


def _show_row(**tmdb_fields: object) -> MagicMock:
    """Build a Show row mock with every ShowRead/ShowList column populated."""
    s = MagicMock(spec=Show)
    for column in Show.__table__.columns:
        setattr(s, column.key, None)
    s.id = 1
    s.tmdb_id = 100
    s.title = "Show"
    s.media_type = "tv"
    s.vote_count = 0
    s.cached = False
    s.track_missing_episodes = True
    s.created_at = _NOW
    s.updated_at = _NOW
    for key, value in tmdb_fields.items():
        setattr(s, key, value)
    return s


def _session_returning(show: MagicMock) -> Callable[[], Any]:
    """Dependency override yielding a session whose queries return *show*."""

    async def _mock_session() -> Any:
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = show
        result.all.return_value = [(show, 0, 0, 0, 0, 0, 0, 0, 0, 0, False, None)]
        session.execute = AsyncMock(return_value=result)
        yield session

    return _mock_session


_ROUTE_FIELDS: dict[str, object] = {
    "genres": [{"name": "Animation", "id": 16, "tmdb_future_key": {"a": [1, None]}}, {"id": 18}],
    "networks": [{"id": 5, "name": "HBO"}, {}],
    "last_episode_to_air": dict(reversed(list(_FULL_EPISODE_REF.items()))),
    "next_episode_to_air": {},
}


def _legacy_json(value: object) -> str:
    """Return *value* serialized the way the old ``dict[str, object]`` fields did."""
    adapter: TypeAdapter[Any] = _LEGACY_LIST if isinstance(value, list) else _LEGACY_OBJECT
    return adapter.dump_json(value).decode()


@pytest.mark.parametrize("path", ["/api/shows/1", "/api/shows"])
def test_routes_return_stored_tmdb_objects_unchanged(path: str) -> None:
    """GET /shows and GET /shows/{id} echo the stored objects verbatim, key order included."""
    from jidou.database import get_session

    app.dependency_overrides[get_session] = _session_returning(_show_row(**_ROUTE_FIELDS))
    try:
        response = TestClient(app).get(path)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    body = response.json()
    record = body[0] if isinstance(body, list) else body
    assert len(_ROUTE_FIELDS) == 4
    for field, stored in _ROUTE_FIELDS.items():
        assert record[field] == stored
        # Byte level: the stored value's compact JSON appears verbatim.
        assert _legacy_json(stored) in response.text
    episode_keys = list(_FULL_EPISODE_REF)[::-1]
    assert list(record["last_episode_to_air"]) == episode_keys
