"""
Provider factory for LLM agents.
"""
import os

from .base import LLMProvider
from .qwen_provider import QwenLLMProvider
from .freellm_provider import FreeLLMProvider
from .mock_provider import MockLLMProvider


def get_llm_provider() -> LLMProvider:
    """
    Return an LLM provider instance based on the AGENT_PROVIDER environment variable.
    Supported providers: "mock", "qwen", "freellm".
    Defaults to "mock".
    """
    provider_name = os.getenv("AGENT_PROVIDER", "mock").lower()
    if provider_name == "qwen":
        return QwenLLMProvider()
    if provider_name == "freellm":
        return FreeLLMProvider()
    # For any other value (including "mock") we return the mock provider.
    return MockLLMProvider()