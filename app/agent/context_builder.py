"""
ConversationContextBuilder: Strict Phase 13.2 context injection.
Prevents premature draft creation and enforces variant_index workflow.
"""
import uuid

from sqlalchemy.orm import Session

from app.agent.providers.base import LLMMessage
from app.models.conversation import Conversation, Message

SYSTEM_PROMPT = """You are DzCommerce Agent, an AI sales assistant for an Algerian online store.

STRICT TOOL POLICY:

1. search_products
   - Use only when the customer asks about a product name and no selected product exists.
   - Also use if the customer explicitly asks for a different/new product.
   - Do not use search_products again if CURRENT STATE already contains SELECTED PRODUCT.

2. get_product_details
   - Use when the customer asks about variants, color, size, stock, price details, or wants to order a selected product.
   - Use the product id from CURRENT STATE if available.
   - Do not invent product ids.
   - Do not pass product names as product_id.

3. create_order_draft
   - Use ONLY when the customer explicitly asks to create/order/buy, for example:
     "ديرلي طلب", "دير الطلب", "نحب نشري", "عايز نطلب", "commander", "order".
   - Use variant indexes from the latest get_product_details result OR from AVAILABLE VARIANT INDEXES in CURRENT STATE. If neither exists, call get_product_details first.
   - Use variant_index integer only.
   - Never use raw UUIDs.
   - Never call create_order_draft for greetings, availability questions, or variant preference alone.

4. confirm_order
   - Use ONLY when customer explicitly confirms, for example:
     "أكد", "نعم", "موافق", "yes", "oui", "confirmer".
   - Only call confirm_order if CURRENT STATE shows ACTIVE CART.
   - If ACTIVE CART exists, do not search again and do not create another draft.

5. State priority
   - If CURRENT STATE shows ACTIVE CART:
       Do not call search_products.
       Do not call create_order_draft.
       Ask the customer to confirm with "أكد".
   - If CURRENT STATE shows SELECTED PRODUCT but no ACTIVE CART:
       Use get_product_details when needed.
       Do not create draft unless explicit order intent exists.

6. Safety
   - Never invent UUIDs.
   - Never use placeholders.
   - If a tool fails once, do not loop repeatedly. Explain briefly and ask the customer to clarify or choose.

7. Language
   - Respond in Algerian Darija, Arabic, or French matching the customer.
   - Be concise.
   - Do not output Chinese characters, random symbols, or mixed broken language.
"""


class ConversationContextBuilder:
    def __init__(
        self,
        db: Session,
        store_id: uuid.UUID,
        customer_id: uuid.UUID,
        conversation_id: uuid.UUID,
    ):
        self.db = db
        self.store_id = store_id
        self.customer_id = customer_id
        self.conversation_id = conversation_id

    async def build(self, current_message: str) -> list[LLMMessage]:
        messages = [LLMMessage(role="system", content=SYSTEM_PROMPT)]

        state_info = self._get_structured_state()
        if state_info:
            messages.append(
                LLMMessage(role="system", content=f"CURRENT STATE:\n{state_info}")
            )

        history = self._get_recent_history()
        messages.extend(history)

        messages.append(LLMMessage(role="user", content=current_message))
        return messages

    def _get_structured_state(self) -> str:
        parts = []

        try:
            conv = (
                self.db.query(Conversation)
                .filter(Conversation.id == self.conversation_id)
                .first()
            )

            if not conv:
                return "- ERROR: No conversation found."

            # 1. Active draft has highest priority
            if conv.active_draft_json:
                draft = conv.active_draft_json
                items = draft.get("items", [])
                total = draft.get("total_price", 0)

                if items:
                    summary = ", ".join(
                        [
                            f"{i.get('product_name', 'Unknown')} "
                            f"({i.get('variant_name', 'Unknown')}) x{i.get('quantity', 1)}"
                            for i in items
                        ]
                    )
                    parts.append("🛒 ACTIVE CART: YES")
                    parts.append(f"- ITEMS: {summary}")
                    parts.append(f"- TOTAL: {total} DZD")
                    parts.append("- STATUS: READY_FOR_CONFIRMATION")
                    parts.append("- ACTION: Do not search. Do not create draft. Ask customer to confirm with 'أكد'.")
                else:
                    parts.append("🛒 ACTIVE CART: Empty")
            else:
                parts.append("🛒 ACTIVE CART: None")

            # 2. Canonical commerce state
            if conv.metadata_json:
                commerce_stage = conv.metadata_json.get("commerce_stage") or "EMPTY"
                parts.append(f"🧭 COMMERCE STAGE: {commerce_stage}")

                selected_product_id = conv.metadata_json.get("selected_product_id") or conv.metadata_json.get("last_product_id")
                selected_product_name = conv.metadata_json.get("selected_product_name") or conv.metadata_json.get("last_product_name")
                if selected_product_id:
                    parts.append(f"📦 SELECTED PRODUCT: {selected_product_name or 'Unknown'}")
                    parts.append(f"   PRODUCT_ID: {selected_product_id}")
                else:
                    candidate_ids = conv.metadata_json.get("candidate_product_ids") or []
                    if candidate_ids:
                        parts.append(f"📋 CANDIDATE PRODUCTS: {candidate_ids}")

                selected_variant_id = conv.metadata_json.get("selected_variant_id")
                if selected_variant_id:
                    parts.append(f"🎯 SELECTED VARIANT: {selected_variant_id}")

                selected_attributes = conv.metadata_json.get("selected_attributes") or {}
                if selected_attributes:
                    parts.append(f"🏷️ SELECTED ATTRIBUTES: {selected_attributes}")

                # 3. Available variant indexes, if already loaded
                variant_map = conv.metadata_json.get("variant_index_map")
                if variant_map:
                    indexes = []
                    for key in variant_map.keys():
                        try:
                            indexes.append(int(key))
                        except (ValueError, TypeError):
                            continue

                    if indexes:
                        indexes = sorted(set(indexes))
                        parts.append(f"🔢 AVAILABLE VARIANT INDEXES: {indexes}")
                        parts.append(
                            "   ACTION: If customer explicitly asks to order, create a draft using the real variant index mapping."
                        )

        except Exception as e:
            print(f"⚠️ Context Builder Error: {e}")
            parts.append("- ERROR loading structured state.")

        return "\n".join(parts)

    def _get_recent_history(self) -> list[LLMMessage]:
        try:
            msgs = (
                self.db.query(Message)
                .filter(Message.conversation_id == self.conversation_id)
                .order_by(Message.created_at.desc())
                .limit(5)
                .all()
            )
        except Exception:
            return []

        msgs.reverse()

        history = []
        for m in msgs:
            role_val = m.role.value if hasattr(m.role, "value") else str(m.role)

            if role_val in ("customer", "user"):
                role = "user"
            elif role_val in ("agent", "assistant"):
                role = "assistant"
            else:
                continue

            content = m.content or ""
            if len(content) > 300:
                content = content[:300] + "..."

            history.append(LLMMessage(role=role, content=content))

        return history
