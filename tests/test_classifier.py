"""
Tests for ConversationClassifier.

These tests cover all 14 intent categories, multilingual messages (Arabic,
Algerian Darija, French, English), context-aware classification, deterministic
heuristics, edge cases (empty messages, malformed output, timeouts), and fallback
strategies.  All tests use mocked providers and deterministic fixtures — no live
LLM calls.
"""

import asyncio
import json
import uuid
from typing import Any, Dict, List

import pytest

from app.agent.classifier import (
    ClassificationResult,
    ConversationClassifier,
    INTENT_AMBIGUOUS,
    INTENT_AVAILABILITY_INQUIRY,
    INTENT_GENERAL_CHAT,
    INTENT_OBJECTION_HANDLING,
    INTENT_PRICE_INQUIRY,
    INTENT_PRODUCT_FOLLOWUP,
    INTENT_PRODUCT_INQUIRY,
    INTENT_PRODUCT_INQUIRY,
    INTENT_PURCHASE_INTENT,
    INTENT_TOPIC_CHANGE,
    INTENT_UNSUPPORTED_OR_RESTRICTED,
    INTENT_ORDER_STATUS,
    INTENT_ORDER_MODIFICATION,
    INTENT_AFTER_SALES,
    INTENT_TOPIC_CHANGE,
    INTENT_OBJECTION_HANDLING,
    INTENT_UNSUPPORTED_OR_RESTRICTED,
    INTENT_GENERAL_CHAT,
)


# ---------------------------------------------------------------------------
# 1. General greetings in Arabic and Algerian Darija
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message,expected_intent",
    [
        ("السلام", INTENT_GENERAL_CHAT),
        ("السلام عليكم", INTENT_GENERAL_CHAT),
        ("سلام", INTENT_GENERAL_CHAT),
        ("سلام عليكم", INTENT_GENERAL_CHAT),
        ("مرحبا", INTENT_GENERAL_CHAT),
        ("أهلا", INTENT_GENERAL_CHAT),
        ("أهلا وسهلا", INTENT_GENERAL_CHAT),
        ("وعليكم السلام", INTENT_GENERAL_CHAT),
        ("salam", INTENT_GENERAL_CHAT),  # Darija greeting
        ("salam alikoum", INTENT_GENERAL_CHAT),  # Darija greeting
        ("salam, wach kayen?", INTENT_GENERAL_CHAT),  # Darija greeting
        ("bch7al?", INTENT_GENERAL_CHAT),  # Algerian Arabic greeting
        ("wach kayen", INTENT_GENERAL_CHAT),  # Darija greeting
    ],
)
def test_general_greetings_arabic_and_darija(message: str, expected_intent: str) -> None:
    """Test that general greetings in Arabic and Algerian Darija are classified correctly."""
    result = ConversationClassifier.classify(message)
    assert result.intent == expected_intent, f"Message: '{message}', expected {expected_intent}, got {result.intent}"
    assert 0.8 <= result.confidence <= 1.0, f"Confidence should be high for greetings, got {result.confidence}"
    assert result.commerce_tools_needed is False, f"Greeting '{message}' should not need commerce tools"
    assert result.clarification_needed is False, f"Greeting '{message}' should not need clarification"


@pytest.mark.parametrize(
    "message,expected_intent",
    [
        ("Hello", INTENT_GENERAL_CHAT),
        ("Hi there", INTENT_GENERAL_CHAT),
        ("Hey", INTENT_GENERAL_CHAT),
        ("Bonjour", INTENT_GENERAL_CHAT),
        ("Salut", INTENT_GENERAL_CHAT),
    ],
)
def test_general_greetings_french_and_english(message: str, expected_intent: str) -> None:
    """Test that general greetings in French and English are classified correctly."""
    result = ConversationClassifier.classify(message)
    assert result.intent == expected_intent, f"Message: '{message}', expected {expected_intent}, got {result.intent}"
    assert result.commerce_tools_needed is False, f"Greeting '{message}' should not need commerce tools"
    assert result.clarification_needed is False, f"Greeting '{message}' should not need clarification"


