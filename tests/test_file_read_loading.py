"""Every route that serializes ``FileRead`` must load ``show`` and ``episode`` explicitly.

``DownloadedFile.show`` / ``DownloadedFile.episode`` are never loaded implicitly
(D25), so a route that forgets the loader options silently returns ``null`` for
a linked file. These tests drive each ``FileRead`` route against a fake session
that models SQLAlchemy's identity-map loading rules and assert the embedded
``show`` / ``episode`` objects come back populated.

The loading model (see :class:`_FakeSession`):

* The first statement that returns the file loads it into the "identity map".
  Its relationships are populated only if that statement carries
  ``selectinload(DownloadedFile.show)`` and ``selectinload(DownloadedFile.episode)``.
* A later statement returning the same (already present) object populates them
  only if it carries both options *and* ``populate_existing=True``; without it
  SQLAlchemy keeps the already-present instance's state as it is.
"""

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from jidou.database import get_session
from jidou.main import app
from jidou.models.downloaded_file import DownloadedFile, FileStatus
from jidou.models.episode import Episode
from jidou.models.show import Show
from jidou.services.synthetic_file import synthetic_remote_path

_SHOW_ID = 7
_EPISODE_ID = 70
_EXPECTED_SHOW = {"id": _SHOW_ID, "title": "Linked Show"}
_EXPECTED_EPISODE = {"id": _EPISODE_ID, "season_number": 1, "episode_number": 2, "name": "Pilot"}


def _linked_file(synthetic_path: str | None = None) -> DownloadedFile:
    """Build a transient file linked (by id) to a show and an episode.

    Args:
        synthetic_path: When given, the file is a synthetic-import row for this
            on-disk path (as ``link-file`` / ``link-movie-file`` create).
    """
    now = datetime.now(UTC)
    return DownloadedFile(
        id=1,
        show_id=_SHOW_ID,
        episode_id=_EPISODE_ID,
        original_filename="Linked Show - S01E02.mkv",
        remote_path=(
            synthetic_remote_path(synthetic_path) if synthetic_path else "/remote/linked.mkv"
        ),
        local_path=synthetic_path or "/library/linked.mkv",
        file_size=1,
        status=FileStatus.UNMATCHED,
        created_at=now,
        updated_at=now,
    )


def _loads_relationships(stmt: Any) -> bool:
    """Return True if *stmt* selectin-loads both ``show`` and ``episode``."""
    loaded: set[str] = set()
    for option in getattr(stmt, "_with_options", ()):
        for element in getattr(option, "context", ()):
            # A selectinload path is (DownloadedFile mapper, relationship, target mapper).
            parts = list(element.path)
            if (
                element.strategy == (("lazy", "selectin"),)
                and len(parts) >= 2
                and getattr(parts[0], "class_", None) is DownloadedFile
            ):
                loaded.add(str(getattr(parts[1], "key", "")))
    return loaded == {"show", "episode"}


