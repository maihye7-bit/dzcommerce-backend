"""
Create Order Draft Tool: Uses the SAME context session with a SAVEPOINT.
CRITICAL FIX: No longer opens an isolated SessionLocal(), which could not see
the uncommitted variant_index_map saved by get_product_details in the same turn.
The savepoint guarantees that a failure here does not poison the main webhook transaction.
"""
import uuid
from typing import Any

from app.agent.tools.base import BaseTool, ToolResult
from app.services.exceptions import NotFoundError, ValidationError
from app.services.order_draft_service import save_draft_safe


class CreateOrderDraftTool(BaseTool):

    @property
    def name(self) -> str:
        return "create_order_draft"

    @property
    def description(self) -> str:
        return (
            "Creates or updates the current order draft. "
            "Requires 'variant_index' (integer from get_product_details) and quantity. "
            "The backend resolves the index to the real variant_id and validates price/stock. "
            "This does NOT place the final order, only prepares it."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "variant_index": {
                                "type": "integer",
                                "description": "The numeric index shown by get_product_details (1, 2, 3...).",
                            },
                            "quantity": {"type": "integer"},
                        },
                        "required": ["variant_index", "quantity"],
                    },
                    "description": "List of products to add using their indexes.",
                },
                "shipping_info": {
                    "type": "object",
                    "properties": {
                        "phone": {"type": "string"},
                        "wilaya": {"type": "string"},
                        "municipality": {"type": "string"},
                        "address": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            },
            "required": ["items"],
        }

    async def execute(
        self,
        store_id: uuid.UUID,
        arguments: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        try:
            args = self.validate_arguments(arguments)
            db = context["db"]  # USE THE SAME SESSION AS get_product_details
            conversation_id = context.get("conversation_id")

            if not conversation_id:
                return ToolResult(success=False, error="Missing conversation context.")

            items = args.get("items", [])
            shipping_info = args.get("shipping_info")

            if not items:
                return ToolResult(success=False, error="No items provided.")

            # SAVEPOINT: run inside the same session, but isolate failure.
            # - Success  -> savepoint committed (draft persisted, visible to later tools).
            # - Failure  -> savepoint rolled back ONLY; main session stays clean.
            with db.begin_nested():
                draft_data = save_draft_safe(
                    db=db,
                    conversation_id=conversation_id,
                    store_id=store_id,
                    items=items,
                    shipping_info=shipping_info,
                )

            return ToolResult(
                success=True,
                data={
                    "message": "Draft saved successfully.",
                    "draft_summary": {
                        "item_count": len(draft_data["items"]),
                        "total_price": draft_data["total_price"],
                        "items_preview": [
                            f"{i['product_name']} ({i['variant_name']}) x{i['quantity']}"
                            for i in draft_data["items"]
                        ],
                    },
                    "delivery_details": {
                        "phone_provided": bool(
                            (draft_data.get("shipping_info") or {}).get("phone")
                        ),
                        "wilaya": (draft_data.get("shipping_info") or {}).get(
                            "wilaya"
                        ),
                        "municipality": (
                            draft_data.get("shipping_info") or {}
                        ).get("municipality"),
                        "address_provided": bool(
                            (draft_data.get("shipping_info") or {}).get("address")
                        ),
                    },
                        "instruction": (
                            "Do not confirm the final order. The conversation engine "
                            "will continue the conversation and require explicit "
                            "customer approval before placing the order."
                        ),
                    },
            )
        except ValidationError as exc:
            message = str(exc)
            if "Variant index" in message and "not found" in message:
                error = (
                    f"الخيار المطلوب غير موجود: {message} "
                    "راجع أرقام الخيارات المعروضة واختر رقماً صحيحاً قبل إنشاء المسودة."
                )
            elif "Insufficient stock" in message:
                error = (
                    f"الكمية المطلوبة غير متوفرة حالياً: {message} "
                    "خفّض الكمية أو اختر خياراً آخر متاحاً."
                )
            else:
                error = (
                    f"تعذر إنشاء مسودة الطلب بسبب بيانات غير صالحة: {message} "
                    "تحقق من رقم الخيار والكمية، ثم أعد الاختيار."
                )
            return ToolResult(
                success=False,
                error=error,
                error_code="VALIDATION_ERROR",
            )
        except NotFoundError as exc:
            return ToolResult(
                success=False,
                error=(
                    f"لم يتم العثور على المحادثة أو المنتج أو الخيار المطلوب: {exc} "
                    "تأكد من اختيار منتج وخيار معروضين في هذا المتجر ثم أعد المحاولة."
                ),
                error_code="NOT_FOUND",
            )
        except Exception:
            raise
