"""Multi-provider LLM service with response caching and graceful degradation.

Supports OpenAI, Anthropic, Ollama, and LM Studio through a single interface.
The active provider is selected via configuration — never hardcoded in business
logic.  All calls degrade gracefully: on failure the method returns ``None``
and logs a warning rather than propagating the exception.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import httpx2 as httpx
from cachetools import TTLCache

if TYPE_CHECKING:
    from jidou.config import Settings

logger = logging.getLogger(__name__)

_ANTHROPIC_VERSION = "2023-06-01"


class LLMProvider(StrEnum):
    """Supported LLM provider identifiers."""

    NONE = "none"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"
    LMSTUDIO = "lmstudio"


# Providers that speak the OpenAI chat-completions API format.
_OPENAI_COMPATIBLE: frozenset[LLMProvider] = frozenset(
    {LLMProvider.OPENAI, LLMProvider.OLLAMA, LLMProvider.LMSTUDIO}
)

# Default base URLs used when the caller does not override.
_DEFAULT_BASE_URLS: dict[LLMProvider, str] = {
    LLMProvider.OPENAI: "https://api.openai.com",
    LLMProvider.ANTHROPIC: "https://api.anthropic.com",
    LLMProvider.OLLAMA: "http://localhost:11434",
    LLMProvider.LMSTUDIO: "http://localhost:1234",
}


@dataclass
class LLMResponse:
    """Structured result of a single LLM completion call."""

    content: str
    model: str
    provider: str
    cached: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_seconds: float = 0.0
    finish_reason: str = ""


class LLMService:
    """Multi-provider LLM service with response caching and graceful degradation.

    Provider selection, model, credentials, and caching are all configured at
    construction time.  The service never blocks application startup — if the
    provider is unreachable the first call will log a warning and return
    ``None``.

    Args:
        provider: LLM provider name (``"openai"``, ``"anthropic"``,
            ``"ollama"``, ``"lmstudio"``, or ``"none"``).
        api_key: API key / bearer token for the provider.
        base_url: Override the provider's default base URL (useful for
            self-hosted instances).
        model: Model identifier (e.g. ``"gpt-4o-mini"``).
        cache_ttl: Response cache TTL in seconds (default 3600).
        timeout: HTTP timeout in seconds for each LLM call (default 30).
    """

    def __init__(
        self,
        provider: str = "none",
        api_key: str = "",
        base_url: str = "",
        model: str = "",
        cache_ttl: int = 3600,
        timeout: float = 30.0,
        no_think: bool = True,
    ) -> None:
        try:
            self._provider = LLMProvider(provider.lower())
        except ValueError:
            logger.warning("Unknown LLM provider %r — falling back to 'none'", provider)
            self._provider = LLMProvider.NONE

        self._no_think = no_think
        self._api_key = api_key
        effective_base = (
            base_url.rstrip("/") if base_url else _DEFAULT_BASE_URLS.get(self._provider, "")
        )
        self._base_url = effective_base
        self._model = model
        self._timeout = timeout
        self._cache: TTLCache[str, str] = TTLCache(maxsize=500, ttl=cache_ttl)
        self._cache_lock = asyncio.Lock()

    def is_available(self) -> bool:
        """Return ``True`` when a real provider and model are configured.

        Returns:
            ``False`` when provider is ``"none"`` or no model is set.
        """
        return self._provider != LLMProvider.NONE and bool(self._model)

    async def test_connection(self) -> tuple[float, str]:
        """Make a minimal provider call and return (latency_seconds, model).

        Unlike :meth:`complete`, this method does **not** suppress exceptions
        so callers receive the real error for diagnostic purposes (auth failures,
        unreachable hosts, bad model names, etc.).

        Returns:
            Tuple of ``(latency_seconds, effective_model)``.

        Raises:
            RuntimeError: If the provider is not configured.
            httpx.HTTPStatusError: On HTTP-level failures (401, 404, etc.).
            Exception: On any other provider-side error.
        """
        if not self.is_available():
            raise RuntimeError("LLM provider is not configured (provider='none' or model unset)")

        # Structured output suppresses reasoning on models that require both
        # /no_think and a schema constraint to skip chain-of-thought.
        _ping_format: dict[str, Any] = {
            "type": "json_schema",
            "json_schema": {
                "name": "ping",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {"result": {"type": "string"}},
                    "required": ["result"],
                    "additionalProperties": False,
                },
            },
        }

        start = time.monotonic()
        if self._provider in _OPENAI_COMPATIBLE:
            await self._call_openai_compatible(
                system=None,
                prompt='/no_think\nReply with {"result": "ok"}',
                model=self._model,
                max_tokens=20,
                response_format=_ping_format,
            )
        elif self._provider == LLMProvider.ANTHROPIC:
            await self._call_anthropic(
                system=None,
                prompt="Reply with the single word: ok",
                model=self._model,
                max_tokens=5,
            )
        else:
            raise RuntimeError(f"Unsupported LLM provider: {self._provider!r}")

        return time.monotonic() - start, self._model

    @staticmethod
    def _make_cache_key(
        provider: str,
        model: str,
        system: str | None,
        prompt: str,
        max_tokens: int,
        response_format: dict[str, Any] | None,
    ) -> str:
        raw = f"{provider}:{model}:{system or ''}:{prompt}:{max_tokens}:{response_format!r}"
        return hashlib.sha256(raw.encode()).hexdigest()

    async def complete(
        self,
        prompt: str,
        system: str | None = None,
        model: str | None = None,
        bypass_cache: bool = False,
        max_tokens: int = 1024,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse | None:
        """Generate a chat completion.

        Args:
            prompt: User-facing prompt text.
            system: Optional system message to prepend.
            model: Override the configured model for this single call.
            bypass_cache: When ``True`` skip cache lookup and always hit the
                provider.
            max_tokens: Maximum tokens the model may generate. Applies to all
                providers. Keeps local models (Ollama, LM Studio) from running
                indefinitely and helps avoid HTTP read timeouts.
            response_format: Optional JSON schema structured output spec
                (OpenAI ``response_format`` shape). Only applied for
                OpenAI-compatible providers; silently ignored for Anthropic.

        Returns:
            :class:`LLMResponse` on success, ``None`` on any failure
            (graceful degradation).
        """
        if not self.is_available():
            logger.debug("LLM provider is 'none' — skipping completion")
            return None

        effective_model = model or self._model
        cache_key = self._make_cache_key(
            self._provider, effective_model, system, prompt, max_tokens, response_format
        )

        if not bypass_cache:
            async with self._cache_lock:
                cached_content = self._cache.get(cache_key)
            if cached_content is not None:
                logger.debug("LLM cache hit (key=%s…)", cache_key[:8])
                return LLMResponse(
                    content=cached_content,
                    model=effective_model,
                    provider=self._provider,
                    cached=True,
                )

        start = time.monotonic()
        try:
            if self._provider in _OPENAI_COMPATIBLE:
                (
                    content,
                    prompt_tokens,
                    completion_tokens,
                    finish_reason,
                ) = await self._call_openai_compatible(
                    system=system,
                    prompt=prompt,
                    model=effective_model,
                    max_tokens=max_tokens,
                    response_format=response_format,
                )
            elif self._provider == LLMProvider.ANTHROPIC:
                (
                    content,
                    prompt_tokens,
                    completion_tokens,
                    finish_reason,
                ) = await self._call_anthropic(
                    system=system,
                    prompt=prompt,
                    model=effective_model,
                    max_tokens=max_tokens,
                )
            else:
                logger.warning("Unsupported LLM provider: %r", self._provider)
                return None
        except Exception as exc:
            logger.warning(
                "LLM call failed (provider=%s model=%s): %s",
                self._provider,
                effective_model,
                exc,
            )
            return None

        elapsed = time.monotonic() - start

        # Strip chain-of-thought blocks that reasoning models (DeepSeek-R1, Qwen3, etc.)
        # emit in content when /no_think is not honoured or thinking is explicitly enabled.
        content = re.sub(
            r"<think(?:ing)?>.*?</think(?:ing)?>", "", content, flags=re.DOTALL
        ).strip()

        if finish_reason == "length":
            logger.warning(
                "LLM response truncated at max_tokens=%d (provider=%s model=%s) — "
                "increase max_tokens or use a model with a larger context window",
                max_tokens,
                self._provider,
                effective_model,
            )
        else:
            # Only cache complete (non-truncated) responses
            async with self._cache_lock:
                self._cache[cache_key] = content

        logger.info(
            "LLM %s/%s: %d+%d tokens in %.2fs (finish_reason=%r)",
            self._provider,
            effective_model,
            prompt_tokens,
            completion_tokens,
            elapsed,
            finish_reason,
        )

        return LLMResponse(
            content=content,
            model=effective_model,
            provider=self._provider,
            cached=False,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_seconds=elapsed,
            finish_reason=finish_reason,
        )

    async def _call_openai_compatible(
        self,
        system: str | None,
        prompt: str,
        model: str,
        max_tokens: int = 8192,
        response_format: dict[str, Any] | None = None,
    ) -> tuple[str, int, int, str]:
        """Call an OpenAI-compatible ``/v1/chat/completions`` endpoint.

        Args:
            system: Optional system message.
            prompt: User message.
            model: Model identifier.
            max_tokens: Maximum tokens the model may generate.
            response_format: Optional JSON schema structured output spec
                (OpenAI ``response_format`` shape).

        Returns:
            Tuple of ``(content, prompt_tokens, completion_tokens, finish_reason)``.

        Raises:
            httpx.HTTPStatusError: On non-2xx responses.
            ValueError: When the provider returns an empty choices list.
        """
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        # /no_think suppresses chain-of-thought on Qwen3 and similar reasoning
        # models that ignore the equivalent system-prompt instruction.
        user_content = f"/no_think\n{prompt}" if self._no_think else prompt
        messages.append({"role": "user", "content": user_content})

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        payload: dict[str, Any] = {"model": model, "messages": messages, "max_tokens": max_tokens}
        if response_format is not None:
            payload["response_format"] = response_format

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/v1/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()

        logger.debug("Raw provider response: %s", json.dumps(data, indent=2, default=str))

        choices: list[dict[str, Any]] = data.get("choices") or []
        if not choices:
            raise ValueError(
                f"Provider returned empty choices list for model={model!r} "
                "(content_filter, token-boundary truncation, or unsupported model)"
            )
        choice = choices[0]
        # Use .get() so a provider that omits content entirely (rather than
        # sending an empty string) doesn't raise KeyError before the fallback.
        content: str = choice["message"].get("content") or ""
        # Qwen3 and some other reasoning models (via LM Studio) emit the answer
        # in reasoning_content and leave content empty when structured output is
        # active.  Fall back to reasoning_content so the caller gets the JSON.
        if not content:
            content = (choice["message"].get("reasoning_content") or "").strip()
        finish_reason: str = choice.get("finish_reason") or ""
        usage: dict[str, int] = data.get("usage", {})
        return (
            content,
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
            finish_reason,
        )

    async def _call_anthropic(
        self,
        system: str | None,
        prompt: str,
        model: str,
        max_tokens: int = 1024,
    ) -> tuple[str, int, int, str]:
        """Call the Anthropic ``/v1/messages`` endpoint.

        Args:
            system: Optional system message (passed as a top-level field).
            prompt: User message.
            model: Anthropic model identifier.
            max_tokens: Maximum tokens the model may generate.

        Returns:
            Tuple of ``(content, input_tokens, output_tokens, finish_reason)``.
            ``finish_reason`` is ``"length"`` when the response was truncated at
            ``max_tokens`` (Anthropic calls this ``"max_tokens"``).

        Raises:
            httpx.HTTPStatusError: On non-2xx responses.
        """
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "x-api-key": self._api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
        }

        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            payload["system"] = system

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/v1/messages",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()

        content = data["content"][0]["text"]
        usage = data.get("usage", {})
        # Anthropic uses "max_tokens" stop_reason; normalise to "length" for consistency
        stop_reason: str = data.get("stop_reason") or ""
        finish_reason = "length" if stop_reason == "max_tokens" else stop_reason
        return content, usage.get("input_tokens", 0), usage.get("output_tokens", 0), finish_reason


def create_llm_service(settings: Settings) -> LLMService:
    """Instantiate :class:`LLMService` from application settings.

    This is the canonical factory used by the FastAPI lifespan, route
    dependencies, and Celery workers.  All six constructor parameters are
    populated so callers do not risk omitting one and silently getting the
    wrong default.

    Args:
        settings: Application settings object exposing ``llm_*`` attributes.

    Returns:
        Configured :class:`LLMService` instance.
    """
    return LLMService(
        provider=settings.llm_provider,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        cache_ttl=settings.llm_cache_ttl,
        timeout=settings.llm_timeout,
        no_think=settings.llm_no_think,
    )
