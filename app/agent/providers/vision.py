"""Provider-independent image understanding over an OpenAI-compatible API."""

import base64
from typing import Protocol

from openai import AsyncOpenAI

from app.core.config import (
    VISION_API_KEY,
    VISION_BASE_URL,
    VISION_MODEL,
    VISION_TIMEOUT,
)


class ImageUnderstandingProvider(Protocol):
    async def describe_image(self, image: bytes, mime_type: str) -> str: ...


class OpenAICompatibleVisionProvider:
    def __init__(
        self,
        client: AsyncOpenAI,
        model: str,
    ) -> None:
        self.client = client
        self.model = model

    @classmethod
    def from_settings(cls) -> "OpenAICompatibleVisionProvider | None":
        if not VISION_API_KEY or not VISION_BASE_URL or not VISION_MODEL:
            return None
        client = AsyncOpenAI(
            api_key=VISION_API_KEY,
            base_url=VISION_BASE_URL,
            timeout=float(VISION_TIMEOUT),
        )
        return cls(client=client, model=VISION_MODEL)

    async def describe_image(self, image: bytes, mime_type: str) -> str:
        image_data = base64.b64encode(image).decode("ascii")
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Describe only visible, relevant details in the image. "
                        "Do not identify a product as a catalog item, infer hidden "
                        "attributes, or make claims about price, stock, authenticity, "
                        "or ownership. Return a concise plain-text observation."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "What is visibly shown in this image?",
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{image_data}",
                                "detail": "low",
                            },
                        },
                    ],
                },
            ],
            temperature=0,
            max_tokens=300,
        )
        content = response.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Vision provider returned no image description.")
        return content.strip()[:800]