class _FakeResult:
    """Minimal stand-in for a SQLAlchemy ``Result``."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None

    def scalar_one(self) -> Any:
        assert len(self._rows) == 1
        return self._rows[0]

    def scalars(self) -> "_FakeResult":
        return self

    def all(self) -> list[Any]:
        return list(self._rows)


@dataclass
class _FakeSession:
    """Async session double that answers ``execute`` from a queue of row lists."""

    file: DownloadedFile
    results: list[list[Any]]
    in_identity_map: bool = False
    flush: AsyncMock = field(default_factory=AsyncMock)
    commit: AsyncMock = field(default_factory=AsyncMock)
    rollback: AsyncMock = field(default_factory=AsyncMock)
    refresh: AsyncMock = field(default_factory=AsyncMock)
    scalar: AsyncMock = field(default_factory=lambda: AsyncMock(return_value=1))

    async def execute(self, stmt: Any) -> _FakeResult:
        rows = self.results.pop(0)
        if self.file in rows:
            self._load(stmt)
        return _FakeResult(rows)

    def _load(self, stmt: Any) -> None:
        populate_existing = bool(stmt.get_execution_options().get("populate_existing"))
        first_load = not self.in_identity_map
        self.in_identity_map = True
        if _loads_relationships(stmt) and (first_load or populate_existing):
            self.file.show = Show(id=_SHOW_ID, title=_EXPECTED_SHOW["title"])
            self.file.episode = Episode(
                id=_EPISODE_ID, season_number=1, episode_number=2, name="Pilot"
            )


def _show(content_type: str = "tv") -> MagicMock:
    show = MagicMock(spec=Show)
    show.id = _SHOW_ID
    show.content_type = content_type
    show.media_type = content_type
    show.local_path = "/library"
    return show


def _episode(*, tracked: bool) -> MagicMock:
    ep = MagicMock(spec=Episode)
    ep.id = _EPISODE_ID
    ep.file_tracked = tracked
    ep.season_number = 1
    ep.episode_number = 2
    return ep


@dataclass(frozen=True)
class _Case:
    """One ``FileRead`` route: how to call it and what its queries return."""

    method: str
    path: str
    url: str
    results: Callable[[DownloadedFile], list[list[Any]]]
    body: Callable[[Path], dict[str, Any] | None] = lambda _tmp: None
    is_list: bool = False
    # The file is the synthetic row already sitting at the request's path.
    synthetic: bool = False
    label: str = ""


_CASES = [
    _Case("GET", "/api/files", "/api/files", lambda f: [[f]], is_list=True),
    _Case("GET", "/api/files/unmatched", "/api/files/unmatched", lambda f: [[f]], is_list=True),
    _Case("GET", "/api/files/{file_id}", "/api/files/1", lambda f: [[f]]),
    _Case(
        "PATCH",
        "/api/files/{file_id}",
        "/api/files/1",
        lambda f: [[f], [f]],
        body=lambda _tmp: {"status": "matched"},
    ),
    _Case("POST", "/api/files/{file_id}/ignore", "/api/files/1/ignore", lambda f: [[f], [f]]),
    _Case(
        "POST",
        "/api/files/{file_id}/match",
        "/api/files/1/match",
        lambda f: [[f], [f]],
        body=lambda _tmp: {"show_id": _SHOW_ID},
    ),
    _Case(
        "POST",
        "/api/shows/{show_id}/episodes/{episode_id}/begin-rematch",
        f"/api/shows/{_SHOW_ID}/episodes/{_EPISODE_ID}/begin-rematch",
        lambda f: [[_show()], [_episode(tracked=True)], [f]],
    ),
    _Case(
        "POST",
        "/api/shows/{show_id}/episodes/{episode_id}/link-file",
        f"/api/shows/{_SHOW_ID}/episodes/{_EPISODE_ID}/link-file",
        lambda f: [[_show()], [_episode(tracked=False)], [f]],
        body=lambda tmp: {"path": str(tmp / "episode.mkv")},
    ),
    _Case(
        "POST",
        "/api/shows/{show_id}/link-movie-file",
        f"/api/shows/{_SHOW_ID}/link-movie-file",
        lambda f: [[_show("movie")], [], [], [f]],
        body=lambda tmp: {"path": str(tmp / "episode.mkv")},
    ),
    # replace=True on the movie's own path: the existing row is unlinked, then
    # re-linked as the orphaned synthetic row, so the final re-select returns an
    # object the session already holds.
    _Case(
        "POST",
        "/api/shows/{show_id}/link-movie-file",
        f"/api/shows/{_SHOW_ID}/link-movie-file",
        lambda f: [[_show("movie")], [f], [f], [f]],
        body=lambda tmp: {"path": str(tmp / "episode.mkv"), "replace": True},
        synthetic=True,
        label="relink",
    ),
]


def _refs(node: Any) -> set[str]:
    """Return every component name ``$ref``-erenced anywhere inside *node*."""
    if isinstance(node, dict):
        found = {str(v).rsplit("/", 1)[-1] for k, v in node.items() if k == "$ref"}
        return found.union(*(_refs(v) for v in node.values()))
    if isinstance(node, list):
        return set().union(*(_refs(v) for v in node))
    return set()


def _file_read_routes() -> set[tuple[str, str]]:
    """Return ``(method, path)`` for every operation whose response contains ``FileRead``.

    Read from the OpenAPI document (not ``app.routes``, which no longer
    flattens included routers) so that a ``FileRead`` embedded in another
    response model, directly or through other components, is found too.
    """
    spec = app.openapi()
    components = spec["components"]["schemas"]
    embedding = {"FileRead"}
    while True:
        grown = embedding | {name for name, s in components.items() if _refs(s) & embedding}
        if grown == embedding:
            break
        embedding = grown
    routes: set[tuple[str, str]] = set()
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            success = {k: v for k, v in operation.get("responses", {}).items() if k[0] == "2"}
            if _refs(success) & embedding:
                routes.add((method.upper(), path))
    return routes


def test_file_read_route_cases_cover_every_file_read_route() -> None:
    """The parametrized cases below cover exactly the app's ``FileRead`` routes."""
    routes = _file_read_routes()
    assert len(routes) >= 9
    assert {(case.method, case.path) for case in _CASES} == routes


@pytest.mark.parametrize(
    "case", _CASES, ids=lambda c: " ".join(filter(None, (c.method, c.path, c.label)))
)
def test_file_read_routes_include_show_and_episode(case: _Case, tmp_path: Path) -> None:
    """A linked file's ``show`` and ``episode`` are populated in every ``FileRead`` response."""
    disk_path = tmp_path / "episode.mkv"
    disk_path.write_bytes(b"")
    file = _linked_file(str(disk_path) if case.synthetic else None)
    session = _FakeSession(file=file, results=case.results(file))

    async def _session() -> AsyncIterator[_FakeSession]:
        yield session

    app.dependency_overrides[get_session] = _session
    try:
        with (
            patch(
                "jidou.api.routes.files.ManualMatchOrchestrator.match",
                AsyncMock(return_value=file),
            ),
            patch("jidou.api.routes.show_episodes.create_synthetic_import_file", AsyncMock()),
            patch("jidou.api.routes.show_local_files.create_synthetic_import_file", AsyncMock()),
        ):
            response = TestClient(app).request(case.method, case.url, json=case.body(tmp_path))
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 200, response.text
    payload = response.json()
    item = payload[0] if case.is_list else payload
    assert item["show"] == _EXPECTED_SHOW
    assert item["episode"] == _EXPECTED_EPISODE
