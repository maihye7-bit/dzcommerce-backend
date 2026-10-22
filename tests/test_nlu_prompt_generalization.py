import asyncio
import json
import uuid

import pytest

from app.agent.conversation_engine import ConversationEngine
from app.agent.commerce_resolver import CommerceResolver
from app.agent.providers.base import LLMResponse
from app.agent.tools.registry import ToolRegistry
from app.models.conversation import Conversation, Message, MessageRole
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
    assert "sentence structure and conversation state" in prompt
    assert "whole utterance, not isolated words" in prompt
    assert "memorized example phrases" in prompt
    assert "حبيت ندير كوموند واحد" not in prompt
    assert "n7ab ndir commande" not in prompt
    assert "Do NOT invent IDs." in prompt
    assert "Do NOT output commerce decisions" in prompt
    assert "No such policy facts are present" in prompt


def test_qwen_receives_compact_product_and_recent_turn_context() -> None:
    provider = PromptCaptureProvider()
    engine = ConversationEngine(llm_provider=provider, tool_registry=ToolRegistry())
    product_id = str(uuid.uuid4())

    asyncio.run(
        engine._extract_nlu_via_qwen(
            "شحال؟",
            {
                "commerce_stage": "PRODUCT_SELECTED",
                "selected_product_id": product_id,
                "selected_product_name": "Samsung Galaxy",
                "selected_attributes": {"color": "black"},
                "last_question_type": "PRODUCT_DETAILS_OFFER",
            },
            dialogue_context=[
                {"role": "customer", "content": "نحب Samsung noir"},
                {"role": "assistant", "content": "أي لون تريد؟"},
            ],
        )
    )

    context = json.loads(provider.messages[1].content.split("\n", 1)[1])
    serialized = json.dumps(context, ensure_ascii=False)
    assert context["selected_product_name"] == "Samsung Galaxy"
    assert context["selected_attributes"] == {"color": "black"}
    assert context["recent_turns"][0]["content"] == "نحب Samsung noir"
    assert product_id not in serialized


def test_vague_repair_request_uses_nlu_confidence_instead_of_phrase_shortcut() -> None:
    provider = PromptCaptureProvider()
    engine = ConversationEngine(llm_provider=provider, tool_registry=ToolRegistry())

    result = asyncio.run(
        engine._extract_nlu_via_qwen(
            "ما فهمتش",
            {"last_question_type": "VARIANT_SELECTION"},
        )
    )

    assert result["intent"] == "unknown"
    assert result["product_mention"] is None
    assert provider.messages


def test_contextual_intent_uses_high_confidence_nlu_for_unseen_purchase_wording() -> None:
    engine = ConversationEngine(llm_provider=None, tool_registry=ToolRegistry())

    intent, confidence = engine._understand_intent_from_context(
        "I intend to make a purchase",
        {"nlu_intent": "order_create", "nlu_confidence": 0.96},
    )

    assert intent == "order_create"
    assert confidence == 0.96


def test_low_confidence_intent_uses_selected_product_context_for_details() -> None:
    engine = ConversationEngine(llm_provider=None, tool_registry=ToolRegistry())

    intent, confidence = engine._understand_intent_from_context(
        "اريد تفاصيل",
        {
            "commerce_stage": "PRODUCT_SELECTED",
            "selected_product_id": str(uuid.uuid4()),
            "selected_product_name": "Samsung",
            "nlu_intent": "unknown",
            "nlu_confidence": 0.1,
        },
    )

    assert intent == "product_details"
    assert confidence >= 0.8


def test_ambiguous_low_confidence_message_remains_unresolved() -> None:
    engine = ConversationEngine(llm_provider=None, tool_registry=ToolRegistry())

    intent, confidence = engine._understand_intent_from_context(
        "hmm",
        {"commerce_stage": "EMPTY", "nlu_intent": "order_create", "nlu_confidence": 0.2},
    )

    assert intent == "unknown"
    assert confidence < 0.6


def test_missing_nlu_confidence_does_not_authorize_a_purchase_guess() -> None:
    class ConfidenceOmittingProvider:
        async def chat(self, messages, tools=None, system_prompt=None):
            return LLMResponse(content='{"intent":"order_create"}')

    engine = ConversationEngine(
        llm_provider=ConfidenceOmittingProvider(),
        tool_registry=ToolRegistry(),
    )

    result = asyncio.run(
        engine._extract_nlu_via_qwen("a vague unfamiliar message", {})
    )

    assert result["intent"] == "unknown"
    assert result["confidence"] < 0.6


