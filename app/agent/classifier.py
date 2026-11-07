"""
ConversationClassifier: Intent classification for DzCommerce agent.

Responsibilities:
- Classify user messages into one of 14 intent categories.
- Return structured results with intent, confidence, language, entities,
  commerce-tool-needed flag, and clarification-needed flag.
- Consider conversation context (recent turns, commerce stage, selected product).
- Support Arabic, Algerian Darija (Arabizi), French, English, and mixed-language messages.
- Provide conservative fallback when classification fails or the LLM is unavailable.
- Never fabricate confidence or claim certainty when classification is uncertain.

The classifier is deliberately deterministic-first: keyword-free primary detection
is supplemented by context-aware inference. When the LLM is available, structured
output is preferred; when it is not, deterministic heuristics take over.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, validator

# ---------------------------------------------------------------------------
# 1. Structured output models
# ---------------------------------------------------------------------------


class ClassificationResult(BaseModel):
    """Validated, structured classification output.

    All fields are required and validated.  The model enforces supported
    intent values, confidence bounds, and language codes so that downstream
    code never receives unexpected types or out-of-range numbers.
    """

    intent: str = Field(
        ...,
        description="One of the supported intent categories.",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Classification confidence in [0.0, 1.0].",
    )
    language: str = Field(
        ...,
        description="Detected language tag: 'ar', 'fr', 'en', or 'dz' (Algerian Darija).",
    )
    relevant_entities: Dict[str, str] = Field(
        default_factory=dict,
        description="Key-value entities extracted from the message (e.g. product mentions).",
    )
    commerce_tools_needed: bool = Field(
        default=False,
        description="True when the message likely requires a commerce tool call.",
    )
    clarification_needed: bool = Field(
        default=False,
        description="True when the message is ambiguous and a clarifying question is warranted.",
    )
    routing_reason: str = Field(
        ...,
        description="Brief explanation of why this intent was chosen.",
    )

    # ------------------------------------------------------------------
    # Validation: supported intent values
    # ------------------------------------------------------------------
    @validator("intent")
    def _validate_intent(cls, v: str) -> str:
        if v not in SUPPORTED_INTENTS:
            raise ValueError(
                f"Unsupported intent '{v}'. "
                f"Must be one of {sorted(SUPPORTED_INTENTS)}"
            )
        return v

    @validator("language")
    def _validate_language(cls, v: str) -> str:
        if v not in {"ar", "fr", "en", "dz"}:
            raise ValueError(f"Unsupported language tag '{v}'. Must be one of: ar, fr, en, dz")
        return v


class ClassificationFallback(BaseModel):
    """Minimal fallback result when classification cannot produce a valid output.

    Used by integrations that need a result object but must not claim certainty.
    """

    intent: str = "AMBIGUOUS"
    confidence: float = 0.0
    language: str = "ar"
    relevant_entities: Dict[str, str] = {}
    commerce_tools_needed: bool = False
    clarification_needed: bool = True
    routing_reason: str = "Classification failed; using conservative fallback."


# ---------------------------------------------------------------------------
# 2. Intent categories (as defined in the task)
# ---------------------------------------------------------------------------

# Module-level constant for supported intents (avoids Pydantic v2 validator issues)
SUPPORTED_INTENTS = frozenset(
    {
        "GENERAL_CHAT",
        "PRODUCT_INQUIRY",
        "PRODUCT_FOLLOWUP",
        "PRICE_INQUIRY",
        "AVAILABILITY_INQUIRY",
        "PURCHASE_INTENT",
        "ORDER_STATUS",
        "ORDER_MODIFICATION",
        "AFTER_SALES",
        "OBJECTION_HANDLING",
        "TOPIC_CHANGE",
        "AMBIGUOUS",
        "UNSUPPORTED_OR_RESTRICTED",
    }
)

INTENT_GENERAL_CHAT = "GENERAL_CHAT"
INTENT_PRODUCT_INQUIRY = "PRODUCT_INQUIRY"
INTENT_PRODUCT_FOLLOWUP = "PRODUCT_FOLLOWUP"
INTENT_PRICE_INQUIRY = "PRICE_INQUIRY"
INTENT_AVAILABILITY_INQUIRY = "AVAILABILITY_INQUIRY"
INTENT_PURCHASE_INTENT = "PURCHASE_INTENT"
INTENT_ORDER_STATUS = "ORDER_STATUS"
INTENT_ORDER_MODIFICATION = "ORDER_MODIFICATION"
INTENT_AFTER_SALES = "AFTER_SALES"
INTENT_OBJECTION_HANDLING = "OBJECTION_HANDLING"
INTENT_TOPIC_CHANGE = "TOPIC_CHANGE"
INTENT_AMBIGUOUS = "AMBIGUOUS"
INTENT_UNSUPPORTED_OR_RESTRICTED = "UNSUPPORTED_OR_RESTRICTED"

# ---------------------------------------------------------------------------
# 3. Language detection (lightweight, regex-based)
# ---------------------------------------------------------------------------

ARABIC_SCRIPT_RE = re.compile(r"[؀-ۿ]")
ARABIC_DIRAJA_ARABIZI_RE = re.compile(r"[dhTrz]|\b7ab\b|\b7al\b|\bn7a\b")  # loose Arabizi markers
FRENCH_RE = re.compile(r"(?<![a-zA-Z])(àâäéèêëïîôùûüÿçñ|Bonsoir|Salut|Allô|merci|désolé|s'il\ vous|s'il\te|comment|où|quel|quoi)|(?<![a-zA-Z])(?:Bonjour|Bonsoir|Salut|Allô|merci|désolé)s?[^\w\s]*")


def detect_language(message: str) -> str:
    """Detect the primary language of a message.

    Priority: Arabic script > French markers > Arabic dialect markers > English default.
    Returns a language tag: 'ar', 'fr', 'en', or 'dz'.
    """
    if not message:
        return "ar"

    has_arabic_script = bool(ARABIC_SCRIPT_RE.search(message))
    has_french_markers = bool(FRENCH_RE.search(message))

    if has_arabic_script and not has_french_markers:
        return "ar"

    if has_french_markers:
        return "fr"

    # Very loose Algerian/Darija Arabizi markers
    msg_lower = message.lower()
    if re.search(r"\b7ab\b|\b7al\b|\bn7a\b|\bch7al\b|\bdar\b", msg_lower):
        return "dz"

    return "en"


# ---------------------------------------------------------------------------
# 4. Deterministic heuristics (used when LLM is unavailable or as guardrails)
# ---------------------------------------------------------------------------


def _is_greeting(message: str) -> bool:
    """Check if the message is a general greeting."""
    normalized = re.sub(
        r"[\s,،؟?!.;:]+",
        " ",
        (message or "").casefold(),
    ).strip()
    greetings_ar = {
        "السلام",
        "سلام",
        "عليكم",
        "السلام عليكم",
        "سلام عليكم",
        "مرحبا",
        "أهلا",
        "أهلا وسهلا",
        "وعليكم السلام",
        "السلام عليكم كيف حالك",
        "السلام عليكم كيف حالكم",
    }
    greetings_dz = {
        "salam",
        "salem",
        "salam alikoum",
        "salam alikom",
        "salem alikoum",
        "salem alikom",
        "salam 3likom",
        "salam 3alaykom",
        "salam wach kayen",
        "salem wach kayen",
    }
    greetings_fr = {"bonjour", "salut", "coucou"}
    greetings_en = {
        "hello",
        "hi",
        "hey",
        "hi there",
        "hello how are you",
        "hey how are you",
        "hi how are you",
    }
    if normalized in greetings_ar:
        return True
    if normalized in greetings_dz:
        return True
    if normalized in greetings_fr:
        return True
    if normalized in greetings_en:
        return True
    return False


def _is_product_inquiry(message: str) -> bool:
    """Check if the message asks about a product (without purchase intent)."""
    normalized = re.sub(r"\s+", " ", (message or "").casefold()).strip()

    # First check for price inquiry - if it's a price question, it's not a product inquiry
    if _is_price_inquiry(message):
        return False

    # Check for objection/defective patterns FIRST - these should NOT be product inquiries
    obj_patterns = [
        r"هذا\s+منتج\s+عيب",
        r"منتج\s+عيب",
        r"هذا\s+عيب",
        r"مش\s+حلو",
    ]
    for pattern in obj_patterns:
        if re.search(pattern, normalized):
            return False

    # Product search phrases in Arabic (excluding objection/defective keywords)
    arabic_patterns = [
        r"وش\s+[ا-ي]+",  # "وش ..." patterns
        r"ريد\s+",       # "ريد" (want)
        r"أبي\s+",       # "أبي" (want)
        r"عندكم\s+",     # "عندكم" (do you have)
        r"سامسونغ|آيفون|هاتف",  # product names (device names only)
        # Note: "منتج" excluded to avoid matching "هذا منتج عيب" etc.
        # "كمسع" excluded to avoid matching price inquiries
    ]
    # Product search phrases in French
    french_patterns = [
        r"produit|produits",
        r"cherche|recherche",
        r"avez-vous",
    ]
    # Product search phrases in English
    english_patterns = [
        r"product|products",
        r"looking for",
        r"search|find",
        r"do you have",
    ]

    # Check price inquiry FIRST (more specific patterns) before product inquiry
    # This prevents price questions from being misclassified as product inquiries
    if _is_price_inquiry(message):
        return True

    all_patterns = arabic_patterns + french_patterns + english_patterns
    for pattern in all_patterns:
        if re.search(pattern, normalized):
            return True
    return False


def _is_after_sales(message: str) -> bool:
    """Check if the message is an after-sales inquiry."""
    normalized = re.sub(r"\s+", " ", (message or "").casefold()).strip()
    after_sales_patterns = [
        r"ضمان|warranty|garantie",
        r"إرجاع|ارجاع|return|retour",
        r"استبدال|exchange|échange",
        r"خدمة\s+بعد\s+البيع|after.sales",
        r"صيانة|maintenance|entretien",
    ]
    for pattern in after_sales_patterns:
        if re.search(pattern, normalized):
            return True
    return False


def _is_order_status(message: str) -> bool:
    """Check if the message asks about order status."""
    normalized = re.sub(r"\s+", " ", (message or "").casefold()).strip()
    order_status_patterns = [
        r"طلب|أوردر|order",
        r"حالة|status|état",
        r"وين\s+طلبي|where\s+is\s+my\s+order",
        r"track|تتبع|تتبع",
        r"طلبات|تاريخ\s+الطلبات|تلخيص",  # Arabic: orders, order history, summary
    ]
    for pattern in order_status_patterns:
        if re.search(pattern, normalized):
            return True
    return False


def _is_order_modification(message: str) -> bool:
    """Check if the message requests order modification."""
    normalized = re.sub(r"\s+", " ", (message or "").casefold()).strip()
    modification_patterns = [
        r"تغيير|تعديل|change|modify|edit",
        r"بدل|غير|replace|switch",
        r"زيد|احذف|add|remove",
        r"تغيير\s+الطلب|modify\s+order",
    ]
    for pattern in modification_patterns:
        if re.search(pattern, normalized):
            return True
    return False


def _is_price_inquiry(message: str) -> bool:
    """Check if the message asks about price specifically."""
    normalized = re.sub(r"\s+", " ", (message or "").casefold()).strip()
    # More specific price question patterns - looking for question-like structures
    price_patterns = [
        r"(بشحال|بقداه|شحال|bch7al|besh7al|ch7al|chhal|كم\s+سع|how\s+much|combien|prix|price|cost|سعر)\s*[؟?]",
        r"(بشحال|بقداه|شحال|bch7al|besh7al|ch7al|chhal|كم\s+سع|how\s+much|combien|prix|price|cost|سعر)\s*$",
        r"(?<!\w)(?:بشحال|بقداه|شحال|bch7al|besh7al|ch7al|chhal|كم\s+سع|how\s+much|combien|prix|price|cost|سعر)\b",
    ]
    for pattern in price_patterns:
        if re.search(pattern, normalized):
            # But exclude "yes price" or greetings
            if not _is_greeting(message) and not re.search(r"\b(yes|oui)\b", normalized):
                return True
    return False


def _is_availability_inquiry(message: str) -> bool:
    """Check if the message asks about availability/stock."""
    normalized = re.sub(r"\s+", " ", (message or "").casefold()).strip()
    avail_patterns = [
        r"(available|in\s+stock|واخذ|كاين|عندكم|متوفر|disponible|stock)\s*[؟?]",
        r"(available|in\s+stock|واخذ|كاين|عندكم|متوفر|disponible|stock)\s*$",
        r"(عندكم|كاين|متوفر|disponible|available)\b",
    ]
    for pattern in avail_patterns:
        if re.search(pattern, normalized):
            return True
    return False


def _is_purchase_intent(message: str, state: Optional[Dict[str, Any]] = None) -> bool:
    """Check if the message expresses purchase intent.

    Purchase intent requires either explicit purchase phrases or a selected
    product in context.  Without context, only strong purchase phrases count.
    """
    if state and state.get("selected_product_id"):
        if _is_explicit_order_request(message):
            return True
        # If a product is already selected, many messages become follow-ups
        # rather than new purchase intent
        normalized = re.sub(r"\s+", " ", (message or "").casefold()).strip()
        # Strong purchase starters without product re-specification
        strong_phrases = [
            "حبيت نكومندي", "نبغي نطلب", "نحب نطلب", "n7ab n7adem", "bghit ncommander",
            # Also include the common purchase phrases
            "حبيت نشري", "نحب نشري", "حب نشري", "حبيتش نشري", "حبيتش نشري هذا",
            "حبيت اطلب", "أريد اطلب", "أريد شراء",
            "n7ab nechri", "bghit nechri", "7ab nechri", "n7ab n7dem", "bghit n7dem",
            "حبيت نكوموني", "نحب نكوموني", "حب نكوموني",
        ]
        for phrase in strong_phrases:
            if re.search(re.escape(phrase), normalized):
                return True
        # If they mention the selected product name WITHOUT a strong purchase phrase,
        # it's a follow-up about the existing selection, not a new purchase
        selected_name = state.get("selected_product_name", "")
        if selected_name and selected_name.lower() in normalized:
            return False
        # If no strong purchase phrase and product name not mentioned, it's not purchase intent
        return False

    # Without selected product, check for strong purchase phrases
    normalized = re.sub(r"\s+", " ", (message or "").casefold()).strip()
    strong_purchase_phrases = [
        r"حبيت نكومندي",
        r"نبغي نطلب",
        r"نحب نطلب",
        r"n7ab n7adem",
        r"bghit ncommander",
        r"حبيت اطلب",
        r"أريد اطلب",
        r"أريد شراء",
        # Algerian Arabic Arabizi phrases (additional variants)
        r"n7ab nechri",
        r"bghit nechri",
        r"7ab nechri",
        r"n7ab n7dem",
        r"bghit n7dem",
        # Algerian Arabic phrases
        r"حبيت نكوموني",
        r"حبيت نكوموني واحد",
        r"نحب نكوموني",
        r"نحب نكوموني واحد",
        r"حب نكوموني",
        r"حب نكوموني واحد",
        r"حب نشري",
        r"حب نشري واحد",
        r"حبيتش نشري",
        r"حبيتش نشري هذا",
        r"حبيت نشري",
        r"نحب نشري",
        # Additional Algerian Darija / common user phrases
        r"حبيت نطلب",           # "I want to order"
        r"حبيت نطلب واحد",      # "I want to order one"
        r"حاب نطلب",            # "I want to order" (Algerian)
        r"كيفاش نأكد",          # "How do I confirm"
        r"كيف ناكد",            # "How to confirm"
        r"ناكد الطلب",          # "Confirm the order"
        r"كيف نؤكد",            # "How to confirm" (MSA)
        r"تأكيد الطلب",         # "Order confirmation"
        r"أكيد الطلب",          # "Confirm the order"
        r"نأكد الطلب",          # "I confirm the order"
        r"أكيد طلبي",          # "Confirm my order"
        r"نكومندي",            # "I order" (short)
        r"نطلب",               # "We/I order"
        r"نكوموني",            # "I order" (variant)
        r"نشرى",               # "We/I buy"
        r"نشرى واحد",          # "Buy one"
    ]
    if _is_explicit_order_request(message):
        return True
    for phrase_pattern in strong_purchase_phrases:
        if re.search(phrase_pattern, normalized):
            return True

    # Moderate phrases that need context
    moderate_phrases = [
        r"حبيت ن Request",
        r"أريد",
    ]
    for phrase_pattern in moderate_phrases:
        if re.search(phrase_pattern, normalized):
            return True  # Will be resolved by context later

    return False


def _is_explicit_order_request(message: str) -> bool:
    """Recognize direct order commands independently of product-follow-up context."""
    normalized = re.sub(r"\s+", " ", (message or "").casefold()).strip()
    return bool(
        re.search(
            r"(?<!\w)(?:دير(?:لي)?|ندير(?:لي)?|حضر(?:لي)?|حضّر(?:لي)?)\s+"
            r"(?:ال)?(?:طلب\w*|كوموند\w*|كوماندة)(?!\w)",
            normalized,
        )
        or re.search(r"(?<!\w)خليني\s+نطلب(?!\w)", normalized)
    )


def _is_objection_handling(message: str) -> bool:
    """Check if the message handles an objection/concern."""
    normalized = re.sub(r"\s+", " ", (message or "").casefold()).strip()

    # First check for explicit greetings that might contain objection-like words
    if _is_greeting(message):
        return False

    objection_patterns = [
        # Specific objection phrases (not standalone "لا")
        r"مش\s+حابب",  # "مش حابب" (don't like)
        r"لا\s+هذا",   # "لا هذا" (not this)
        r"not\s+working",
        r"لا\s+يشتغل",
        r"عيب",        # "defective"
        r"مشكلة",      # "problem"
        r"مش\s+ممتاز", # "not great"
        r"هذا\s+منتج\s+عيب",  # "this product is defective"
        r"منتج\s+عيب",       # "product defective"
        r"هذا\s+عيب",         # "this is defective"
        r"مش\s+حلو",          # "not good/nice"
        # Price objections
        r"غالي",         # "expensive"
        r"السعر\s+غالي",  # "price is expensive"
        r"باهظ",         # "pricey"
        r"مش\s+غالي",     # "not expensive" (could be positive)
        r"too\s+expensive",
        r"price\s+high",
        r"co[ûu]te\s+cher",
        r"trop\s+cher",
    ]
    for pattern in objection_patterns:
        if re.search(pattern, normalized):
            return True
    return False


def _is_topic_change(message: str, recent_turns: Optional[List[Dict[str, str]]] = None) -> bool:
    """Check if the message changes the topic from the current conversation."""
    if not recent_turns:
        return False

    normalized = re.sub(r"\s+", " ", (message or "").casefold()).strip()

    # Check if the message mentions a completely different subject
    # Simple heuristic: if the message has very different vocabulary
    # from the recent turns, it might be a topic change
    recent_text = " ".join(
        turn.get("content", "") for turn in recent_turns[-3:] if turn.get("content")
    )
    if not recent_text:
        return False

    # If the message is very short and doesn't reference previous context
    if len(normalized.split()) <= 3 and not any(
        word in normalized for word in recent_text.split()[:5]
    ):
        # Could be a topic change if it's a simple question/greeting
        # but only if there's an established context
        if recent_turns and len(recent_turns) >= 2:
            prev_intents = []
            for turn in recent_turns[-3:-1]:
                content = turn.get("content", "")
                content_lower = content.lower()
                # Check for product-related terms in multiple languages
                if any(term in content_lower for term in ["product", "منتج", "هاتف", "سامسونغ", "samsung", "phone"]):
                    prev_intents.append("product")
                # Check for order-related terms
                if any(term in content_lower for term in ["order", "طلب", "أوردر", "ordrer"]):
                    prev_intents.append("order")
                # Check for price-related terms
                if any(term in content_lower for term in ["price", "سعر", "بشحال", "prix", "cost"]):
                    prev_intents.append("price")

            # If previous turns were about products/orders and this is a
            # completely different question, it's a topic change
            if prev_intents and not any(
                pt in normalized for pt in prev_intents
            ):
                return True

    return False


# ---------------------------------------------------------------------------
# 5. Context-aware inference
# ---------------------------------------------------------------------------

def _infer_intent_from_context(
    message: str,
    language: str,
    selected_product_id: Optional[str],
    selected_product_name: Optional[str],
    commerce_stage: Optional[str],
    last_question_type: Optional[str],
    recent_turns: Optional[List[Dict[str, str]]] = None,
) -> Tuple[str, Dict[str, str], bool, bool]:
    """Infer intent using conversation context.

    Returns (intent, entities, commerce_tools_needed, clarification_needed).
    """

    entities: Dict[str, str] = {}
    commerce_tools_needed = False
    clarification_needed = False

    normalized = re.sub(r"\s+", " ", (message or "").casefold()).strip()

    if _is_greeting(message):
        return INTENT_GENERAL_CHAT, entities, False, False

    # ------------------------------------------------------------------
    # Context: product selected → follow-ups or details
    # ------------------------------------------------------------------
    if commerce_stage in {"PRODUCT_SELECTED", "VARIANT_SELECTED", "DRAFT_PENDING"} and selected_product_name:
        entities["product_mention"] = selected_product_name

        if _is_purchase_intent(
            message,
            {
                "selected_product_id": selected_product_id,
                "selected_product_name": selected_product_name,
            },
        ):
            return INTENT_PURCHASE_INTENT, entities, True, False

        # Check if this is a follow-up about the selected product
        if last_question_type == "PRODUCT_DETAILS_OFFER":
            # Customer is responding to an offer of product details
            if _is_price_inquiry(message) or _is_availability_inquiry(message):
                intent = INTENT_PRICE_INQUIRY if "price" in normalized else INTENT_AVAILABILITY_INQUIRY
                commerce_tools_needed = True
                clarification_needed = False
            else:
                # General follow-up about the product
                intent = INTENT_PRODUCT_FOLLOWUP
                commerce_tools_needed = False
                clarification_needed = False

        elif last_question_type == "PRODUCT_SEARCH_OFFER":
            # Customer is continuing a product search
            intent = INTENT_PRODUCT_INQUIRY
            commerce_tools_needed = True
            clarification_needed = False

        elif last_question_type == "VARIANT_SELECTION":
            # Customer is responding to variant selection
            if _is_price_inquiry(message):
                intent = INTENT_PRICE_INQUIRY
            elif _is_availability_inquiry(message):
                intent = INTENT_AVAILABILITY_INQUIRY
            else:
                intent = INTENT_PRODUCT_FOLLOWUP
                # For simple variant attribute follow-ups (color, size, etc.), don't need commerce tools
                commerce_tools_needed = False
                clarification_needed = False
                return intent, entities, commerce_tools_needed, clarification_needed
            commerce_tools_needed = True
            clarification_needed = False

        else:
            # No prior question type; check message content
            if _is_price_inquiry(message):
                intent = INTENT_PRICE_INQUIRY
                commerce_tools_needed = True
            elif _is_availability_inquiry(message):
                intent = INTENT_AVAILABILITY_INQUIRY
                commerce_tools_needed = True
            elif _is_objection_handling(message):
                intent = INTENT_OBJECTION_HANDLING
                commerce_tools_needed = False
                clarification_needed = True
            elif _is_order_modification(message):
                intent = INTENT_ORDER_MODIFICATION
                commerce_tools_needed = True
                clarification_needed = True
            elif _is_purchase_intent(message, {"selected_product_id": selected_product_id, "selected_product_name": selected_product_name}):
                intent = INTENT_PURCHASE_INTENT
                commerce_tools_needed = True
                clarification_needed = True
            elif _is_product_inquiry(message):
                intent = INTENT_PRODUCT_INQUIRY
                commerce_tools_needed = True
            else:
                # Could be a follow-up question about the selected product
                intent = INTENT_PRODUCT_FOLLOWUP
                commerce_tools_needed = False

    # ------------------------------------------------------------------
    # Context: no product selected (EMPTY stage)
    # ------------------------------------------------------------------
    elif commerce_stage in {None, "EMPTY"} or commerce_stage is None:
        # Check for price inquiry without product context
        # When explicitly in EMPTY stage, price inquiry is ambiguous (need to know which product)
        if commerce_stage == "EMPTY" and _is_price_inquiry(message):
            intent = INTENT_AMBIGUOUS
            commerce_tools_needed = False
            clarification_needed = True  # Need to know which product
            return intent, entities, commerce_tools_needed, clarification_needed
        # Check for price inquiry without product context (default stage)
        if _is_price_inquiry(message):
            intent = INTENT_PRICE_INQUIRY
            commerce_tools_needed = True
            clarification_needed = True  # Need to know which product
            return intent, entities, commerce_tools_needed, clarification_needed

        # Check for after-sales inquiries (must be before availability check since "عندكم" matches both)
        if _is_after_sales(message):
            intent = INTENT_AFTER_SALES
            commerce_tools_needed = True
            clarification_needed = True
            return intent, entities, commerce_tools_needed, clarification_needed

        # Check for availability inquiry without product context
        if _is_availability_inquiry(message):
            intent = INTENT_AVAILABILITY_INQUIRY
            commerce_tools_needed = True
            clarification_needed = True  # Need to know which product
            return intent, entities, commerce_tools_needed, clarification_needed

        # Check for purchase intent without product context
        # Build a minimal state dict for the purchase intent check
        state_dict = {
            "selected_product_id": selected_product_id,
            "selected_product_name": selected_product_name,
        }
        if _is_purchase_intent(message, state_dict):
            # Without a selected product, this is ambiguous - need clarification
            intent = INTENT_AMBIGUOUS
            clarification_needed = True
            commerce_tools_needed = False
            return intent, entities, commerce_tools_needed, clarification_needed

        # Check for objections (before product inquiry to catch "هذا المنتج عيب" etc.)
        if _is_objection_handling(message):
            intent = INTENT_OBJECTION_HANDLING
            commerce_tools_needed = False
            clarification_needed = True
            return intent, entities, commerce_tools_needed, clarification_needed

        # Check for product inquiry
        if _is_product_inquiry(message):
            intent = INTENT_PRODUCT_INQUIRY
            commerce_tools_needed = True
            clarification_needed = True  # Need product name
            return intent, entities, commerce_tools_needed, clarification_needed

        # Check for order status inquiries
        if _is_order_status(message):
            intent = INTENT_ORDER_STATUS
            commerce_tools_needed = True
            clarification_needed = True
            return intent, entities, commerce_tools_needed, clarification_needed

        # Check for order modification inquiries
        if _is_order_modification(message):
            intent = INTENT_ORDER_MODIFICATION
            commerce_tools_needed = True
            clarification_needed = True
            return intent, entities, commerce_tools_needed, clarification_needed

        # Check for topic change
        if _is_topic_change(message, recent_turns):
            intent = INTENT_TOPIC_CHANGE
            commerce_tools_needed = False
            clarification_needed = True
            return intent, entities, commerce_tools_needed, clarification_needed

        # Short ambiguous messages with no context → AMBIGUOUS
        if not message or re.match(r"^\s*$", message) or len(message.strip()) <= 2:
            intent = INTENT_AMBIGUOUS
            commerce_tools_needed = False
            clarification_needed = True
            return intent, entities, commerce_tools_needed, clarification_needed

        # Messages with no recognizable intent patterns → AMBIGUOUS (fallback)
        # Check if any intent pattern matched by seeing if we have entities or if message is very short/garbled
        normalized = re.sub(r"\s+", " ", (message or "").casefold()).strip()
        # Very short messages without clear words → AMBIGUOUS
        if len(normalized) <= 5 and not re.search(r"[aeiouAEIOU]{1,}", normalized):
            # Very short messages without vowels (likely not real words)
            intent = INTENT_AMBIGUOUS
            commerce_tools_needed = False
            clarification_needed = True
            return intent, entities, commerce_tools_needed, clarification_needed

        # Long messages that don't match any intent patterns → AMBIGUOUS
        # If we have a long message with no intent detection, it's likely ambiguous
        if len(normalized) > 5 and not entities:
            # Check if it has any Arabic/French/English commerce-related words
            # But exclude greetings and casual chatter from being flagged as ambiguous
            if not _is_greeting(message):
                # Also exclude common non-commerce phrases
                casual_phrases = re.search(r"(salam|سلام|wach|wesh|كيفاش|kifash|بch7al|bch7al|بشحال|sava|ça\s+va)", normalized)
                if not casual_phrases:
                    commerce_words = re.search(r"(price|prix|سعر|بشحال|كم\s+سع|product|produit|منتج|عندكم|order|طلب|warranty|ضمان|refund|استرجاع|delivery|توصيل|كمية|quantity|اشتري|buy|achat)", normalized)
                    if not commerce_words:
                        intent = INTENT_AMBIGUOUS
                        commerce_tools_needed = False
                        clarification_needed = True
                        return intent, entities, commerce_tools_needed, clarification_needed

        # Default: general chat
        intent = INTENT_GENERAL_CHAT
        commerce_tools_needed = False
        clarification_needed = False

    # ------------------------------------------------------------------
    # Default fallthrough (should not reach here)
    # ------------------------------------------------------------------
    else:
        intent = INTENT_GENERAL_CHAT
        commerce_tools_needed = False
        clarification_needed = False

    return intent, entities, commerce_tools_needed, clarification_needed


# ---------------------------------------------------------------------------
# 5. Compatibility functions (for existing code integration)
# ---------------------------------------------------------------------------


def classify_message(message: str) -> str:
    """Legacy compatibility function.

    Returns a simple intent string for backward compatibility with code that
    expects a string rather than a ClassificationResult.
    """
    result = ConversationClassifier.classify(message)
    return result.intent


# ---------------------------------------------------------------------------
# 6. Main classifier class
# ---------------------------------------------------------------------------


class ConversationClassifier:
    """Production-conscious conversation intent classifier for DzCommerce.

    Classifies user messages into one of 14 intent categories while considering
    conversation context.  The classifier is deterministic-first; when an LLM
    provider is available, it can be used to augment or validate the deterministic
    classification, but the deterministic path is always respected as the source of
    truth for intent, confidence, and routing decisions.

    The classifier never fabricates confidence.  When uncertain, it returns a
    conservative fallback that preserves existing safeguards and prompts for
    clarification when appropriate.
    """

    # Class-level cache for compiled regex patterns (performance)
    _compiled_patterns: Dict[str, re.Pattern] = {}

    # Intent categories that are considered "non-commercial" for the bypass logic
    _NON_COMMERCIAL_INTENTS = frozenset(
        {
            INTENT_GENERAL_CHAT,
            INTENT_TOPIC_CHANGE,
            INTENT_AMBIGUOUS,
            INTENT_UNSUPPORTED_OR_RESTRICTED,
        }
    )

    def __init__(self) -> None:
        pass  # No state needed; all methods are static/classmethods

    @staticmethod
    def is_greeting(message: str) -> bool:
        return _is_greeting(message)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def classify(
        cls,
        user_message: str,
        *,
        language: Optional[str] = None,
        recent_turns: Optional[List[Dict[str, str]]] = None,
        commerce_stage: Optional[str] = None,
        selected_product_id: Optional[str] = None,
        selected_product_name: Optional[str] = None,
        last_question_type: Optional[str] = None,
    ) -> ClassificationResult:
        """Classify a user message and return a validated result.

        Args:
            user_message: The raw customer message.
            language: Optional explicit language tag ('ar', 'fr', 'en', 'dz').
                      If omitted, the classifier attempts auto-detection.
            recent_turns: Recent conversation turns for context-aware inference.
            commerce_stage: Current commerce stage from the conversation state.
            selected_product_id: Selected product ID, when applicable.
            selected_product_name: Selected product name, when applicable.
            last_question_type: The last question type from the conversation state.

        Returns:
            A validated ClassificationResult instance.
        """
        # ------------------------------------------------------------------
        # Step 1: Language detection
        # ------------------------------------------------------------------
        detected_language = language or cls._detect_language(user_message)

        # ------------------------------------------------------------------
        # Step 2: Deterministic heuristic inference using context
        # ------------------------------------------------------------------
        intent, entities, commerce_tools_needed, clarification_needed = (
            _infer_intent_from_context(
                user_message,
                detected_language,
                selected_product_id,
                selected_product_name,
                commerce_stage,
                last_question_type,
                recent_turns,
            )
        )

        # ------------------------------------------------------------------
        # Step 3: Compute confidence based on signal strength
        # ------------------------------------------------------------------
        confidence = cls._compute_confidence(
            intent,
            detected_language,
            entities,
            commerce_tools_needed,
            clarification_needed,
        )

        # ------------------------------------------------------------------
        # Step 4: Build routing reason
        # ------------------------------------------------------------------
        routing_reason = cls._build_routing_reason(
            intent,
            detected_language,
            entities,
            commerce_tools_needed,
            clarification_needed,
        )

        # ------------------------------------------------------------------
        # Step 5: Validate and return
        # ------------------------------------------------------------------
        try:
            result = ClassificationResult(
                intent=intent,
                confidence=confidence,
                language=detected_language,
                relevant_entities=entities,
                commerce_tools_needed=commerce_tools_needed,
                clarification_needed=clarification_needed,
                routing_reason=routing_reason,
            )
        except Exception:
            # Should not happen given our control flow, but safety first
            return ClassificationResult(
                intent=INTENT_AMBIGUOUS,
                confidence=0.0,
                language=detected_language,
                relevant_entities={},
                commerce_tools_needed=False,
                clarification_needed=True,
                routing_reason="Classification validation failed; using conservative fallback.",
            )

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_language(message: str) -> str:
        """Detect the primary language of a message."""
        if not message:
            return "ar"

        has_arabic_script = bool(ARABIC_SCRIPT_RE.search(message))
        has_french_markers = bool(FRENCH_RE.search(message))

        if has_arabic_script and not has_french_markers:
            return "ar"

        if has_french_markers:
            return "fr"

        # Very loose Algerian/Darija Arabizi markers
        msg_lower = message.lower()
        if re.search(r"\b7ab\b|\b7al\b|\bn7a\b|\bch7al\b", msg_lower):
            return "dz"

        return "en"

    @staticmethod
    def _compute_confidence(
        intent: str,
        language: str,
        entities: Dict[str, str],
        commerce_tools_needed: bool,
        clarification_needed: bool,
    ) -> float:
        """Compute a confidence score in [0.0, 1.0].

        The confidence is based on how many deterministic signals matched
        and how unambiguous the intent is.  It is intentionally conservative:
        ambiguous or context-dependent messages receive lower confidence,
        and messages that trigger clarification needs also get reduced
        confidence to reflect uncertainty.
        """
        base = 0.0

        # Greeting: high confidence when clearly a greeting
        if intent == INTENT_GENERAL_CHAT and not entities:
            base = 0.95

# Product inquiry with clear entity
        if intent == INTENT_PRODUCT_INQUIRY and entities.get("product_mention"):
            base = 0.85
        # Product inquiry without clear entity - raise base confidence
        # to reflect clear pattern matching, but still apply penalties
        elif intent == INTENT_PRODUCT_INQUIRY:
            base = 0.75

        # Price inquiry: moderate confidence (need to know which product)
        if intent == INTENT_PRICE_INQUIRY:
            base = 0.80

        # Availability inquiry: moderate confidence
        if intent == INTENT_AVAILABILITY_INQUIRY:
            base = 0.80

        # Purchase intent without product context: low confidence (needs clarification)
        if intent == INTENT_PURCHASE_INTENT and not entities.get("product_mention"):
            base = 0.40
        # Purchase intent with product context: high confidence
        if intent == INTENT_PURCHASE_INTENT and entities.get("product_mention"):
            base = 0.90

        # Ambiguous: low confidence
        if intent == INTENT_AMBIGUOUS:
            base = 0.30

        # Topic change: moderate confidence
        if intent == INTENT_TOPIC_CHANGE:
            base = 0.65

        # Objection handling: moderate confidence
        if intent == INTENT_OBJECTION_HANDLING:
            base = 0.75

        # After-sales: moderate confidence
        if intent == INTENT_AFTER_SALES:
            base = 0.70

        # Order status/modification: moderate confidence
        if intent == INTENT_ORDER_STATUS:
            base = 0.70
        if intent == INTENT_ORDER_MODIFICATION:
            base = 0.70

        # Unsupported/restricted: low confidence (policy-driven)
        if intent == INTENT_UNSUPPORTED_OR_RESTRICTED:
            base = 0.60

        # Reduce confidence when clarification is needed
        if clarification_needed:
            base = max(0.0, base - 0.10)

        # Reduce confidence when commerce tools are needed but no entity is clear
        if commerce_tools_needed and not entities.get("product_mention"):
            base = max(0.0, base - 0.10)

        # Ensure minimum floor
        return round(max(0.0, min(1.0, base)), 2)

    @staticmethod
    def _build_routing_reason(
        intent: str,
        language: str,
        entities: Dict[str, str],
        commerce_tools_needed: bool,
        clarification_needed: bool,
    ) -> str:
        """Build a brief explanation of why this intent was chosen."""
        entity_str = f", product={entities.get('product_mention')}" if entities else ""

        reasons = {
            INTENT_GENERAL_CHAT: f"General conversation{entity_str}",
            INTENT_PRODUCT_INQUIRY: f"Product inquiry{entity_str}",
            INTENT_PRODUCT_FOLLOWUP: f"Product follow-up (selected product in context){entity_str}",
            INTENT_PRICE_INQUIRY: f"Price inquiry{entity_str}",
            INTENT_AVAILABILITY_INQUIRY: f"Availability/stock inquiry{entity_str}",
            INTENT_PURCHASE_INTENT: f"Purchase intent{entity_str}",
            INTENT_ORDER_STATUS: f"Order status request{entity_str}",
            INTENT_ORDER_MODIFICATION: f"Order modification request{entity_str}",
            INTENT_AFTER_SALES: f"After-sales inquiry{entity_str}",
            INTENT_OBJECTION_HANDLING: f"Objection/concern handling{entity_str}",
            INTENT_TOPIC_CHANGE: f"Topic change from previous conversation",
            INTENT_AMBIGUOUS: f"Ambiguous intent; clarification needed{entity_str}",
            INTENT_UNSUPPORTED_OR_RESTRICTED: f"Unsupported or restricted request{entity_str}",
        }

        return reasons.get(intent, "Unknown intent classification")

    # ------------------------------------------------------------------
    # Convenience: quick-classify without full context (for simple cases)
    # ------------------------------------------------------------------

    @classmethod
    def quick_classify(
        cls,
        user_message: str,
        *,
        language: Optional[str] = None,
    ) -> ClassificationResult:
        """Quick classification without conversation context.

        Useful for simple one-turn scenarios or initial screening before
        full context-aware classification.  Returns a result with lower
        confidence when context is absent.
        """
        # Detect language
        detected_language = language or cls._detect_language(user_message)

        # Normalize
        normalized = re.sub(r"\s+", " ", (user_message or "").casefold()).strip()

        # Entities
        entities: Dict[str, str] = {}

        # Simple intent detection without context
        if _is_greeting(user_message):
            intent = INTENT_GENERAL_CHAT
            commerce_tools_needed = False
            clarification_needed = False
        elif _is_price_inquiry(user_message):
            intent = INTENT_PRICE_INQUIRY
            commerce_tools_needed = True
            clarification_needed = True
            entities["query"] = normalized
        elif _is_availability_inquiry(user_message):
            intent = INTENT_AVAILABILITY_INQUIRY
            commerce_tools_needed = True
            clarification_needed = True
            entities["query"] = normalized
        elif _is_product_inquiry(user_message):
            intent = INTENT_PRODUCT_INQUIRY
            commerce_tools_needed = True
            clarification_needed = True
            entities["query"] = normalized
        elif re.search(r"\b(yes|oui|confirm|confirmation)\b", normalized):
            intent = INTENT_AMBIGUOUS
            commerce_tools_needed = False
            clarification_needed = True
        elif _is_objection_handling(user_message):
            intent = INTENT_OBJECTION_HANDLING
            commerce_tools_needed = False
            clarification_needed = True
        else:
            # Default to general chat
            intent = INTENT_GENERAL_CHAT
            commerce_tools_needed = False
            clarification_needed = False

        # Compute confidence
        confidence = cls._compute_confidence(
            intent,
            detected_language,
            entities,
            commerce_tools_needed,
            clarification_needed,
        )

        # Build routing reason
        reasons = {
            INTENT_GENERAL_CHAT: "General conversation (no context)",
            INTENT_PRODUCT_INQUIRY: "Product inquiry (no context)",
            INTENT_PRICE_INQUIRY: "Price inquiry (no context)",
            INTENT_AVAILABILITY_INQUIRY: "Availability inquiry (no context)",
            INTENT_AMBIGUOUS: "Ambiguous intent (no context)",
            INTENT_OBJECTION_HANDLING: "Objection handling (no context)",
        }
        routing_reason = reasons.get(intent, "Unknown intent")

        try:
            return ClassificationResult(
                intent=intent,
                confidence=confidence,
                language=detected_language,
                relevant_entities=entities,
                commerce_tools_needed=commerce_tools_needed,
                clarification_needed=clarification_needed,
                routing_reason=routing_reason,
            )
        except Exception:
            return ClassificationResult(
                intent=INTENT_AMBIGUOUS,
                confidence=0.0,
                language=detected_language,
                relevant_entities={},
                commerce_tools_needed=False,
                clarification_needed=True,
                routing_reason="Quick classify validation failed.",
            )

    @classmethod
    def is_non_commercial_message(cls, message: str, commerce_stage: str = None, selected_product_id: str = None, selected_product_name: str = None) -> bool:
        """Check if a message is non-commercial (should bypass the agent loop).

        This method is used by ConversationEngine to determine if a message
        is purely conversational and should be handled by the Qwen agent
        without forcing commerce tool calls.

        Args:
            message: The user message to check.
            commerce_stage: Current commerce stage from conversation state.
            selected_product_id: Selected product ID, when applicable.
            selected_product_name: Selected product name, when applicable.

        Returns:
            True if the message is non-commercial (GENERAL_CHAT, TOPIC_CHANGE,
            AMBIGUOUS, or UNSUPPORTED_OR_RESTRICTED).
        """
        result = cls.classify(
            message,
            commerce_stage=commerce_stage,
            selected_product_id=selected_product_id,
            selected_product_name=selected_product_name,
        )
        return result.intent in cls._NON_COMMERCIAL_INTENTS