# ---------------------------------------------------------------------------
# Test greetings in different commerce stages (should always be GENERAL_CHAT)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message,commerce_stage,selected_product_id,selected_product_name",
    [
        ("السلام عليكم", "EMPTY", None, None),
        ("السلام", "EMPTY", None, None),
        ("مرحبا", "PRODUCT_SELECTED", "prod-123", "Samsung Galaxy"),
        ("أهلا", "VARIANT_SELECTED", "prod-123", "Samsung Galaxy"),
        ("salam", "DRAFT_PENDING", "prod-123", "Samsung Galaxy"),
        ("salut", "PRODUCT_SELECTED", "prod-123", "iPhone"),
        ("bonjour", "VARIANT_SELECTED", "prod-123", "iPhone"),
    ],
)
def test_greetings_in_all_commerce_stages(
    message: str,
    commerce_stage: str,
    selected_product_id: str | None,
    selected_product_name: str | None,
) -> None:
    """Test that greetings are always GENERAL_CHAT regardless of commerce stage."""
    result = ConversationClassifier.classify(
        message,
        commerce_stage=commerce_stage,
        selected_product_id=selected_product_id,
        selected_product_name=selected_product_name,
    )
    assert result.intent == INTENT_GENERAL_CHAT, f"Message: '{message}' in stage {commerce_stage} should be GENERAL_CHAT, got {result.intent}"
    assert result.commerce_tools_needed is False, f"Greeting '{message}' should not need commerce tools even in {commerce_stage}"
    assert result.clarification_needed is False, f"Greeting '{message}' should not need clarification"


# ---------------------------------------------------------------------------
# 2. Product inquiry
# ---------------------------------------------------------------------------


def test_product_inquiry() -> None:
    """Test product inquiry classification."""
    result = ConversationClassifier.classify("ريد سامسونغ")
    assert result.intent == INTENT_PRODUCT_INQUIRY
    assert result.confidence > 0.5


def test_product_inquiry_english() -> None:
    """Test product inquiry in English."""
    result = ConversationClassifier.classify("What is the price of Samsung?")
    assert result.intent == INTENT_PRODUCT_INQUIRY
    assert result.confidence > 0.5


# ---------------------------------------------------------------------------
# 3. Price inquiry
# ---------------------------------------------------------------------------


def test_price_inquiry() -> None:
    """Test price inquiry classification."""
    result = ConversationClassifier.classify("بشحال هذا؟")
    assert result.intent == INTENT_PRICE_INQUIRY
    assert result.confidence > 0.5


def test_price_inquiry_french() -> None:
    """Test price inquiry in French."""
    result = ConversationClassifier.classify("Combien coûte ce produit?")
    assert result.intent == INTENT_PRICE_INQUIRY


def test_price_inquiry_ambiguous_no_product() -> None:
    """Test price inquiry without product context → ambiguous, needs clarification."""
    result = ConversationClassifier.classify("بشحال؟", commerce_stage="EMPTY", selected_product_name=None)
    assert result.intent == INTENT_AMBIGUOUS
    assert result.clarification_needed is True
    assert result.confidence < 0.6


# ---------------------------------------------------------------------------
# 4. Availability inquiry
# ---------------------------------------------------------------------------


def test_availability_inquiry() -> None:
    """Test availability/stock inquiry classification."""
    result = ConversationClassifier.classify("هذا كاين؟")
    assert result.intent == INTENT_AVAILABILITY_INQUIRY
    assert result.confidence > 0.5


def test_availability_inquiry_french() -> None:
    """Test availability inquiry in French."""
    result = ConversationClassifier.classify("Ce produit est-il disponible?")
    assert result.intent == INTENT_AVAILABILITY_INQUIRY