def test_contextual_intent_accepts_confident_greeting_from_nlu() -> None:
    engine = ConversationEngine(llm_provider=None, tool_registry=ToolRegistry())

    intent, confidence = engine._understand_intent_from_context(
        "an unfamiliar greeting",
        {"commerce_stage": "EMPTY", "nlu_intent": "greeting", "nlu_confidence": 0.91},
    )

    assert intent == "greeting"
    assert confidence == 0.91


def test_heuristic_recognizes_darija_price_and_purchase_requests() -> None:
    engine = ConversationEngine(llm_provider=None, tool_registry=ToolRegistry())
    selected_state = {
        "selected_product_id": str(uuid.uuid4()),
        "selected_product_name": "Samsung",
    }

    for message in ("سعر", "سومة سامسونغ", "شحال سامسونغ", "بشحال"):
        assert engine._heuristic_nlu(message, selected_state)["intent"] == "product_details"

    assert engine._heuristic_nlu("سعر")["intent"] == "unknown"

    for message in ("حبيت نكومندي واحد", "نحب ندي واحد"):
        nlu = engine._heuristic_nlu(message, selected_state)
        assert nlu["intent"] == "order_create"
        assert nlu["quantity"] == 1

    nlu = engine._heuristic_nlu("نحب نشري", selected_state)
    assert nlu["intent"] == "order_create"
    assert nlu["quantity"] is None

    unrelated_one = engine._heuristic_nlu("عندي واحد سؤال", selected_state)
    assert unrelated_one["intent"] == "unknown"
    assert unrelated_one["quantity"] is None

    purchase_with_quantity = engine._heuristic_nlu("نحب نشري 3", selected_state)
    assert purchase_with_quantity["intent"] == "order_create"
    assert purchase_with_quantity["quantity"] == 3

    number_without_purchase_context = engine._heuristic_nlu("2", selected_state)
    assert number_without_purchase_context["intent"] != "order_create"
    assert number_without_purchase_context["quantity"] is None


@pytest.mark.parametrize(
    ("message", "quantity"),
    [
        ("حبيت ندير كوموند واحد", 1),
        ("نبغي نطلب", None),
        ("ندير كوموند", None),
        ("نكوموندي", None),
        ("n7ab ndir commande wa7ed", 1),
        ("bghit ncommandi", None),
    ],
)
def test_heuristic_recognizes_additional_algerian_purchase_phrases(
    message,
    quantity,
) -> None:
    engine = ConversationEngine(llm_provider=None, tool_registry=ToolRegistry())

    nlu = engine._heuristic_nlu(message)

    assert nlu["intent"] == "order_create"
    assert nlu["quantity"] == quantity
    assert nlu["confirmation_phrase"] is False


def test_purchase_completion_construction_is_not_mistaken_for_product_search() -> None:
    engine = ConversationEngine(llm_provider=None, tool_registry=ToolRegistry())

    nlu = engine._heuristic_nlu("اتمام الشراء")

    assert nlu["intent"] == "order_create"
    assert nlu["product_mention"] is None


@pytest.mark.parametrize(
    "message",
    [
        "حبيت ندير كوموند واحد",
        "نبغي نطلب",
        "n7ab ndir commande wa7ed",
        "bghit ncommandi",
    ],
)
def test_explicit_purchase_phrases_override_incorrect_search_nlu(message) -> None:
    class IncorrectSearchProvider:
        async def chat(self, messages, tools=None, system_prompt=None):
            return LLMResponse(
                content=json.dumps(
                    {"intent": "product_search", "product_mention": message},
                    ensure_ascii=False,
                )
            )

    engine = ConversationEngine(
        llm_provider=IncorrectSearchProvider(),
        tool_registry=ToolRegistry(),
    )

    nlu = asyncio.run(engine._extract_nlu_via_qwen(message, {}))

    assert nlu["intent"] == "order_create"
    assert nlu["quantity"] == 1


