"""Tests for orchestrator domain errors and the single HTTP handler that maps them."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jidou.errors import (
    InvalidRequestError,
    NotFoundError,
    OrchestratorError,
    ServiceUnavailableError,
    UpstreamError,
)
from jidou.main import orchestrator_error_handler


class _UnmappedError(OrchestratorError):
    """Stand-in for a future subclass nobody has added to the status table yet."""


class _SpecificNotFoundError(NotFoundError):
    """A subclass of a mapped error."""


def _client_raising(exc: OrchestratorError) -> TestClient:
    """Mount the production handler on a minimal app whose only route raises *exc*."""
    app = FastAPI()
    app.add_exception_handler(OrchestratorError, orchestrator_error_handler)  # type: ignore[arg-type]

    @app.get("/boom")
    async def boom() -> None:
        raise exc

    return TestClient(app)


@pytest.mark.parametrize(
    ("error_cls", "status_code"),
    [
        (NotFoundError, 404),
        (InvalidRequestError, 422),
        (UpstreamError, 502),
        (ServiceUnavailableError, 503),
    ],
)
def test_each_error_maps_to_its_status_and_http_exception_body(
    error_cls: type[OrchestratorError], status_code: int
) -> None:
    response = _client_raising(error_cls("x")).get("/boom")

    assert response.status_code == status_code
    assert response.json() == {"detail": "x"}


def test_subclass_of_a_mapped_error_inherits_its_status() -> None:
    response = _client_raising(_SpecificNotFoundError("gone")).get("/boom")

    assert (response.status_code, response.json()) == (404, {"detail": "gone"})


def test_unmapped_error_is_a_500_with_its_detail() -> None:
    response = _client_raising(_UnmappedError("oops")).get("/boom")

    assert (response.status_code, response.json()) == (500, {"detail": "oops"})


def test_detail_is_kept_as_attribute_and_exception_message() -> None:
    exc = NotFoundError("Show not found")

    assert exc.detail == "Show not found"
    assert str(exc) == "Show not found"
