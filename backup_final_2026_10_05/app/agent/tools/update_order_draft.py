"""
Update Order Draft Tool: Modifies existing draft (add/remove/change qty).
"""
import uuid
from typing import Any
from sqlalchemy.orm import Session
from app.agent.tools.base import BaseTool, ToolResult
from app.services.order_draft_service import get_current_draft, save_draft


class UpdateOrderDraftTool(BaseTool):

    @property
    def name(self) -> str:
        return "update_order_draft"

    @property
    def description(self) -> str:
        return (
            "Updates the current order draft. Can add new items, remove items, "
            "or change quantities. Always validates against latest DB prices/stock."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "remove", "set"],
                    "description": "Operation to perform."
                },
                "variant_id": {
                    "type": "string",
                    "description": "Target variant ID."
                },
                "quantity": {
                    "type": "integer",
                    "description": "New quantity (for add/set)."
                }
            },
            "required": ["action", "variant_id"],
        }

    async def execute(
        self,
        store_id: uuid.UUID,
        arguments: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        try:
            args = self.validate_arguments(arguments)
            db: Session = context["db"]
            conversation_id = context.get("conversation_id")
            
            if not conversation_id:
                return ToolResult(success=False, error="Missing conversation context.")

            action = args["action"]
            variant_id_str = args["variant_id"]
            quantity = args.get("quantity", 1)

            # Get current draft
            current_draft = get_current_draft(db, conversation_id)
            if not current_draft:
                return ToolResult(success=False, error="No active draft found to update.")

            # Convert items list to mutable structure
            items_list = current_draft.get("items", [])
            
            # Helper to find index
            def find_idx(v_id):
                for i, item in enumerate(items_list):
                    if item["variant_id"] == v_id:
                        return i
                return -1

            idx = find_idx(variant_id_str)

            if action == "remove":
                if idx == -1:
                    return ToolResult(success=False, error="Item not in draft.")
                del items_list[idx]
                
            elif action == "add":
                if idx != -1:
                    # Merge quantities if adding same item
                    items_list[idx]["quantity"] += quantity
                else:
                    # Add new entry (service will re-validate price later)
                    items_list.append({"variant_id": variant_id_str, "quantity": quantity})
                    
            elif action == "set":
                if idx == -1:
                    return ToolResult(success=False, error="Item not in draft to set quantity.")
                items_list[idx]["quantity"] = quantity
                
            else:
                return ToolResult(success=False, error="Invalid action.")

            # Re-save via service to ensure consistency and price refresh
            # Note: save_draft expects raw input format [{"variant_id":..., "quantity":...}]
            raw_items = [{"variant_id": it["variant_id"], "quantity": it["quantity"]} for it in items_list]
            
            new_draft = save_draft(
                db=db,
                conversation_id=conversation_id,
                items=raw_items,
                shipping_info=current_draft.get("shipping_info")
            )
            
            db.commit()

            return ToolResult(
                success=True,
                data={
                    "message": "Draft updated.",
                    "total_price": new_draft["total_price"],
                    "item_count": len(new_draft["items"])
                }
            )

        except Exception as e:
            db.rollback()
            return ToolResult(success=False, error=f"Update failed: {str(e)}")