def test_reference_darija_and_arabizi_messages_are_classified_conservatively() -> None:
    engine = ConversationEngine(llm_provider=None, tool_registry=ToolRegistry())
    selected_state = {
        "selected_product_id": str(uuid.uuid4()),
        "selected_product_name": "Samsung",
    }
    examples = [
        (
            "salam, wach kayen Samsung?",
            {},
            "product_search",
            "Samsung",
            {},
            None,
        ),
        ("ch7al?", selected_state, "product_details", None, {}, None),
        ("bch7al Samsung?", {}, "product_search", "Samsung", {}, None),
        ("n7ab nechri wa7ed", {}, "order_create", None, {}, 1),
        ("n7ab nechri 1", {}, "order_create", None, {}, 1),
        (
            "n7ab Samsung noir",
            {},
            "product_search",
            "Samsung",
            {"color": "black"},
            None,
        ),
        (
            "n7ab Samsung noir, ch7al?",
            {},
            "product_search",
            "Samsung",
            {"color": "black"},
            None,
        ),
        ("livraison l Setif ch7al?", {}, "unknown", None, {}, None),
        ("3andkom had produit?", {}, "unknown", None, {}, None),
        ("ma3lich, n7ab wa7ed", {}, "unknown", None, {}, None),
        ("حبيت نكوموندي واحد", {}, "order_create", None, {}, 1),
        ("شحال السومة؟", {}, "unknown", None, {}, None),
        (
            "شحال السومة؟",
            selected_state,
            "product_details",
            None,
            {},
            None,
        ),
    ]

    for message, state, intent, product_mention, attributes, quantity in examples:
        result = engine._heuristic_nlu(message, state)
        assert result["intent"] == intent, message
        assert result["product_mention"] == product_mention, message
        assert result["attributes"] == attributes, message
        assert result["quantity"] == quantity, message
        assert result["intent"] != "order_confirm" or result["confirmation_phrase"]


def test_product_search_phrase_is_reduced_to_the_catalog_entity() -> None:
    engine = ConversationEngine(llm_provider=None, tool_registry=ToolRegistry())

    result = engine._heuristic_nlu("نحوس على هاتف سامسونغ")

    assert result["intent"] == "product_search"
    assert result["product_mention"] == "سامسونغ"


def test_local_entity_cleanup_corrects_a_whole_message_as_search_query() -> None:
    class IncorrectEntityProvider:
        async def chat(self, messages, tools=None, system_prompt=None):
            return LLMResponse(
                content=json.dumps(
                    {
                        "intent": "product_search",
                        "product_mention": "نحوس على هاتف سامسونغ",
                        "language": "ar",
                        "confidence": 0.95,
                    },
                    ensure_ascii=False,
                )
            )

    engine = ConversationEngine(
        llm_provider=IncorrectEntityProvider(),
        tool_registry=ToolRegistry(),
    )

    result = asyncio.run(
        engine._extract_nlu_via_qwen("نحوس على هاتف سامسونغ", {})
    )

    assert result["intent"] == "product_search"
    assert result["product_mention"] == "سامسونغ"


def test_purchase_reference_uses_selected_product_context() -> None:
    engine = ConversationEngine(llm_provider=None, tool_registry=ToolRegistry())
    state = {
        "commerce_stage": "PRODUCT_SELECTED",
        "selected_product_id": str(uuid.uuid4()),
        "selected_product_name": "Samsung Galaxy",
    }

    result = engine._heuristic_nlu("حبيت نشريه", state)

    assert result["intent"] == "order_create"
    assert result["product_mention"] is None


def test_order_guidance_is_not_a_product_search() -> None:
    engine = ConversationEngine(llm_provider=None, tool_registry=ToolRegistry())

    result = engine._heuristic_nlu("كيفاه ندير طلب")

    assert result["intent"] == "order_create"
    assert result["product_mention"] is None


def test_purchase_with_named_product_preserves_entity_and_purchase_intent() -> None:
    engine = ConversationEngine(llm_provider=None, tool_registry=ToolRegistry())

    result = engine._heuristic_nlu("نحوس ندير طلب على سامسونغ")

    assert result["intent"] == "order_create"
    assert result["product_mention"] == "سامسونغ"


def test_named_purchase_resolves_to_catalog_search_without_changing_intent(db_session):
    engine = ConversationEngine(llm_provider=None, tool_registry=ToolRegistry())
    nlu = engine._heuristic_nlu("نحوس ندير طلب على سامسونغ")

    decision = CommerceResolver(db_session).resolve(
        nlu_output=nlu,
        current_state={"commerce_stage": "EMPTY"},
        store_id=uuid.uuid4(),
    )

    assert nlu["intent"] == "order_create"
    assert decision.allowed_action == "EXECUTE_TOOL:search_products"
    assert decision.resolved_entities["query"] == "سامسونغ"


