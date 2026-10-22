import logging
from types import SimpleNamespace

import pytest

from app.agent.providers.base import LLMMessage
from app.agent.providers.qwen_provider import QwenLLMProvider


@pytest.mark.asyncio
async def test_provider_failure_log_does_not_include_exception_details(caplog):
    async def fail_request(**_kwargs):
        raise RuntimeError("sensitive-provider-response")

    provider = object.__new__(QwenLLMProvider)
    provider.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=fail_request),
        )
    )
    provider.model = "test-model"
    provider.max_retries = 0

    with caplog.at_level(logging.ERROR, logger="app.agent.providers.qwen_provider"):
        response = await provider.chat([LLMMessage(role="user", content="hello")])

    assert response.finish_reason == "error"
    assert "RuntimeError" in caplog.text
    assert "sensitive-provider-response" not in caplog.text
