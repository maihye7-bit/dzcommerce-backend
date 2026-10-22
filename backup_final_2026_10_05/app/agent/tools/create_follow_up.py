"""
create_follow_up_opportunity tool: Manually creates a sales opportunity.
Used when the agent detects interest but no immediate purchase.
"""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.agent.tools.base import BaseTool, ToolResult
from app.models.sales_opportunity import OpportunityType
from app.services import lost_sales_service


class CreateFollowUpOpportunityTool(BaseTool):
    @property
    def name(self) -> str:
        return "create_follow_up_opportunity"

    @property
    def description(self) -> str:
        return (
            "Create a new sales opportunity for follow-up. "
            "Use this when a customer shows interest (asks price, checks stock) "
            "but doesn't complete the purchase immediately."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "Customer UUID"},
                "opportunity_type": {
                    "type": "string",
                    "enum": [
                        "abandoned_draft",
                        "out_of_stock_inquiry",
                        "price_inquiry",
                        "general_interest",
                    ],
                    "description": "Type of opportunity",
                },
                "notes": {
                    "type": "string",
                    "description": "Context notes for the follow-up",
                },
                "related_product_id": {
                    "type": "string",
                    "description": "Product UUID (optional)",
                },
            },
            "required": ["customer_id", "opportunity_type"],
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

            customer_id = uuid.UUID(args["customer_id"])
            opp_type = OpportunityType(args["opportunity_type"])
            related_product_id = (
                uuid.UUID(args["related_product_id"])
                if args.get("related_product_id")
                else None
            )

            opp = lost_sales_service.create_opportunity(
                db=db,
                store_id=store_id,
                customer_id=customer_id,
                opp_type=opp_type,
                related_product_id=related_product_id,
                notes=args.get("notes"),
            )

            return ToolResult(
                success=True,
                data={
                    "opportunity_id": str(opp.id),
                    "type": opp.opportunity_type,
                    "message": "Follow-up opportunity created successfully.",
                },
            )

        except ValueError as e:
            return ToolResult(success=False, error=f"Invalid argument: {str(e)}")
        except Exception as e:
            return ToolResult(
                success=False, error=f"Failed to create opportunity: {str(e)}"
            )