def test_order_guidance_without_product_does_not_search(db_session):
    engine = ConversationEngine(llm_provider=None, tool_registry=ToolRegistry())
    nlu = engine._heuristic_nlu("كيفاه ندير طلب")

    decision = CommerceResolver(db_session).resolve(
        nlu_output=nlu,
        current_state={"commerce_stage": "EMPTY"},
        store_id=uuid.uuid4(),
    )

    assert nlu["intent"] == "order_create"
    assert decision.allowed_action == "RESPOND:text_only"
    assert "نبدأ" in decision.response_hint


def test_empty_conversation_greeting_uses_deterministic_greeting_intent() -> None:
    engine = ConversationEngine(llm_provider=None, tool_registry=ToolRegistry())

    assert engine._heuristic_nlu("السلام عليكم")["intent"] == "greeting"


def test_general_catalog_question_has_a_distinct_intent() -> None:
    engine = ConversationEngine(llm_provider=None, tool_registry=ToolRegistry())

    result = engine._heuristic_nlu("وش عندكم منتجات؟")

    assert result["intent"] == "catalog_browse"
    assert result["product_mention"] is None


def test_unknown_qwen_intents_use_local_darija_fallback_without_inventing_delivery(
) -> None:
    provider = PromptCaptureProvider()
    engine = ConversationEngine(llm_provider=provider, tool_registry=ToolRegistry())
    state = {}
    examples = [
        (
            "salam, wach kayen Samsung?",
            "product_search",
            "Samsung",
        ),
        ("n7ab nechri wa7ed", "order_create", None),
        ("livraison l Setif ch7al?", "unknown", None),
        ("3andkom had produit?", "unknown", None),
    ]

    for message, expected_intent, expected_mention in examples:
        result = asyncio.run(engine._extract_nlu_via_qwen(message, state))
        assert result["intent"] == expected_intent, message
        assert result["product_mention"] == expected_mention, message


def test_price_question_cannot_be_promoted_to_purchase_by_nlu() -> None:
    class IncorrectPurchaseProvider:
        async def chat(self, messages, tools=None, system_prompt=None):
            return LLMResponse(
                content=json.dumps(
                    {"intent": "order_create", "quantity": 1},
                    ensure_ascii=False,
                )
            )

    engine = ConversationEngine(
        llm_provider=IncorrectPurchaseProvider(),
        tool_registry=ToolRegistry(),
    )
    result = asyncio.run(
        engine._extract_nlu_via_qwen("ch7al?", {"selected_product_id": str(uuid.uuid4())})
    )

    assert result["intent"] == "product_details"
    assert result["quantity"] is None


@pytest.mark.parametrize(
    ("message", "state", "expected_intent", "expected_mention"),
    [
        ("bch7al Samsung?", {}, "product_search", "Samsung"),
        ("n7ab Samsung noir", {}, "product_search", "Samsung"),
    ],
)
def test_nlu_cannot_turn_price_or_unresolved_product_into_purchase(
    message,
    state,
    expected_intent,
    expected_mention,
) -> None:
    class IncorrectPurchaseProvider:
        async def chat(self, messages, tools=None, system_prompt=None):
            return LLMResponse(
                content=json.dumps(
                    {"intent": "order_create", "quantity": 1},
                    ensure_ascii=False,
                )
            )

    engine = ConversationEngine(
        llm_provider=IncorrectPurchaseProvider(),
        tool_registry=ToolRegistry(),
    )
    result = asyncio.run(engine._extract_nlu_via_qwen(message, state))

    assert result["intent"] == expected_intent
    assert result["product_mention"] == expected_mention
    assert result["quantity"] is None


def test_purchase_with_requested_color_must_resolve_variant_before_draft() -> None:
    class IncorrectPurchaseProvider:
        async def chat(self, messages, tools=None, system_prompt=None):
            return LLMResponse(
                content=json.dumps(
                    {"intent": "order_create", "quantity": 1},
                    ensure_ascii=False,
                )
            )

    engine = ConversationEngine(
        llm_provider=IncorrectPurchaseProvider(),
        tool_registry=ToolRegistry(),
    )
    result = asyncio.run(
        engine._extract_nlu_via_qwen(
            "n7ab nechri Samsung noir",
            {
                "selected_product_id": str(uuid.uuid4()),
                "selected_product_name": "Samsung",
                "selected_variant_id": str(uuid.uuid4()),
                "commerce_stage": "VARIANT_SELECTED",
            },
        )
    )

    assert result["intent"] == "variant_selection"
    assert result["attributes"] == {"color": "black"}


