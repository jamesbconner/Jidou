"""Multi-provider LLM service with response caching and graceful degradation.

Supports OpenAI, Anthropic, Ollama, and LM Studio through a single interface.
The active provider is selected via configuration — never hardcoded in business
logic.  All calls degrade gracefully: on failure the method returns ``None``
and logs a warning rather than propagating the exception.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import httpx
from cachetools import TTLCache

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
    ) -> None:
        try:
            self._provider = LLMProvider(provider.lower())
        except ValueError:
            logger.warning("Unknown LLM provider %r — falling back to 'none'", provider)
            self._provider = LLMProvider.NONE

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

    @staticmethod
    def _make_cache_key(provider: str, model: str, system: str | None, prompt: str) -> str:
        raw = f"{provider}:{model}:{system or ''}:{prompt}"
        return hashlib.sha256(raw.encode()).hexdigest()

    async def complete(
        self,
        prompt: str,
        system: str | None = None,
        model: str | None = None,
        bypass_cache: bool = False,
    ) -> LLMResponse | None:
        """Generate a chat completion.

        Args:
            prompt: User-facing prompt text.
            system: Optional system message to prepend.
            model: Override the configured model for this single call.
            bypass_cache: When ``True`` skip cache lookup and always hit the
                provider.

        Returns:
            :class:`LLMResponse` on success, ``None`` on any failure
            (graceful degradation).
        """
        if not self.is_available():
            logger.debug("LLM provider is 'none' — skipping completion")
            return None

        effective_model = model or self._model
        cache_key = self._make_cache_key(self._provider, effective_model, system, prompt)

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
                content, prompt_tokens, completion_tokens = await self._call_openai_compatible(
                    system=system,
                    prompt=prompt,
                    model=effective_model,
                )
            elif self._provider == LLMProvider.ANTHROPIC:
                content, prompt_tokens, completion_tokens = await self._call_anthropic(
                    system=system,
                    prompt=prompt,
                    model=effective_model,
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
        logger.info(
            "LLM %s/%s: %d+%d tokens in %.2fs",
            self._provider,
            effective_model,
            prompt_tokens,
            completion_tokens,
            elapsed,
        )

        async with self._cache_lock:
            self._cache[cache_key] = content

        return LLMResponse(
            content=content,
            model=effective_model,
            provider=self._provider,
            cached=False,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_seconds=elapsed,
        )

    async def _call_openai_compatible(
        self,
        system: str | None,
        prompt: str,
        model: str,
    ) -> tuple[str, int, int]:
        """Call an OpenAI-compatible ``/v1/chat/completions`` endpoint.

        Args:
            system: Optional system message.
            prompt: User message.
            model: Model identifier.

        Returns:
            Tuple of ``(content, prompt_tokens, completion_tokens)``.

        Raises:
            httpx.HTTPStatusError: On non-2xx responses.
        """
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        payload: dict[str, Any] = {"model": model, "messages": messages}

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/v1/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()

        content: str = data["choices"][0]["message"]["content"]
        usage: dict[str, int] = data.get("usage", {})
        return content, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)

    async def _call_anthropic(
        self,
        system: str | None,
        prompt: str,
        model: str,
    ) -> tuple[str, int, int]:
        """Call the Anthropic ``/v1/messages`` endpoint.

        Args:
            system: Optional system message (passed as a top-level field).
            prompt: User message.
            model: Anthropic model identifier.

        Returns:
            Tuple of ``(content, input_tokens, output_tokens)``.

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
            "max_tokens": 1024,
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
        return content, usage.get("input_tokens", 0), usage.get("output_tokens", 0)
