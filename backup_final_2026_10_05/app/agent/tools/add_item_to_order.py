"""
add_item_to_order tool: adds a product to an order draft.
Price is ALWAYS taken from the authoritative product record.
The Agent can NEVER override the price.
"""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.agent.tools.base import BaseTool, ToolResult
from app.services import order_service
from app.services.exceptions import NotFoundError, OrderNotModifiableError


class AddItemToOrderTool(BaseTool):
    @property
    def name(self) -> str:
        return "add_item_to_order"

    @property
    def description(self) -> str:
        return (
            "Add a product to an order draft. "
            "The price is always taken from the product catalog - "
            "you cannot set or override the price. "
            "Only works on DRAFT orders."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "UUID of the order draft",
                },
                "product_id": {
                    "type": "string",
                    "description": "UUID of the product to add",
                },
                "quantity": {
                    "type": "integer",
                    "description": "Quantity (must be positive)",
                    "minimum": 1,
                },
            },
            "required": ["order_id", "product_id", "quantity"],
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

            order_id = uuid.UUID(args["order_id"])
            product_id = uuid.UUID(args["product_id"])
            quantity = int(args["quantity"])

            item = order_service.add_item(
                db=db,
                store_id=store_id,
                order_id=order_id,
                product_id=product_id,
                quantity=quantity,
            )

            return ToolResult(
                success=True,
                data={
                    "item_id": str(item.id),
                    "product_name": item.product_name,
                    "quantity": item.quantity,
                    "unit_price": str(item.unit_price),
                    "message": f"Added {item.quantity} x {item.product_name}",
                },
            )

        except NotFoundError as e:
            return ToolResult(success=False, error=str(e))
        except OrderNotModifiableError as e:
            return ToolResult(success=False, error=str(e))
        except (ValueError, KeyError) as e:
            return ToolResult(success=False, error="Invalid arguments")
        except Exception:
            return ToolResult(success=False, error="Failed to add item to order")
