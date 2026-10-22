"""
ConversationEngine: Orchestrates LLM, CommerceResolver, and ToolRegistry.
PHASE 14 INTEGRATION: Backend-driven decision making via CommerceResolver.

Flow:
1. Load Current State from DB.
2. Extract Intent/NLU (via Qwen or simple heuristic for now).
3. Resolve Business Action via CommerceResolver.
4. Execute Approved Tool/Service.
5. Update Context & Respond.
"""
import json
import re
import uuid
from typing import Any
from sqlalchemy.orm import Session

from app.agent.context_builder import ConversationContextBuilder
from app.agent.providers.base import LLMMessage
from app.agent.tools.registry import ToolRegistry
from app.agent.commerce_resolver import CommerceResolver, ResolutionResult, AllowedAction
from app.models.conversation import Conversation, ConversationStatus
from app.database import SessionLocal # For isolated sessions if needed

MAX_TOOL_ROUNDS = 3
HANDOFF_KEYWORDS = ["human", "person", "agent", "بشري", "انسان", "موظف", "دعم"]
SAFE_FALLBACK_RESPONSE = "عذراً، لم أتمكن من إكمال طلبك حالياً. يرجى المحاولة مرة أخرى لاحقاً."


def _detect_handoff_intent(message: str) -> bool:
    if not message:
        return False
    lower = message.lower().strip()
    return any(kw in lower for kw in HANDOFF_KEYWORDS)


