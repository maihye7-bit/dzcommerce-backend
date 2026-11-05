"""
get_lost_sales_opportunities tool: Lists open sales opportunities.
Helps the agent or merchant identify customers who need follow-up.
"""

import uuid
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agent.tools.base import BaseTool, ToolResult
from app.services import lost_sales_service


class GetLostSalesOpportunitiesTool(BaseTool):
    @property
    def name(self) -> str:
        return "get_lost_sales_opportunities"

    @property
    def description(self) -> str:
        return (
            "List open sales opportunities that need follow-up. "
            "Includes abandoned drafts, out-of-stock inquiries, and price questions. "
            "Use this to proactively reach out to interested customers."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max opportunities to return (default 10)",
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
            db: Session = context["db"]
            limit = int(args.get("limit", 10))

            opportunities = lost_sales_service.get_open_opportunities(
                db=db, store_id=store_id, limit=limit
            )

            return ToolResult(
                success=True,
                data={
                    "opportunities": [
                        {
                            "id": str(opp.id),
                            "type": opp.opportunity_type,
                            "status": opp.status,
                            "customer_id": str(opp.customer_id),
                            "related_order_id": (
                                str(opp.related_order_id)
                                if opp.related_order_id
                                else None
                            ),
                            "notes": opp.notes,
                            "created_at": (
                                opp.created_at.isoformat() if opp.created_at else None
                            ),
                        }
                        for opp in opportunities
                    ],
                    "count": len(opportunities),
                },
            )

        except SQLAlchemyError:
            raise
        except Exception as e:
            return ToolResult(
                success=False, error=f"Failed to get opportunities: {str(e)}"
            )
