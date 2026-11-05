"""
get_customer_context tool: retrieves structured customer context.
Uses CustomerContextService internally. Never accesses DB directly.
"""

import uuid
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agent.tools.base import BaseTool, ToolResult
from app.services import customer_context_service
from app.services.exceptions import NotFoundError


class GetCustomerContextTool(BaseTool):
    @property
    def name(self) -> str:
        return "get_customer_context"

    @property
    def description(self) -> str:
        return (
            "Read the current customer's verified order history and saved "
            "preferences. Use this for order-history questions or when a relevant "
            "stored preference could improve a requested recommendation; do not "
            "call it on every turn. The customer and store are resolved by the server."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "include_conversations": {
                    "type": "boolean",
                    "description": "Whether to include recent conversations",
                },
                "recent_orders_limit": {
                    "type": "integer",
                    "description": "Max number of recent orders to include (default 5, max 20)",
                },
            },
        }

    async def execute(
        self,
        store_id: uuid.UUID,
        arguments: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        try:
            args = self.validate_arguments(arguments)

            # customer_id comes from conversation context, NOT from LLM
            customer_id = context.get("customer_id") if context else None
            if not customer_id:
                return ToolResult(
                    success=False,
                    error="No customer context available",
                )

            db: Session = context["db"]
            limit = args.get("recent_orders_limit", 5)
            if (
                isinstance(limit, bool)
                or not isinstance(limit, int)
                or not 1 <= limit <= 20
            ):
                return ToolResult(
                    success=False,
                    error="Invalid arguments",
                    error_code="VALIDATION_ERROR",
                )

            result = customer_context_service.get_customer_context(
                db=db,
                store_id=store_id,
                customer_id=customer_id,
                recent_orders_limit=limit,
            )

            return ToolResult(success=True, data=result)

        except NotFoundError:
            return ToolResult(success=False, error="Customer not found")
        except (ValueError, TypeError) as e:
            return ToolResult(success=False, error="Invalid arguments")
        except SQLAlchemyError:
            raise
        except Exception:
            return ToolResult(
                success=False, error="Failed to retrieve customer context"
            )
