import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent.providers import vision


@pytest.mark.asyncio
async def test_openai_compatible_vision_provider_sends_image_data_without_external_url(
    monkeypatch,
):
    create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="A red sneaker on a white floor.")
                )
            ]
        )
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=create),
        )
    )
    monkeypatch.setattr(vision, "AsyncOpenAI", lambda **_kwargs: client)
    monkeypatch.setattr(vision, "VISION_API_KEY", "test-only-key")
    monkeypatch.setattr(vision, "VISION_BASE_URL", "https://vision.example.test/v1")
    monkeypatch.setattr(vision, "VISION_MODEL", "vision-test-model")

    provider = vision.OpenAICompatibleVisionProvider.from_settings()
    assert provider is not None
    observation = await provider.describe_image(b"local-image-bytes", "image/png")

    assert observation == "A red sneaker on a white floor."
    message = create.await_args.kwargs["messages"][1]
    image_url = message["content"][1]["image_url"]["url"]
    assert image_url == (
        "data:image/png;base64,"
        + base64.b64encode(b"local-image-bytes").decode("ascii")
    )
    assert "https://" not in image_url


def test_vision_provider_requires_explicit_compatible_model_configuration(monkeypatch):
    monkeypatch.setattr(vision, "VISION_API_KEY", "")
    monkeypatch.setattr(vision, "VISION_BASE_URL", "https://vision.example.test/v1")
    monkeypatch.setattr(vision, "VISION_MODEL", "vision-test-model")

    assert vision.OpenAICompatibleVisionProvider.from_settings() is None
