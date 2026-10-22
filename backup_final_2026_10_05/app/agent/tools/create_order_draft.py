"""
Create Order Draft Tool: Uses the SAME context session with a SAVEPOINT.
CRITICAL FIX: No longer opens an isolated SessionLocal(), which could not see
the uncommitted variant_index_map saved by get_product_details in the same turn.
The savepoint guarantees that a failure here does not poison the main webhook transaction.
"""
import uuid
from typing import Any

from app.agent.tools.base import BaseTool, ToolResult
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
                    "additionalProperties": True,
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
            try:
                with db.begin_nested():
                    draft_data = save_draft_safe(
                        db=db,
                        conversation_id=conversation_id,
                        store_id=store_id,
                        items=items,
                        shipping_info=shipping_info,
                    )
            except Exception as e:
                print(f"❌ CreateOrderDraftTool Error: {str(e)}")
                return ToolResult(success=False, error=f"Failed: {str(e)}")

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
                    "instruction": "Ask the customer to confirm with 'أكد'.",
                },
            )

        except Exception as outer_e:
            print(f"💥 Unexpected Error in CreateOrderDraftTool: {outer_e}")
            return ToolResult(success=False, error="Internal tool error.")