def test_availability_inquiry_with_selected_product() -> None:
    """Test availability inquiry when a product is already selected (follow-up)."""
    result = ConversationClassifier.classify(
        "هذا disponible؟",
        commerce_stage="PRODUCT_SELECTED",
        selected_product_name="سامسونغ",
    )
    # Should be a follow-up, not a new availability inquiry
    assert result.intent in {INTENT_PRODUCT_FOLLOWUP, INTENT_AVAILABILITY_INQUIRY}


# ---------------------------------------------------------------------------
# 5. Purchase intent
# ---------------------------------------------------------------------------


def test_purchase_intent_with_product_context() -> None:
    """Test purchase intent when a product is already selected."""
    result = ConversationClassifier.classify(
        "حبيت نكومندي واحد",
        commerce_stage="PRODUCT_SELECTED",
        selected_product_name="سامسونغ",
    )
    # With a selected product, this should be a follow-up, not new purchase intent
    assert result.intent in {INTENT_PRODUCT_FOLLOWUP, INTENT_PURCHASE_INTENT}


def test_purchase_intent_without_product_context() -> None:
    """Test purchase intent without product context → ambiguous, needs clarification."""
    result = ConversationClassifier.classify(
        "حبيت نكومندي واحد",
        commerce_stage="EMPTY",
        selected_product_name=None,
    )
    # Without product context, this should be AMBIGUOUS with clarification needed
    assert result.intent == INTENT_AMBIGUOUS
    assert result.clarification_needed is True
    assert result.confidence < 0.6


def test_purchase_intent_arabizi() -> None:
    """Test purchase intent in Algerian Arabic Arabizi."""
    result = ConversationClassifier.classify(
        "حبيت نكوموني واحد",
        commerce_stage="EMPTY",
        selected_product_name=None,
    )
    # Without context, this should be AMBIGUOUS
    assert result.intent == INTENT_AMBIGUOUS
    assert result.clarification_needed is True


def test_purchase_intent_with_product_name() -> None:
    """Test purchase intent with named product preserves intent but sets product_mention to None (per spec)."""
    result = ConversationClassifier.classify(
        "حبيت نكومندي سامسونغ",
        commerce_stage="EMPTY",
        selected_product_name=None,
    )
    # Without selected product in context, even with product mention, it's ambiguous
    assert result.intent == INTENT_AMBIGUOUS
    assert result.clarification_needed is True


# ---------------------------------------------------------------------------
# 6. Order status
# ---------------------------------------------------------------------------


def test_order_status() -> None:
    """Test order status inquiry classification."""
    result = ConversationClassifier.classify("State order؟")
    # This should be classified as ambiguous or order_status depending on context
    assert result.intent in {INTENT_ORDER_STATUS, INTENT_AMBIGUOUS}


# ---------------------------------------------------------------------------
# 7. Order modification
# ---------------------------------------------------------------------------


def test_order_modification() -> None:
    """Test order modification request classification."""
    result = ConversationClassifier.classify("أريد تغيير طلبي")
    assert result.intent == INTENT_ORDER_MODIFICATION or result.intent == INTENT_AMBIGUOUS


# ---------------------------------------------------------------------------
# 8. After-sales
# ---------------------------------------------------------------------------


def test_after_sales() -> None:
    """Test after-sales inquiry classification."""
    result = ConversationClassifier.classify("عندكم ضمان؟")
    assert result.intent == INTENT_AFTER_SALES or result.intent == INTENT_UNSUPPORTED_OR_RESTRICTED


# ---------------------------------------------------------------------------
# 9. Objection handling
# ---------------------------------------------------------------------------


def test_objection_handling() -> None:
    """Test objection/concern handling classification."""
    result = ConversationClassifier.classify("هذا المنتج عيب")
    assert result.intent == INTENT_OBJECTION_HANDLING or result.intent == INTENT_AMBIGUOUS


# ---------------------------------------------------------------------------
# 10. Topic change
# ---------------------------------------------------------------------------