def test_yes_and_numeric_replies_require_matching_prior_context() -> None:
    validate = ConversationEngine._validate_nlu_context
    draft_state = {
        "commerce_stage": "DRAFT_PENDING",
        "last_question_type": "ORDER_CONFIRMATION",
        "active_draft_json": {
            "items": [{"variant_id": str(uuid.uuid4()), "quantity": 1}]
        },
    }

    confirmed = validate(
        {"intent": "unknown"},
        "نعم",
        draft_state,
    )
    no_confirmation_context = validate(
        {"intent": "order_confirm", "confirmation_phrase": True},
        "نعم",
        {**draft_state, "last_question_type": "SHIPPING_INFO"},
    )
    listed_option = validate(
        {"intent": "unknown"},
        "2",
        {
            "last_question_type": "VARIANT_SELECTION",
            "selected_product_id": "product-1",
            "variant_index_map_product_id": "product-1",
            "variant_index_map": {"2": "variant-2"},
        },
    )
    unlisted_number = validate(
        {"intent": "variant_selection"},
        "2",
        {
            "last_question_type": None,
        },
    )

    assert confirmed["intent"] == "order_confirm"
    assert no_confirmation_context["intent"] == "unknown"
    assert listed_option["intent"] == "variant_selection"
    assert listed_option["variant_index"] == 2
    assert unlisted_number["intent"] == "unknown"
    assert unlisted_number.get("variant_index") is None


def test_nlu_context_omits_all_message_history_and_allowlists_state(db_session):
    from app.models.customer import Customer
    from app.models.store import Store

    store = Store(name="NLU history store", slug=f"nlu-{uuid.uuid4()}")
    db_session.add(store)
    db_session.flush()
    customer = Customer(store_id=store.id, name="NLU history customer")
    db_session.add(customer)
    db_session.flush()
    conversation = Conversation(
        store_id=store.id,
        customer_id=customer.id,
        channel="test",
        status="active",
        metadata_json={},
    )
    db_session.add(conversation)
    db_session.flush()
    other_store = Store(name="Other NLU store", slug=f"other-nlu-{uuid.uuid4()}")
    db_session.add(other_store)
    db_session.flush()
    other_customer = Customer(store_id=other_store.id, name="Other NLU customer")
    db_session.add(other_customer)
    db_session.flush()
    other_conversation = Conversation(
        store_id=other_store.id,
        customer_id=other_customer.id,
        channel="test",
        status="active",
        metadata_json={},
    )
    db_session.add(other_conversation)
    db_session.flush()
    db_session.add_all(
        [
            Message(
                conversation_id=conversation.id,
                role=MessageRole.CUSTOMER,
                content="SENSITIVE-HISTORY-EMAIL user@example.test 123 Main Street",
            ),
            Message(
                conversation_id=conversation.id,
                role=MessageRole.AGENT,
                content="PRIVATE-BOT-HISTORY-DO-NOT-SEND",
            ),
            Message(
                conversation_id=other_conversation.id,
                role=MessageRole.CUSTOMER,
                content="CROSS-CONVERSATION-SECRET-HISTORY",
            ),
        ]
    )
    db_session.commit()

    provider = PromptCaptureProvider()
    engine = ConversationEngine(llm_provider=provider, tool_registry=ToolRegistry())
    asyncio.run(
        engine._extract_nlu_via_qwen(
            "نعم",
            {
                "last_question_type": "PRODUCT_DETAILS_OFFER",
                "commerce_stage": "PRODUCT_SELECTED",
                "selected_product_name": "Samsung",
                "selected_product_id": str(uuid.uuid4()),
                "candidate_product_ids": [str(uuid.uuid4())],
                "customer_phone": "+1-202-555-0100",
                "active_draft_json": None,
            },
            db=db_session,
            store_id=store.id,
            conversation_id=conversation.id,
        )
    )

    serialized_messages = json.dumps(
        [message.__dict__ for message in provider.messages],
        ensure_ascii=False,
    )
    nlu_context = json.loads(provider.messages[1].content.split("\n", 1)[1])
    assert "نعم" in serialized_messages
    assert "PRODUCT_DETAILS_OFFER" in serialized_messages
    assert "PRODUCT_SELECTED" in serialized_messages
    assert nlu_context["selected_product_name"] is None
    assert "customer_phone" not in serialized_messages
    assert "selected_product_id" not in serialized_messages
    assert "SENSITIVE-HISTORY-EMAIL" not in serialized_messages
    assert "PRIVATE-BOT-HISTORY" not in serialized_messages
    assert "CROSS-CONVERSATION-SECRET" not in serialized_messages


