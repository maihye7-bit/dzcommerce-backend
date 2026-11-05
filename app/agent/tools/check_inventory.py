"""
Check Inventory Tool: Verifies availability for a specific variant.
Fast lookup before creating drafts or confirming orders.
"""
import uuid
from typing import Any
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from app.agent.tools.base import BaseTool, ToolResult
from app.models.inventory import InventoryItem


class CheckInventoryTool(BaseTool):

    @property
    def name(self) -> str:
        return "check_inventory"

    @property
    def description(self) -> str:
        return (
            "Check if a specific quantity of a product variant is currently in stock. "
            "Returns boolean availability and exact remaining count."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "variant_id": {
                    "type": "string",
                    "description": "The UUID of the product variant.",
                },
                "quantity": {
                    "type": "integer",
                    "description": "Desired quantity to check.",
                },
            },
            "required": ["variant_id", "quantity"],
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
            variant_id = uuid.UUID(args["variant_id"])
            requested_qty = int(args["quantity"])

            if requested_qty <= 0:
                return ToolResult(success=False, error="Quantity must be positive.")

            # Find inventory item linked to this variant AND belonging to this store's products
            # Note: We rely on the fact that InventoryItem links to Variant, which links to Product, which has Store_ID.
            # For strict isolation, we should join through Product.
            from app.models.product import ProductVariant, Product
            
            inv_item = (
                db.query(InventoryItem)
                .join(ProductVariant, InventoryItem.variant_id == ProductVariant.id)
                .join(Product, ProductVariant.product_id == Product.id)
                .filter(
                    InventoryItem.variant_id == variant_id,
                    Product.store_id == store_id
                )
                .first()
            )

            available = inv_item.quantity if inv_item else 0
            is_sufficient = available >= requested_qty

            return ToolResult(
                success=True,
                data={
                    "variant_id": str(variant_id),
                    "requested_quantity": requested_qty,
                    "available_quantity": available,
                    "is_available": is_sufficient,
                },
            )

        except SQLAlchemyError:
            raise
        except Exception as e:
            return ToolResult(success=False, error=f"Inventory check failed: {str(e)}")
