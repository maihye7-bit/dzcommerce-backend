"""
cancel_order tool: cancels an order.
Only allowed from DRAFT or CONFIRMED states.
If confirmed, restores inventory.
"""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.agent.tools.base import BaseTool, ToolResult
from app.services import order_service
from app.services.exceptions import NotFoundError, OrderStateError


class CancelOrderTool(BaseTool):
    @property
    def name(self) -> str:
        return "cancel_order"

    @property
    def description(self) -> str:
        return (
            "Cancel an order. Only allowed from DRAFT or CONFIRMED states. "
            "If the order was already confirmed, inventory will be restored. "
            "This action is idempotent."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "UUID of the order to cancel",
                },
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

            order = order_service.cancel_order(db, store_id, order_id)

            return ToolResult(
                success=True,
                data={
                    "order_id": str(order.id),
                    "status": order.status.value,
                    "message": "Order cancelled.",
                },
            )

        except NotFoundError as e:
            return ToolResult(success=False, error=str(e))
        except OrderStateError as e:
            return ToolResult(success=False, error=str(e))
        except (ValueError, KeyError):
            return ToolResult(success=False, error="Invalid order_id format")
        except Exception:
            return ToolResult(success=False, error="Failed to cancel order")
