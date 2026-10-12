"""One structured-output LLM call: prompt -> LLM -> JSON object.

Four services (episode matching, filename parsing, RSS regex suggestion) all
repeated the same first half of a structured call: invoke ``LLMService.complete``,
then decide whether the reply was missing, malformed, or not a JSON object.
:func:`request_json_object` is that shared step. It classifies *why* a call
failed but deliberately never logs or emits events: each caller keeps its own
wording and its own fallback, so the step stays a pure, independently testable
building block that callers compose with their own validation.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from jidou.services.llm_json import parse_llm_json
from jidou.services.llm_service import LLMResponse, LLMService


class JsonCallFailure(StrEnum):
    """Why a structured call produced no usable JSON object."""

    RAISED = "raised"
    NO_RESPONSE = "no_response"
    INVALID_JSON = "invalid_json"
    NOT_OBJECT = "not_object"


@dataclass(frozen=True)
class JsonCallResult:
    """Outcome of :func:`request_json_object`.

    Attributes:
        data: The parsed JSON object, or ``None`` on any failure.
        response: The raw LLM response, when one was received (kept on
            ``INVALID_JSON`` / ``NOT_OBJECT`` so callers can quote the content
            and inspect ``finish_reason``).
        failure: ``None`` on success, otherwise the failure kind.
        error: The exception, when ``failure`` is ``RAISED``.
    """

    data: dict[str, Any] | None
    response: LLMResponse | None
    failure: JsonCallFailure | None
    error: Exception | None = None

    @property
    def content(self) -> str:
        """Raw reply text for failure messages (empty when no reply arrived)."""
        return self.response.content if self.response is not None else ""


async def request_json_object(
    llm: LLMService,
    *,
    prompt: str,
    system: str,
    response_format: dict[str, object],
    max_tokens: int = 1024,
    bypass_cache: bool = False,
) -> JsonCallResult:
    """Call the LLM once and parse the reply as a JSON object.

    Never logs or emits events, so every caller can keep its own messages.

    Args:
        llm: The LLM service to call.
        prompt: User prompt text.
        system: System prompt text.
        response_format: ``response_format`` schema (see
            :func:`~jidou.services.llm_json.json_schema_format`).
        max_tokens: Maximum completion tokens.
        bypass_cache: Skip the LLM response cache for this call.

    Returns:
        A :class:`JsonCallResult`; ``failure`` is ``None`` iff ``data`` is set.
    """
    try:
        response = await llm.complete(
            prompt=prompt,
            system=system,
            response_format=response_format,
            max_tokens=max_tokens,
            bypass_cache=bypass_cache,
        )
    except Exception as exc:
        # complete() already degrades to None; anything that still escapes is
        # surfaced to the caller, which decides whether to swallow or re-raise.
        return JsonCallResult(data=None, response=None, failure=JsonCallFailure.RAISED, error=exc)

    if response is None:
        return JsonCallResult(data=None, response=None, failure=JsonCallFailure.NO_RESPONSE)

    parsed = parse_llm_json(response.content)
    if parsed is None:
        return JsonCallResult(data=None, response=response, failure=JsonCallFailure.INVALID_JSON)
    if not isinstance(parsed, dict):
        return JsonCallResult(data=None, response=response, failure=JsonCallFailure.NOT_OBJECT)
    return JsonCallResult(data=parsed, response=response, failure=None)