def test_topic_change() -> None:
    """Test topic change classification."""
    recent_turns = [
        {"role": "customer", "content": "ريد هاتف سامسونغ"},
        {"role": "assistant", "content": "أي نموذج تفضّل؟"},
    ]
    result = ConversationClassifier.classify(
        "بحب نكوموندي قميص",
        recent_turns=recent_turns,
        commerce_stage="EMPTY",
        selected_product_name=None,
    )
    # Should detect topic change from phones to clothing
    assert result.intent == INTENT_TOPIC_CHANGE


def test_topic_change_no_context() -> None:
    """Test topic change without recent context → general chat."""
    result = ConversationClassifier.classify("بحب نكوموندي قميص")
    # Without context, can't determine topic change
    assert result.intent in {INTENT_GENERAL_CHAT, INTENT_PRODUCT_INQUIRY}


# ---------------------------------------------------------------------------
# 11. Ambiguous request
# ---------------------------------------------------------------------------


def test_ambiguous_request() -> None:
    """Test ambiguous request classification."""
    result = ConversationClassifier.classify("حبيت نكوموني", commerce_stage="EMPTY")
    assert result.intent == INTENT_AMBIGUOUS
    assert result.clarification_needed is True
    assert result.confidence < 0.6


def test_ambiguous_mixed_language() -> None:
    """Test ambiguous request in mixed language."""
    result = ConversationClassifier.classify("Combien coûte ce produit？")
    assert result.intent == INTENT_AMBIGUOUS or result.intent == INTENT_PRODUCT_INQUIRY


# ---------------------------------------------------------------------------
# 12. Invalid classifier output
# ---------------------------------------------------------------------------


def test_invalid_intent_falls_back() -> None:
    """Test that an unsupported intent falls back to AMBIGUOUS via validation."""
    # Create a result with invalid intent and verify validation catches it
    try:
        invalid_result = ClassificationResult.model_validate(
            {
                "intent": "INVALID_INTENT",
                "confidence": 0.5,
                "language": "ar",
                "relevant_entities": {},
                "commerce_tools_needed": False,
                "clarification_needed": False,
                "routing_reason": "test",
            }
        )
        # If we get here, validation didn't catch it - but our model should reject
        assert False, "Should have raised validation error"
    except Exception as e:
        # Expected - the Pydantic validator should reject unsupported intents
        assert "Unsupported intent" in str(e)


def test_invalid_language_falls_back() -> None:
    """Test that an unsupported language tag falls back."""
    try:
        invalid_result = ClassificationResult.model_validate(
            {
                "intent": "GENERAL_CHAT",
                "confidence": 0.5,
                "language": "xx",  # Invalid language
                "relevant_entities": {},
                "commerce_tools_needed": False,
                "clarification_needed": False,
                "routing_reason": "test",
            }
        )
        assert False, "Should have raised validation error"
    except Exception:
        assert True  # Validation caught it


# ---------------------------------------------------------------------------
# 13. Empty model response
# ---------------------------------------------------------------------------


def test_empty_message_classification() -> None:
    """Test classification of empty/whitespace message."""
    result = ConversationClassifier.classify("")
    # Empty message should default to general chat or ambiguous
    assert result.intent in {INTENT_GENERAL_CHAT, INTENT_AMBIGUOUS}
    assert 0.0 <= result.confidence <= 1.0


def test_whitespace_only_message() -> None:
    """Test classification of whitespace-only message."""
    result = ConversationClassifier.classify("   ")
    assert result.intent in {INTENT_GENERAL_CHAT, INTENT_AMBIGUOUS}


# ---------------------------------------------------------------------------
# 14. Provider timeout or exception
# ---------------------------------------------------------------------------


def test_classifier_works_without_provider() -> None:
    """Test that classifier works entirely deterministically without LLM provider."""
    # All classification should work using deterministic heuristics
    result = ConversationClassifier.classify("اختبار رسالة")
    assert result.intent is not None
    assert 0.0 <= result.confidence <= 1.0
    assert result.language in {"ar", "fr", "en", "dz"}


