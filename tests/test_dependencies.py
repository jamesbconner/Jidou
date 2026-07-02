"""Tests for shared FastAPI dependencies."""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from jidou.api.dependencies import verify_api_key


def _make_app() -> FastAPI:
    app = FastAPI()

    @app.get("/protected", dependencies=[])
    async def _protected() -> dict[str, str]:
        return {"ok": "true"}

    app.dependency_overrides = {}
    # Wire the real dependency so tests exercise it end-to-end.
    from fastapi import Depends

    @app.get("/guarded")
    async def _guarded(_: None = Depends(verify_api_key)) -> dict[str, str]:
        return {"ok": "true"}

    return app


@pytest.fixture()
def app() -> FastAPI:
    return _make_app()


@pytest.fixture()
async def client(app: FastAPI) -> AsyncClient:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


class TestVerifyApiKey:
    async def test_passes_when_key_not_configured(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("jidou.api.dependencies.settings.jidou_api_key", None)
        res = await client.get("/guarded")
        assert res.status_code == 200

    async def test_passes_with_correct_key(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("jidou.api.dependencies.settings.jidou_api_key", "secret")
        res = await client.get("/guarded", headers={"X-API-Key": "secret"})
        assert res.status_code == 200

    async def test_rejects_wrong_key(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("jidou.api.dependencies.settings.jidou_api_key", "secret")
        res = await client.get("/guarded", headers={"X-API-Key": "wrong"})
        assert res.status_code == 401

    async def test_rejects_missing_header(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("jidou.api.dependencies.settings.jidou_api_key", "secret")
        res = await client.get("/guarded")
        assert res.status_code == 401

    async def test_empty_configured_key_disables_auth(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("jidou.api.dependencies.settings.jidou_api_key", "")
        res = await client.get("/guarded")
        assert res.status_code == 200