@pytest.mark.parametrize(
    "sensitive_message",
    [
        "السعر سامسونغ user@example.test",
        "سومة سامسونغ +1 (202) 555-0100",
        "سعر سامسونغ 06 12 34 56 78",
        "السعر سامسونغ ٠٦١٢٣٤٥٦٧٨",
        "شحال سامسونغ 123 Main Street",
        "سومة سامسونغ 12 rue Exemple",
        "سعر سامسونغ ١٢ شارع النخيل",
        "طلب سامسونغ password=hunter2",
        "تفاصيل سامسونغ token sk-test-token-value-12345",
        "الدفع ببطاقة ائتمان 4111 1111 1111 1111",
    ],
)
def test_sensitive_current_message_never_reaches_provider(sensitive_message):
    provider = PromptCaptureProvider()
    engine = ConversationEngine(llm_provider=provider, tool_registry=ToolRegistry())

    result = asyncio.run(
        engine._extract_nlu_via_qwen(
            sensitive_message,
            {
                "selected_product_id": str(uuid.uuid4()),
                "selected_product_name": "Samsung",
                "commerce_stage": "PRODUCT_SELECTED",
            },
        )
    )

    assert provider.messages == []
    assert result["intent"] in {"product_details", "order_create", "unknown"}


def test_numeric_selection_is_contextual_and_uses_engine_validated_index():
    validate = ConversationEngine._validate_nlu_context
    product_id = str(uuid.uuid4())
    state = {
        "commerce_stage": "PRODUCT_SELECTED",
        "last_question_type": "VARIANT_SELECTION",
        "variant_index_map": {"1": str(uuid.uuid4()), "2": str(uuid.uuid4())},
        "variant_index_map_product_id": product_id,
        "selected_product_id": product_id,
    }

    selected = validate(
        {"intent": "unknown", "attributes": {"size": "1"}},
        "2",
        state,
    )
    assert selected["intent"] == "variant_selection"
    assert selected["variant_index"] == 2
    assert selected["attributes"] == {}

    unrelated = validate(
        {"intent": "variant_selection", "attributes": {"size": "1"}},
        "1",
        {**state, "last_question_type": None},
    )
    assert unrelated["intent"] == "unknown"
    assert unrelated.get("variant_index") is None


def test_invalid_qwen_intent_uses_controlled_darija_fallback() -> None:
    provider = PromptCaptureProvider()
    provider.chat = _invalid_nlu_response
    engine = ConversationEngine(llm_provider=provider, tool_registry=ToolRegistry())

    nlu = asyncio.run(
        engine._extract_nlu_via_qwen(
            "حبيت نكومندي واحد",
            {"selected_product_id": str(uuid.uuid4())},
        )
    )

    assert nlu["intent"] == "order_create"
    assert nlu["quantity"] == 1


def test_incomplete_qwen_order_intent_uses_contextual_quantity_fallback() -> None:
    provider = PromptCaptureProvider()
    provider.chat = _incomplete_order_response
    engine = ConversationEngine(llm_provider=provider, tool_registry=ToolRegistry())

    nlu = asyncio.run(
        engine._extract_nlu_via_qwen(
            "حبيت نكومندي واحد",
            {"selected_product_id": str(uuid.uuid4())},
        )
    )

    assert nlu["intent"] == "order_create"
    assert nlu["quantity"] == 1


async def _invalid_nlu_response(messages, tools=None, system_prompt=None):
    return LLMResponse(content=json.dumps({"intent": "not-a-valid-intent"}))


async def _incomplete_order_response(messages, tools=None, system_prompt=None):
    return LLMResponse(content=json.dumps({"intent": "order_create"}))