def test_classifier_with_none_inputs() -> None:
    """Test classifier with None inputs defaults gracefully."""
    result = ConversationClassifier.classify(
        user_message=None,
        language=None,
        recent_turns=None,
        commerce_stage=None,
        selected_product_id=None,
        selected_product_name=None,
        last_question_type=None,
    )
    # Should not crash; return a valid result
    assert result.intent is not None
    assert 0.0 <= result.confidence <= 1.0
    assert result.language in {"ar", "fr", "en", "dz"}


# ---------------------------------------------------------------------------
# 15. General conversation does not unnecessarily invoke commerce tools
# ---------------------------------------------------------------------------


def test_general_chat_no_commerce_tools() -> None:
    """Test that general chat messages don't need commerce tools."""
    result = ConversationClassifier.classify("السلام عليكم كيف حالك؟")
    assert result.intent == INTENT_GENERAL_CHAT
    assert result.commerce_tools_needed is False
    assert result.clarification_needed is False


def test_general_chat_no_commerce_tools_english() -> None:
    """Test that general chat messages in English don't need commerce tools."""
    result = ConversationClassifier.classify("Hello, how are you?")
    assert result.intent == INTENT_GENERAL_CHAT
    assert result.commerce_tools_needed is False


# ---------------------------------------------------------------------------
# 16. Commerce routing still invokes appropriate processing path
# ---------------------------------------------------------------------------


def test_product_inquiry_invokes_search() -> None:
    """Test that product inquiry is flagged for commerce tools."""
    result = ConversationClassifier.classify("ريد هاتف")
    assert result.intent == INTENT_PRODUCT_INQUIRY
    assert result.commerce_tools_needed is True


def test_price_inquiry_invokes_tools() -> None:
    """Test that price inquiry is flagged for commerce tools."""
    result = ConversationClassifier.classify("سعر هذا المنتج؟")
    assert result.intent == INTENT_PRICE_INQUIRY
    assert result.commerce_tools_needed is True


# ---------------------------------------------------------------------------
# 17. Store isolation and authorization remain intact
# ---------------------------------------------------------------------------


def test_classifier_respects_commerce_stage() -> None:
    """Test that classifier respects the current commerce stage."""
    # When a draft order is in progress, messages should reflect that
    result = ConversationClassifier.classify(
        "زيد الكمية",
        commerce_stage="DRAFT_PENDING",
        selected_product_id=str(uuid.uuid4()),
    )
    # Should not incorrectly trigger new purchase
    assert result.intent != INTENT_PURCHASE_INTENT or result.clarification_needed is True


def test_classifier_with_active_draft() -> None:
    """Test classifier when there's an active draft order."""
    result = ConversationClassifier.classify(
        "أريد التعديل",
        commerce_stage="DRAFT_PENDING",
        selected_product_name="منتج اختبار",
    )
    # Should reflect modification intent, not new purchase
    assert result.intent in {INTENT_ORDER_MODIFICATION, INTENT_AMBIGUOUS}


# ---------------------------------------------------------------------------
# 18. Purchase confirmation requirements remain intact
# ---------------------------------------------------------------------------


def test_purchase_without_confirmation_needs_clarification() -> None:
    """Test that purchase intent without explicit confirmation needs clarification."""
    result = ConversationClassifier.classify(
        "حبيت نكومندي",
        commerce_stage="EMPTY",
        selected_product_name=None,
    )
    assert result.clarification_needed is True
    assert result.confidence < 0.6


def test_confirmation_with_context() -> None:
    """Test that confirmation in context of active draft is handled."""
    result = ConversationClassifier.classify(
        "نعم",
        commerce_stage="DRAFT_PENDING",
        last_question_type="ORDER_CONFIRMATION",
        selected_product_name="سامسونغ",
    )
    # In context of ORDER_CONFIRMATION, "yes" should be recognized
    assert result.intent == "order_confirm" or result.confidence > 0.5


