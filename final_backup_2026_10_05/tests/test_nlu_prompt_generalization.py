import asyncio

from app.agent.conversation_engine import ConversationEngine
from app.agent.providers.base import LLMResponse
from app.agent.tools.registry import ToolRegistry
from app.services.attribute_normalizer import normalize_attributes


def test_heuristic_extracts_general_product_attributes() -> None:
    engine = ConversationEngine(llm_provider=None, tool_registry=ToolRegistry())
    examples = [
        (
            "تليفون 256 غيغا أسود",
            {"storage": "256gb", "color": "black"},
        ),
        (
            "طاولة خشب بيضا",
            {"material": "wood", "color": "white"},
        ),
        (
            "عسل 500 غرام",
            {"weight": "500g"},
        ),
    ]

    for message, expected_attributes in examples:
        nlu = engine._heuristic_nlu(message)
        assert nlu["intent"] == "variant_selection"
        assert normalize_attributes(nlu["attributes"]) == expected_attributes


class PromptCaptureProvider:
    def __init__(self) -> None:
        self.messages = []

    async def chat(self, messages, tools=None, system_prompt=None) -> LLMResponse:
        self.messages = messages
        return LLMResponse(content='{"intent":"unknown"}')


def test_qwen_prompt_contains_open_attributes_and_multi_sector_examples() -> None:
    provider = PromptCaptureProvider()
    engine = ConversationEngine(llm_provider=provider, tool_registry=ToolRegistry())

    asyncio.run(engine._extract_nlu_via_qwen("طاولة", {}))
    prompt = provider.messages[0].content

    assert '"attributes": { "اسم_السمة": "القيمة كما قالها العميل" }' in prompt
    assert "عايز نوت بش ٢٥٦ غيغا كحل" in prompt
    assert "كاكاو ٤٠٠ غرام" in prompt
    assert "طاولة خشب بيضا" in prompt
    assert "نحب قميص مقاس M أزرق" in prompt
    assert "Do NOT invent IDs." in prompt
    assert "Do NOT output commerce decisions" in prompt
