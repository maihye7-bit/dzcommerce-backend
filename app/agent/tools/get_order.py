"""
get_order tool: retrieves order details including items and totals.
"""

import uuid
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agent.tools.base import BaseTool, ToolResult
from app.models.order import OrderItem
from app.services import order_service
from app.services.exceptions import NotFoundError


class GetOrderTool(BaseTool):
    @property
    def name(self) -> str:
        return "get_order"

    @property
    def description(self) -> str:
        return (
            "Get the details of an order including its items, quantities, "
            "prices, total, and current status."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "UUID of the order"},
            },
            "required": ["order_id"],
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

            order = order_service.get_order(db, store_id, order_id)
            items = db.query(OrderItem).filter(OrderItem.order_id == order.id).all()

            return ToolResult(
                success=True,
                data={
                    "order_id": str(order.id),
                    "status": order.status.value,
                    "total_amount": str(order.total_amount),
                    "currency": order.currency,
                    "created_at": (
                        order.created_at.isoformat() if order.created_at else None
                    ),
                    "items": [
                        {
                            "item_id": str(item.id),
                            "product_name": item.product_name,
                            "quantity": item.quantity,
                            "unit_price": str(item.unit_price),
                            "subtotal": str(item.unit_price * item.quantity),
                        }
                        for item in items
                    ],
                },
            )

        except NotFoundError as e:
            return ToolResult(success=False, error=str(e))
        except (ValueError, KeyError):
            return ToolResult(success=False, error="Invalid order_id format")
        except SQLAlchemyError:
            raise
        except Exception:
            return ToolResult(success=False, error="Failed to get order")
