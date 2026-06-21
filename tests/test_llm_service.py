"""Tests for the LLM service (multi-provider with caching and graceful degradation)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jidou.services.llm_service import LLMProvider, LLMService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def openai_service() -> LLMService:
    return LLMService(
        provider="openai",
        api_key="sk-test",
        base_url="https://api.openai.com",
        model="gpt-4o-mini",
    )


@pytest.fixture
def lmstudio_service() -> LLMService:
    return LLMService(
        provider="lmstudio",
        api_key="",
        base_url="http://localhost:1234",
        model="qwen2.5-7b-instruct",
    )


@pytest.fixture
def anthropic_service() -> LLMService:
    return LLMService(
        provider="anthropic",
        api_key="sk-ant-test",
        base_url="https://api.anthropic.com",
        model="claude-haiku-20240307",
    )


@pytest.fixture
def no_provider_service() -> LLMService:
    return LLMService(provider="none")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _openai_response(content: str, prompt: int = 10, completion: int = 20) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
    }
    return resp


def _anthropic_response(content: str, input_tokens: int = 5, output_tokens: int = 15) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "content": [{"text": content}],
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }
    return resp


def _mock_http_client(response: MagicMock) -> AsyncMock:
    """Return an AsyncMock suitable for use as an httpx.AsyncClient context manager."""
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.__aexit__.return_value = False
    client.post.return_value = response
    return client


# ---------------------------------------------------------------------------
# Provider availability
# ---------------------------------------------------------------------------


class TestLLMServiceAvailability:
    def test_none_provider_not_available(self, no_provider_service: LLMService) -> None:
        assert no_provider_service.is_available() is False

    def test_configured_provider_is_available(self, openai_service: LLMService) -> None:
        assert openai_service.is_available() is True

    def test_missing_model_not_available(self) -> None:
        svc = LLMService(provider="openai", api_key="k")  # no model
        assert svc.is_available() is False

    def test_unknown_provider_falls_back_to_none(self) -> None:
        svc = LLMService(provider="mystery_llm", model="some-model")
        assert svc._provider == LLMProvider.NONE
        assert svc.is_available() is False


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    @pytest.mark.asyncio
    async def test_none_provider_returns_none(self, no_provider_service: LLMService) -> None:
        """complete() on a 'none' provider must return None without raising."""
        result = await no_provider_service.complete("hello")
        assert result is None

    @pytest.mark.asyncio
    async def test_http_error_returns_none(self, openai_service: LLMService) -> None:
        """An HTTP error must be swallowed and return None."""
        client = _mock_http_client(MagicMock())
        client.post.side_effect = Exception("connection refused")

        with patch("httpx.AsyncClient", return_value=client):
            result = await openai_service.complete("test")

        assert result is None

    @pytest.mark.asyncio
    async def test_http_error_logs_warning(
        self, openai_service: LLMService, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An LLM failure must be logged at WARNING level."""
        import logging

        client = _mock_http_client(MagicMock())
        client.post.side_effect = ConnectionError("broker down")

        with (
            patch("httpx.AsyncClient", return_value=client),
            caplog.at_level(logging.WARNING, logger="jidou.services.llm_service"),
        ):
            await openai_service.complete("test")

        assert any("LLM call failed" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# OpenAI-compatible providers
# ---------------------------------------------------------------------------


class TestOpenAICompatible:
    @pytest.mark.asyncio
    async def test_complete_returns_llm_response(self, openai_service: LLMService) -> None:
        """complete() returns a populated LLMResponse on success."""
        client = _mock_http_client(_openai_response("The answer is 42"))

        with patch("httpx.AsyncClient", return_value=client):
            result = await openai_service.complete("What is 6x7?")

        assert result is not None
        assert result.content == "The answer is 42"
        assert result.provider == LLMProvider.OPENAI
        assert result.cached is False
        assert result.prompt_tokens == 10
        assert result.completion_tokens == 20

    @pytest.mark.asyncio
    async def test_system_message_included_in_payload(self, openai_service: LLMService) -> None:
        """System message is sent as the first message with role='system'."""
        client = _mock_http_client(_openai_response("ok"))

        with patch("httpx.AsyncClient", return_value=client):
            await openai_service.complete("hello", system="Be concise.")

        payload = client.post.call_args.kwargs["json"]
        assert payload["messages"][0] == {"role": "system", "content": "Be concise."}
        assert payload["messages"][1]["role"] == "user"

    @pytest.mark.asyncio
    async def test_uses_correct_endpoint(self, openai_service: LLMService) -> None:
        """Request is sent to /v1/chat/completions."""
        client = _mock_http_client(_openai_response("ok"))

        with patch("httpx.AsyncClient", return_value=client):
            await openai_service.complete("test")

        url = client.post.call_args.args[0]
        assert url.endswith("/v1/chat/completions")

    @pytest.mark.asyncio
    async def test_lmstudio_uses_openai_compatible_endpoint(
        self, lmstudio_service: LLMService
    ) -> None:
        """LM Studio (OpenAI-compatible) also uses /v1/chat/completions."""
        client = _mock_http_client(_openai_response("response"))

        with patch("httpx.AsyncClient", return_value=client):
            await lmstudio_service.complete("test")

        url = client.post.call_args.args[0]
        assert "/v1/chat/completions" in url
        assert "localhost:1234" in url

    @pytest.mark.asyncio
    async def test_authorization_header_sent_when_api_key_set(
        self, openai_service: LLMService
    ) -> None:
        """Bearer token is included in Authorization header."""
        client = _mock_http_client(_openai_response("ok"))

        with patch("httpx.AsyncClient", return_value=client):
            await openai_service.complete("test")

        headers = client.post.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer sk-test"

    @pytest.mark.asyncio
    async def test_no_auth_header_when_api_key_empty(self, lmstudio_service: LLMService) -> None:
        """No Authorization header when api_key is empty (local models)."""
        client = _mock_http_client(_openai_response("ok"))

        with patch("httpx.AsyncClient", return_value=client):
            await lmstudio_service.complete("test")

        headers = client.post.call_args.kwargs["headers"]
        assert "Authorization" not in headers

    @pytest.mark.asyncio
    async def test_model_override_per_call(self, openai_service: LLMService) -> None:
        """model kwarg overrides the service-level model for a single call."""
        client = _mock_http_client(_openai_response("ok"))

        with patch("httpx.AsyncClient", return_value=client):
            result = await openai_service.complete("test", model="gpt-3.5-turbo")

        assert result is not None
        assert result.model == "gpt-3.5-turbo"
        payload = client.post.call_args.kwargs["json"]
        assert payload["model"] == "gpt-3.5-turbo"


# ---------------------------------------------------------------------------
# Anthropic provider
# ---------------------------------------------------------------------------


class TestAnthropicProvider:
    @pytest.mark.asyncio
    async def test_complete_returns_llm_response(self, anthropic_service: LLMService) -> None:
        """Anthropic complete() returns a populated LLMResponse."""
        client = _mock_http_client(_anthropic_response("42"))

        with patch("httpx.AsyncClient", return_value=client):
            result = await anthropic_service.complete("What is 6x7?")

        assert result is not None
        assert result.content == "42"
        assert result.provider == LLMProvider.ANTHROPIC

    @pytest.mark.asyncio
    async def test_uses_anthropic_messages_endpoint(self, anthropic_service: LLMService) -> None:
        """Anthropic uses /v1/messages, not /v1/chat/completions."""
        client = _mock_http_client(_anthropic_response("ok"))

        with patch("httpx.AsyncClient", return_value=client):
            await anthropic_service.complete("test")

        url = client.post.call_args.args[0]
        assert url.endswith("/v1/messages")

    @pytest.mark.asyncio
    async def test_system_prompt_as_top_level_field(self, anthropic_service: LLMService) -> None:
        """Anthropic system message is a top-level 'system' field, not in messages."""
        client = _mock_http_client(_anthropic_response("ok"))

        with patch("httpx.AsyncClient", return_value=client):
            await anthropic_service.complete("hello", system="Be concise.")

        payload = client.post.call_args.kwargs["json"]
        assert payload["system"] == "Be concise."
        assert all(m["role"] != "system" for m in payload["messages"])

    @pytest.mark.asyncio
    async def test_anthropic_version_header_sent(self, anthropic_service: LLMService) -> None:
        """anthropic-version header is included in every request."""
        client = _mock_http_client(_anthropic_response("ok"))

        with patch("httpx.AsyncClient", return_value=client):
            await anthropic_service.complete("test")

        headers = client.post.call_args.kwargs["headers"]
        assert "anthropic-version" in headers


# ---------------------------------------------------------------------------
# Response caching
# ---------------------------------------------------------------------------


class TestResponseCaching:
    @pytest.mark.asyncio
    async def test_second_call_hits_cache(self, openai_service: LLMService) -> None:
        """Identical calls must only issue one HTTP request; second is cached."""
        client = _mock_http_client(_openai_response("42"))

        with patch("httpx.AsyncClient", return_value=client):
            first = await openai_service.complete("What is 6x7?")
            second = await openai_service.complete("What is 6x7?")

        assert client.post.call_count == 1
        assert first is not None and second is not None
        assert second.cached is True
        assert second.content == "42"

    @pytest.mark.asyncio
    async def test_different_prompts_not_cached_together(self, openai_service: LLMService) -> None:
        """Different prompts must result in separate HTTP calls."""
        client = _mock_http_client(_openai_response("result"))

        with patch("httpx.AsyncClient", return_value=client):
            await openai_service.complete("prompt A")
            await openai_service.complete("prompt B")

        assert client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_bypass_cache_forces_new_request(self, openai_service: LLMService) -> None:
        """bypass_cache=True always calls the provider even if cache is warm."""
        client = _mock_http_client(_openai_response("42"))

        with patch("httpx.AsyncClient", return_value=client):
            await openai_service.complete("What is 6x7?")
            result = await openai_service.complete("What is 6x7?", bypass_cache=True)

        assert client.post.call_count == 2
        assert result is not None
        assert result.cached is False

    @pytest.mark.asyncio
    async def test_different_system_prompts_have_separate_cache_entries(
        self, openai_service: LLMService
    ) -> None:
        """System message is part of the cache key."""
        client = _mock_http_client(_openai_response("42"))

        with patch("httpx.AsyncClient", return_value=client):
            await openai_service.complete("hello", system="Be concise.")
            await openai_service.complete("hello", system="Be verbose.")

        assert client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_latency_tracked_on_cache_miss(self, openai_service: LLMService) -> None:
        """latency_seconds is populated on a fresh (non-cached) call."""
        client = _mock_http_client(_openai_response("ok"))

        with patch("httpx.AsyncClient", return_value=client):
            result = await openai_service.complete("test")

        assert result is not None
        assert result.latency_seconds >= 0.0