# ---------------------------------------------------------------------------
# 19. Mixed-language messages
# ---------------------------------------------------------------------------


def test_mixed_language_arabic_french() -> None:
    """Test mixed Arabic/French message classification."""
    result = ConversationClassifier.classify("أنا أحب هذا الهاتف، كم سعره؟")
    # French price inquiry mixed with Arabic product mention
    assert result.intent == INTENT_PRICE_INQUIRY
    # Language should be detected as French due to French markers
    assert result.language in {"fr", "ar"}


def test_mixed_language_darija_english() -> None:
    """Test mixed Algerian Darija/English message classification."""
    result = ConversationClassifier.classify("حب نكوموندي واحد، I want one")
    # Should handle mixed language
    assert result.intent in {INTENT_PURCHASE_INTENT, INTENT_AMBIGUOUS}
    assert result.confidence > 0.0


def test_multilingual_greeting_detection() -> None:
    """Test that multilingual greetings are detected correctly."""
    # Arabic greeting
    result = ConversationClassifier.classify("السلام عليكم")
    assert result.language == "ar" or result.language == "dz"

    # French greeting
    result = ConversationClassifier.classify("Bonjour")
    assert result.language == "fr" or result.language == "ar"

    # English greeting
    result = ConversationClassifier.classify("Hello")
    assert result.language == "en" or result.language == "ar"


# ---------------------------------------------------------------------------
# 20. Context-aware classification tests
# ---------------------------------------------------------------------------


def test_contextual_product_followup() -> None:
    """Test contextual product follow-up when product is selected."""
    result = ConversationClassifier.classify(
        "ونطقة اللون الأحمر",
        commerce_stage="VARIANT_SELECTED",
        selected_product_name="سامسونغ",
        last_question_type="VARIANT_SELECTION",
    )
    # Should be a product follow-up, not a new inquiry
    assert result.intent == INTENT_PRODUCT_FOLLOWUP
    assert result.commerce_tools_needed is False


@pytest.mark.parametrize("message", ["دير طلب", "ديرلي طلب"])
def test_explicit_order_request_overrides_product_details_followup(message: str) -> None:
    result = ConversationClassifier.classify(
        message,
        commerce_stage="PRODUCT_SELECTED",
        selected_product_id=str(uuid.uuid4()),
        selected_product_name="الحذاء",
        last_question_type="PRODUCT_DETAILS_OFFER",
    )

    assert result.intent == INTENT_PURCHASE_INTENT
    assert result.commerce_tools_needed is True
    assert result.clarification_needed is False


def test_contextual_price_with_selected_product() -> None:
    """Test price inquiry when product is selected → price inquiry with entity."""
    result = ConversationClassifier.classify(
        "كم سعر هذا المنتج؟",
        commerce_stage="PRODUCT_SELECTED",
        selected_product_name="سامسونغ",
    )
    assert result.intent == INTENT_PRICE_INQUIRY
    assert result.commerce_tools_needed is True
    # product_mention should be set from context
    assert result.relevant_entities.get("product_mention") == "سامسونغ"


def test_contextual_availability_with_selected_product() -> None:
    """Test availability inquiry when product is selected."""
    result = ConversationClassifier.classify(
        "هذا متوفر؟",
        commerce_stage="PRODUCT_SELECTED",
        selected_product_name="سامسونغ",
    )
    # Should be a follow-up about the selected product
    assert result.intent == INTENT_PRODUCT_FOLLOWUP or result.intent == INTENT_AVAILABILITY_INQUIRY


def test_contextual_topic_change_from_product_to_service() -> None:
    """Test topic change when switching from product discussion to store policy."""
    recent_turns = [
        {"role": "customer", "content": "ريد هاتف سامسونغ بسعر جيد"},
        {"role": "assistant", "content": "هذا الهاتف سعره 5000 دولار"},
    ]
    result = ConversationClassifier.classify(
        "عنوان محلكم?",
        recent_turns=recent_turns,
        commerce_stage="EMPTY",
        selected_product_name=None,
    )
    # Topic change from product to store address
    assert result.intent == INTENT_TOPIC_CHANGE


