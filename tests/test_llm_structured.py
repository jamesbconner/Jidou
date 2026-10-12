"""Tests for jidou.services.llm_structured."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from jidou.services.llm_service import LLMProvider, LLMResponse
from jidou.services.llm_structured import JsonCallFailure, JsonCallResult, request_json_object

_FORMAT: dict[str, object] = {"type": "json_schema", "json_schema": {"name": "t"}}


def _llm(*, content: str | None = None, raises: Exception | None = None) -> MagicMock:
    llm = MagicMock()
    if raises is not None:
        llm.complete = AsyncMock(side_effect=raises)
    elif content is None:
        llm.complete = AsyncMock(return_value=None)
    else:
        llm.complete = AsyncMock(
            return_value=LLMResponse(content=content, model="m", provider=LLMProvider.OPENAI)
        )
    return llm


async def _call(llm: MagicMock, **kwargs: object) -> JsonCallResult:
    return await request_json_object(
        llm,
        prompt="p",
        system="s",
        response_format=_FORMAT,
        **kwargs,  # type: ignore[arg-type]
    )


async def test_raised_is_captured_with_the_exception() -> None:
    boom = RuntimeError("boom")

    result = await _call(_llm(raises=boom))

    assert result == JsonCallResult(
        data=None, response=None, failure=JsonCallFailure.RAISED, error=boom
    )
    assert result.error is boom


async def test_no_response() -> None:
    result = await _call(_llm())

    assert result.failure is JsonCallFailure.NO_RESPONSE
    assert result.data is None
    assert result.response is None
    assert result.error is None


async def test_invalid_json_keeps_the_response() -> None:
    result = await _call(_llm(content="nope"))

    assert result.failure is JsonCallFailure.INVALID_JSON
    assert result.data is None
    assert result.response is not None
    assert result.response.content == "nope"


async def test_json_array_is_not_an_object() -> None:
    result = await _call(_llm(content="[1]"))

    assert result.failure is JsonCallFailure.NOT_OBJECT
    assert result.data is None
    assert result.response is not None
    assert result.response.content == "[1]"


async def test_fenced_object_parses() -> None:
    result = await _call(_llm(content='```json\n{"a": 1}\n```'))

    assert result.failure is None
    assert result.data == {"a": 1}
    assert result.response is not None
    assert result.error is None


async def test_arguments_are_passed_through_to_complete() -> None:
    llm = _llm(content="{}")

    await _call(llm, max_tokens=77, bypass_cache=True)

    llm.complete.assert_awaited_once_with(
        prompt="p", system="s", response_format=_FORMAT, max_tokens=77, bypass_cache=True
    )


async def test_defaults_match_llm_service_defaults() -> None:
    llm = _llm(content="{}")

    await _call(llm)

    kwargs = llm.complete.await_args.kwargs
    assert kwargs["max_tokens"] == 1024
    assert kwargs["bypass_cache"] is False


@pytest.mark.parametrize("exc", [KeyboardInterrupt, SystemExit])
async def test_base_exceptions_are_not_swallowed(exc: type[BaseException]) -> None:
    with pytest.raises(exc):
        await _call(_llm(raises=exc()))