class ConversationEngine:
    def __init__(self, llm_provider, tool_registry: ToolRegistry):
        self.llm = llm_provider
        self.registry = tool_registry

    @staticmethod
    def _normalize_current_state(conversation: Conversation, store_id: uuid.UUID) -> dict:
        """Flatten the conversation JSON into the canonical commerce state contract."""
        metadata = conversation.metadata_json or {}
        draft = conversation.active_draft_json or {}

        selected_product_id = metadata.get("selected_product_id") or metadata.get("last_product_id")
        selected_product_name = metadata.get("selected_product_name") or metadata.get("last_product_name")
        selected_variant_id = metadata.get("selected_variant_id")
        candidate_product_ids = metadata.get("candidate_product_ids") or []

        commerce_stage = metadata.get("commerce_stage")
        if not commerce_stage:
            if draft and isinstance(draft, dict) and draft.get("items"):
                commerce_stage = "DRAFT_PENDING"
            elif selected_variant_id:
                commerce_stage = "VARIANT_SELECTED"
            elif candidate_product_ids and not selected_product_id:
                commerce_stage = "PRODUCT_CANDIDATES"
            elif selected_product_id:
                commerce_stage = "PRODUCT_SELECTED"
            else:
                commerce_stage = "EMPTY"

        return {
            "store_id": store_id,
            "commerce_stage": commerce_stage,
            "selected_product_id": selected_product_id,
            "selected_product_name": selected_product_name,
            "candidate_product_ids": candidate_product_ids,
            "selected_variant_id": selected_variant_id,
            "selected_attributes": metadata.get("selected_attributes") or {},
            "variant_index_map": metadata.get("variant_index_map") or {},
            "active_draft_json": draft,
        }

    async def process_message(
        self,
        db: Session,
        store_id: uuid.UUID,
        customer_id: uuid.UUID,
        conversation_id: uuid.UUID | None,
        channel: str,
        user_message: str,
    ) -> dict:
        conv_id = conversation_id or uuid.uuid4()

        # Ensure conversation exists
        conversation = db.query(Conversation).filter(Conversation.id == conv_id).first()
        if not conversation:
            conversation = Conversation(
                id=conv_id,
                store_id=store_id,
                customer_id=customer_id,
                channel=channel,
                status=ConversationStatus.ACTIVE,
            )
            db.add(conversation)
            db.flush()

        # ---------------------------------------------------------
        # STEP 1: LOAD CURRENT STATE FROM DB
        # ---------------------------------------------------------
        current_state = self._normalize_current_state(conversation, store_id)

        # ---------------------------------------------------------
        # STEP 2: EXTRACT INTENT VIA QWEN (NLU ONLY)
        # ---------------------------------------------------------
        # We ask Qwen to interpret the text WITHOUT executing tools yet.
        # This replaces the old 'tool_choice="auto"' behavior.
        nlu_output = await self._extract_nlu_via_qwen(user_message, current_state)

        # Safety Check: If NLU fails completely, fallback to unknown
        if not nlu_output or "intent" not in nlu_output:
            intent = nlu_output.get("intent_guess") if isinstance(nlu_output, dict) and "intent_guess" in nlu_output else "unknown"
            nlu_output = {
                "intent": intent,
                "intent_guess": intent,
                "product_mention": nlu_output.get("product_mention") if isinstance(nlu_output, dict) else None,
                "attributes": nlu_output.get("attributes") if isinstance(nlu_output, dict) else {},
                "quantity": nlu_output.get("quantity") if isinstance(nlu_output, dict) else None,
                "confirmation_phrase": bool(nlu_output.get("confirmation_phrase", False)) if isinstance(nlu_output, dict) else False,
                "language": nlu_output.get("language") if isinstance(nlu_output, dict) else "ar",
                "confidence": float(nlu_output.get("confidence", 0.0)) if isinstance(nlu_output, dict) else 0.0,
            }

        # ---------------------------------------------------------
        # STEP 3: RESOLVE BUSINESS DECISION VIA BACKEND
        # ---------------------------------------------------------
        resolver = CommerceResolver(db=db)
        decision: ResolutionResult = resolver.resolve(
            nlu_output=nlu_output,
            current_state=current_state,
            store_id=store_id
        )

        # ---------------------------------------------------------
        # STEP 4: EXECUTE ACTION BASED ON DECISION
        # ---------------------------------------------------------
        final_response_content = ""
        
        if decision.allowed_action.startswith("EXECUTE_TOOL:"):
            # Case A: Run a registered tool (e.g., search_products, confirm_order)
            tool_name = decision.allowed_action.split(":")[1]
            
            # Prepare arguments SAFELY using data resolved by Backend (DB), not LLM
            tool_args = self._prepare_safe_tool_args(tool_name, decision.resolved_entities, nlu_output)
            
            # Execute Tool
            result = await self.registry.aexecute(
                tool_name=tool_name,
                arguments=tool_args,
                context={
                    "db": db,
                    "store_id": store_id,
                    "customer_id": customer_id,
                    "conversation_id": conv_id,
                    "channel": channel,
                },
            )
            
            # Generate natural language response from tool result
            if result.success:
                final_response_content = await self._generate_final_text(result.data, decision.response_hint, user_message)
            else:
                final_response_content = f"حدث خطأ: {result.error}"

        elif decision.allowed_action.startswith("CALL_SERVICE:"):
            # Case B: Call internal service directly (e.g., create_draft logic if bypassed tool)
            # For Phase 14.1-A, we mostly rely on Tools, but this hook allows direct service calls later.
            service_name = decision.allowed_action.split(":")[1]
            final_response_content = await self._handle_service_call(service_name, decision.resolved_entities, db, conv_id)

        elif decision.allowed_action == "RESPOND:text_only":
            # Case C: No action taken, just respond with hint/error message
            final_response_content = decision.response_hint or "أعتذر، لم أفهم ما تريد فعله بالضبط."

        else:
            # Unknown action fallback
            final_response_content = SAFE_FALLBACK_RESPONSE

        # ---------------------------------------------------------
        # STEP 5: PERSIST CONTEXT UPDATES TO DB
        # ---------------------------------------------------------
        if decision.context_updates:
            tool_managed_search_state = set()
            if (
                decision.allowed_action == AllowedAction.SEARCH_PRODUCTS.value
                and "result" in locals()
                and result.success
            ):
                db.refresh(conversation, attribute_names=["metadata_json"])
                tool_managed_search_state = {
                    "commerce_stage",
                    "selected_product_id",
                    "selected_product_name",
                    "candidate_product_ids",
                    "selected_variant_id",
                    "selected_attributes",
                }

            # Merge updates into existing metadata_json
            if not conversation.metadata_json:
                conversation.metadata_json = {}
            
            # Only update specific keys to avoid overwriting unrelated data
            for key, value in decision.context_updates.items():
                if key not in tool_managed_search_state:
                    conversation.metadata_json[key] = value
            
            db.flush() # Save changes
        
        # Commit transaction at the end of processing
        db.commit()

        return {
            "conversation_id": str(conv_id),
            "response": final_response_content,
            "handoff": False, # Handoff logic can be added here if needed
            "tool_calls": [], # Deprecated in new flow, kept for compatibility
        }

    async def _extract_nlu_via_qwen(self, message: str, state: dict) -> dict:
        """
        Calls Qwen specifically for NLU extraction.
        Returns structured JSON intent.
        """
        # Construct a lightweight prompt for pure understanding
        system_prompt = """You are an NLU engine for an Algerian e-commerce bot.
Analyze the user message and return ONLY valid JSON.
Schema:
{
  "intent": "product_search|variant_selection|order_create|order_confirm|greeting|unknown",
  "product_mention": string|null,
  "attributes": { "اسم_السمة": "القيمة كما قالها العميل" },
  "quantity": int|null,
  "confirmation_phrase": boolean,
  "language": "ar|fr|en",
  "confidence": 0.0
}
Rules:
- Extract any relevant attributes without limiting them to clothing: color, size, storage, RAM, weight, material, dimensions, volume, smell, flavor, quantity, model, and other product-specific properties.
- Use attribute names naturally in the customer's language and preserve the values as spoken. Do not translate or normalize attribute keys or values.
- Examples:
  Customer: "عايز نوت بش ٢٥٦ غيغا كحل"
  JSON: {"intent":"variant_selection","product_mention":null,"attributes":{"التخزين":"٢٥٦ غيغا","اللون":"كحل"},"quantity":null,"confirmation_phrase":false,"language":"ar","confidence":0.95}
  Customer: "كاكاو ٤٠٠ غرام"
  JSON: {"intent":"variant_selection","product_mention":null,"attributes":{"الوزن":"٤٠٠ غرام","الطعم":"كاكاو"},"quantity":null,"confirmation_phrase":false,"language":"ar","confidence":0.95}
  Customer: "طاولة خشب بيضا"
  JSON: {"intent":"variant_selection","product_mention":null,"attributes":{"المادة":"خشب","اللون":"بيضا"},"quantity":null,"confirmation_phrase":false,"language":"ar","confidence":0.95}
  Customer: "نحب قميص مقاس M أزرق"
  JSON: {"intent":"variant_selection","product_mention":null,"attributes":{"المقاس":"M","اللون":"أزرق"},"quantity":null,"confirmation_phrase":false,"language":"ar","confidence":0.95}
- Do NOT invent IDs.
- Do NOT output commerce decisions like product_id, variant_id, order_id, price, stock.
- Return JSON only."""

        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=message)
        ]

        try:
            response = await self.llm.chat(messages=messages, tools=None)
            if getattr(response, "tool_calls", None):
                first_tool = response.tool_calls[0]
                name = str(first_tool.get("name") or "")
                args = first_tool.get("arguments") or {}
                product_mention = args.get("query") or args.get("product_mention")
                intent = "product_search" if name == "search_products" else "unknown"
                return {
                    "intent": intent,
                    "intent_guess": intent,
                    "product_mention": product_mention,
                    "attributes": {},
                    "quantity": None,
                    "confirmation_phrase": False,
                    "language": "ar",
                    "confidence": 0.8,
                }

            raw_text = (response.content or "").strip()
            if not raw_text:
                return self._heuristic_nlu(message)

            # Parse JSON
            if raw_text.startswith("```"):
                lines = raw_text.split("\n")
                raw_text = "\n".join(lines[1:-1])

            try:
                parsed = json.loads(raw_text)
                if isinstance(parsed, dict):
                    intent = parsed.get("intent") or parsed.get("intent_guess") or "unknown"
                    parsed.setdefault("intent", intent)
                    parsed.setdefault("intent_guess", intent)
                    parsed.setdefault("attributes", {})
                    parsed.setdefault("quantity", None)
                    parsed.setdefault("confirmation_phrase", False)
                    parsed.setdefault("language", "ar")
                    parsed.setdefault("confidence", 0.0)
                    return parsed
            except Exception:
                pass

            return self._heuristic_nlu(message)
        except Exception as e:
            print(f"⚠️ NLU Extraction Failed: {e}")
            return self._heuristic_nlu(message)

    def _heuristic_nlu(self, message: str) -> dict:
        msg = (message or "").strip()
        normalized_digits = msg.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789"))
        lower = normalized_digits.casefold()

        if not msg:
            return {"intent": "unknown", "intent_guess": "unknown", "product_mention": None, "attributes": {}, "quantity": None, "confirmation_phrase": False, "language": "ar", "confidence": 0.0}

        attributes: dict[str, str] = {}

        storage_match = re.search(
            r"(?<!\w)(\d+(?:[.,]\d+)?)\s*(غيغا|جيغا|гб|gb|go|giga)(?!\w)",
            lower,
            flags=re.IGNORECASE,
        )
        if storage_match:
            attributes["storage"] = f"{storage_match.group(1)} {storage_match.group(2)}"

        weight_match = re.search(
            r"(?<!\w)(\d+(?:[.,]\d+)?)\s*(غرامات|غرام|جرامات|جرام|كلغ|كيلوغرام|كيلو|kgs|kg|grammes|gram|gr|غ)(?!\w)",
            lower,
            flags=re.IGNORECASE,
        )
        if weight_match:
            attributes["weight"] = f"{weight_match.group(1)} {weight_match.group(2)}"
        elif re.search(r"(?<!\w)(?:كيلو|kg)(?!\w)", lower, flags=re.IGNORECASE):
            attributes["weight"] = "كيلو"

        material_aliases = {
            "خشب": "wood",
            "الخشب": "wood",
            "bois": "wood",
            "حديد": "metal",
            "معدن": "metal",
            "métal": "metal",
            "metal": "metal",
            "بلاستيك": "plastic",
            "plastique": "plastic",
            "جلد": "leather",
            "cuir": "leather",
            "قماش": "fabric",
        }
        for alias, canonical in material_aliases.items():
            if alias in lower:
                attributes["material"] = canonical
                break

        color_aliases = {
            "أسود": "black",
            "اسود": "black",
            "سودا": "black",
            "سوداء": "black",
            "black": "black",
            "noir": "black",
            "أبيض": "white",
            "ابيض": "white",
            "بيضا": "white",
            "بيضاء": "white",
            "white": "white",
            "blanc": "white",
        }
        for alias, canonical in color_aliases.items():
            if alias in lower:
                attributes["color"] = canonical
                break

        screen_match = re.search(
            r"(?<!\w)(\d+(?:[.,]\d+)?)\s*(بوصة|بوصات|pouces?|inches?|inch)(?!\w)",
            lower,
            flags=re.IGNORECASE,
        )
        if screen_match:
            attributes["screen_size"] = f"{screen_match.group(1)} {screen_match.group(2)}"

        size_match = re.search(
            r"(?:مقاس|قياس|size|taille)\s*([a-z]{1,3}|\d{1,3})\b",
            lower,
            flags=re.IGNORECASE,
        )
        if size_match:
            attributes["size"] = size_match.group(1)
        elif not any(key in attributes for key in ("storage", "weight", "screen_size")):
            small_number = re.search(r"(?<!\w)(\d{1,3})(?!\w)", lower)
            if small_number:
                attributes["size"] = small_number.group(1)

        if any(keyword in lower for keyword in ["مرحبا", "سلام", "hello", "hi", "اهلا", "bonjour", "salut"]):
            intent = "greeting"
        elif any(keyword in lower for keyword in ["أكد", "confirm", "yes", "oui", "موافق", "تأكيد", "yes please", "نعم"]):
            intent = "order_confirm"
            return {"intent": intent, "intent_guess": intent, "product_mention": None, "attributes": {}, "quantity": None, "confirmation_phrase": True, "language": "ar", "confidence": 0.9}
        elif any(keyword in lower for keyword in ["ديرلي طلب", "دير الطلب", "أريد طلب", "أحب اشتري", "أشتري", "order", "buy", "commander", "طلب", "نحب نشري"]):
            intent = "order_create"
        elif any(keyword in lower for keyword in ["عندكم", "توجد", "لديكم", "بحث", "search", "find", "available", "شو", "شحال", "كم", "؟"]):
            intent = "product_search"
        elif attributes or any(keyword in lower for keyword in ["color", "لون", "size", "حجم", "مقاس", "جرب", "variant"]):
            intent = "variant_selection"
        else:
            intent = "unknown"

        product_mention = msg
        if intent == "greeting":
            product_mention = None
        elif intent == "order_confirm":
            product_mention = None

        return {
            "intent": intent,
            "intent_guess": intent,
            "product_mention": product_mention if intent == "product_search" else None,
            "attributes": attributes,
            "quantity": None,
            "confirmation_phrase": intent == "order_confirm",
            "language": "ar",
            "confidence": 0.9 if intent != "unknown" else 0.0,
        }

    def _prepare_safe_tool_args(self, tool_name: str, resolved_data: dict, nlu_output: dict) -> dict:
        """
        Constructs arguments strictly from DB-validated data.
        Prevents LLM hallucination of IDs.
        """
        args = {}
        
        if tool_name == "search_products":
            # Query comes from NLU text mention, safe to pass
            args["query"] = resolved_data.get("query") or nlu_output.get("product_mention", "")
            
        elif tool_name == "get_product_details":
            # Product ID MUST come from resolver's DB lookup
            pid = resolved_data.get("product_id")
            if pid:
                args["product_id"] = str(pid)
                
        elif tool_name == "create_order_draft":
            # Variant ID MUST come from resolver's DB lookup
            vid = resolved_data.get("variant_id")
            qty = resolved_data.get("quantity") or nlu_output.get("quantity", 1)
            if vid:
                args["items"] = [{"variant_id": str(vid), "quantity": int(qty)}]
                
        elif tool_name == "confirm_order":
            # No args needed, reads from active_draft_json in DB
            args = {}
            
        return args

    async def _generate_final_text(self, tool_result_data: dict, hint: str, original_msg: str) -> str:
        """
        Uses Qwen to phrase the final answer naturally, but constrained by facts.
        """
        # Simple template-based response for stability
        if "products" in tool_result_data:
            count = tool_result_data.get("count", 0)
            if count > 0:
                return f"وجدت {count} منتجات مطابقة. هل تريد رؤية التفاصيل؟"
            return "لم أجد منتجات مطابقة."
        
        if "variants" in tool_result_data:
            return "إليك الخيارات المتاحة لهذا المنتج:"
            
        if "draft_summary" in tool_result_data:
            total = tool_result_data["draft_summary"].get("total_price", 0)
            return f"تم حفظ مسودة الطلب. المجموع: {total} دج. قل 'أكد' للمتابعة."
            
        if "order_number" in tool_result_data:
            return f"تم تأكيد طلبك بنجاح! رقم الطلب: {tool_result_data['order_number']}"
            
        return hint or "تم التنفيذ."

    async def _handle_service_call(self, service_name: str, data: dict, db: Session, conv_id: uuid.UUID) -> str:
        """
        Executes approved backend service calls using resolver-validated entities.
        """
        if service_name == "create_draft":
            from app.models.product import Product, ProductVariant
            from app.services.exceptions import NotFoundError, ValidationError
            from app.services.order_draft_service import save_draft

            variant_id = data.get("variant_id")
            product_id = data.get("product_id")
            quantity = data.get("quantity")
            unit_price = data.get("unit_price")
            total_price = data.get("total_price")

            try:
                variant_uuid = uuid.UUID(str(variant_id))
                product_uuid = uuid.UUID(str(product_id))
            except (ValueError, TypeError, AttributeError):
                return "تعذر إنشاء المسودة: بيانات المنتج أو الخيار غير صالحة."

            if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
                return "تعذر إنشاء المسودة: الكمية غير صالحة."
            if unit_price is None or total_price is None:
                return "تعذر إنشاء المسودة: بيانات السعر غير مكتملة."

            conversation = db.query(Conversation).filter(
                Conversation.id == conv_id
            ).one_or_none()
            if conversation is None:
                return "تعذر إنشاء المسودة: المحادثة غير موجودة."

            variant = (
                db.query(ProductVariant)
                .join(Product)
                .filter(
                    ProductVariant.id == variant_uuid,
                    ProductVariant.product_id == product_uuid,
                    Product.store_id == conversation.store_id,
                    Product.is_active.is_(True),
                )
                .one_or_none()
            )
            if variant is None:
                return "تعذر إنشاء المسودة: المنتج أو الخيار غير متاح لهذا المتجر."

            metadata = dict(conversation.metadata_json or {})
            variant_index_map = dict(metadata.get("variant_index_map") or {})
            variant_index = next(
                (
                    str(index)
                    for index, mapped_variant_id in variant_index_map.items()
                    if str(mapped_variant_id) == str(variant_uuid)
                ),
                None,
            )
            if variant_index is None:
                numeric_indexes = [
                    int(index)
                    for index in variant_index_map
                    if str(index).isdigit()
                ]
                variant_index = str(max(numeric_indexes, default=0) + 1)
                variant_index_map[variant_index] = str(variant_uuid)
                metadata["variant_index_map"] = variant_index_map

            try:
                with db.begin_nested():
                    conversation.metadata_json = metadata
                    draft = save_draft(
                        db=db,
                        conversation_id=conv_id,
                        store_id=conversation.store_id,
                        items=[{
                            "variant_index": int(variant_index),
                            "quantity": quantity,
                        }],
                    )
            except (NotFoundError, ValidationError) as exc:
                return f"تعذر إنشاء المسودة: {exc}"

            return (
                f"تم حفظ مسودة الطلب. المجموع: "
                f"{draft['total_price']} دج. قل 'أكد' للمتابعة."
            )

        elif service_name == "resolve_variant":
            price = data.get("price")
            stock = data.get("stock")

            return (
                "وجدت الاختلاف المطلوب.\n"
                f"السعر: {price} دج\n"
                f"الكمية المتوفرة: {stock}\n"
                "قل 'ديرلي طلب' لإضافة المنتج للسلة."
            )

        return f"[Service Call: {service_name}] - Not implemented in Phase 14.1-A."

    @staticmethod
    def _get_call_signature(tool_calls: list[dict]) -> str:
        """Legacy helper, unused in new flow."""
        return ""