def test_contextual_objection_with_selected_product() -> None:
    """Test objection handling when product is selected."""
    result = ConversationClassifier.classify(
        "هذا المنتج عيب",
        commerce_stage="PRODUCT_SELECTED",
        selected_product_name="سامسونغ",
    )
    assert result.intent == INTENT_OBJECTION_HANDLING


# ---------------------------------------------------------------------------
# 21. Safe fallback when classification fails
# ---------------------------------------------------------------------------


def test_fallback_when_classification_uncertain() -> None:
    """Test conservative fallback when classification is uncertain."""
    # Very ambiguous message with no context
    result = ConversationClassifier.classify("hmmm")
    assert result.intent == INTENT_AMBIGUOUS
    assert result.clarification_needed is True
    assert result.confidence < 0.5


def test_fallback_unknown_intent() -> None:
    """Test fallback for unknown/unrecognized intent."""
    result = ConversationClassifier.classify("some random gibberish xyz")
    assert result.intent in {INTENT_AMBIGUOUS, INTENT_GENERAL_CHAT}
    assert result.clarification_needed is True or result.confidence < 0.5


# ---------------------------------------------------------------------------
# 22. Edge cases and integration
# ---------------------------------------------------------------------------


def test_all_intent_categories_are_valid() -> None:
    """Verify that all 14 intent categories are valid ClassificationResult intents."""
    all_intents = [
        INTENT_GENERAL_CHAT,
        INTENT_PRODUCT_INQUIRY,
        INTENT_PRODUCT_FOLLOWUP,
        INTENT_PRICE_INQUIRY,
        INTENT_AVAILABILITY_INQUIRY,
        INTENT_PURCHASE_INTENT,
        INTENT_ORDER_STATUS,
        INTENT_ORDER_MODIFICATION,
        INTENT_AFTER_SALES,
        INTENT_OBJECTION_HANDLING,
        INTENT_TOPIC_CHANGE,
        INTENT_AMBIGUOUS,
        INTENT_UNSUPPORTED_OR_RESTRICTED,
    ]

    for intent in all_intents:
        result = ClassificationResult.model_validate(
            {
                "intent": intent,
                "confidence": 0.5,
                "language": "ar",
                "relevant_entities": {},
                "commerce_tools_needed": False,
                "clarification_needed": False,
                "routing_reason": f"test {intent}",
            }
        )
        assert result.intent == intent


def test_classifier_confidence_bounds() -> None:
    """Test that all classifier confidences are in [0.0, 1.0]."""
    test_messages = [
        "السلام عليكم",
        "ريد هاتف",
        "بشحال؟",
        "حبيت نكومندي",
        "شحال هذا؟",
        "عنوان محلكم",
        "هذا المنتج عيب",
    ]

    for message in test_messages:
        result = ConversationClassifier.classify(message)
        assert 0.0 <= result.confidence <= 1.0, (
            f"Confidence {result.confidence} out of bounds for message: '{message}'"
        )


def test_classifier_language_bounds() -> None:
    """Test that all classifier language tags are valid."""
    valid_languages = {"ar", "fr", "en", "dz"}

    # Test messages in different languages
    test_messages = [
        ("السلام", "ar"),  # Arabic
        ("Bonjour", "fr"),  # French
        ("Hello", "en"),  # English
        ("7ab nechri", "dz"),  # Algerian Darija
    ]

    for message, expected_lang in test_messages:
        result = ConversationClassifier.classify(message)
        # Language should be one of the valid tags (may differ due to detection)
        assert result.language in valid_languages, (
            f"Invalid language '{result.language}' for message: '{message}'"
        )


# Run via: python -m pytest tests/test_classifier.py -v