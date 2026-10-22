"""
Phase 9 Part 2 - Smart Follow-up & Risk Tools
Run: python setup_phase9_part2.py
"""
import os

def write_file(path, content):
    dir_name = os.path.dirname(path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"  Created: {path}")

print("\n=== Phase 9 Part 2: Smart Follow-up Tools ===\n")

# ============================================================
# 1. CHECK COD RISK TOOL
# ============================================================
write_file("app/agent/tools/check_cod_risk.py", '''"""
check_cod_risk tool: Evaluates the Cash-on-Delivery risk for a customer.
Used by the Sales Agent to decide whether to ask for prepayment or confirm COD.
"""
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.agent.tools.base import BaseTool, ToolResult
from app.services import cod_intelligence_service


class CheckCODRiskTool(BaseTool):
    @property
    def name(self) -> str:
        return "check_cod_risk"

    @property
    def description(self) -> str:
        return (
            "Check the Cash-on-Delivery (COD) risk score for a specific customer. "
            "Returns a score from 0 (Low Risk/Trustworthy) to 100 (High Risk). "
            "Use this before confirming large orders or when unsure about a new customer."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "UUID of the customer to evaluate",
                },
            },
            "required": ["customer_id"],
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

            # Calculate fresh risk score
            risk = cod_intelligence_service.calculate_risk_score(
                db=db, store_id=store_id, customer_id=customer_id
            )

            # Determine risk level label
            if risk.risk_score < 30:
                level = "LOW"
            elif risk.risk_score < 70:
                level = "MEDIUM"
            else:
                level = "HIGH"

            return ToolResult(
                success=True,
                data={
                    "customer_id": str(customer_id),
                    "risk_score": risk.risk_score,
                    "risk_level": level,
                    "total_orders": risk.total_orders,
                    "rejected_orders": risk.rejected_orders,
                    "message": f"Customer COD risk is {level} ({risk.risk_score}/100).",
                },
            )

        except Exception as e:
            return ToolResult(success=False, error=f"Failed to check COD risk: {str(e)}")
''')

# ============================================================
# 2. GET LOST SALES OPPORTUNITIES TOOL
# ============================================================
write_file("app/agent/tools/get_lost_sales.py", '''"""
get_lost_sales_opportunities tool: Lists open sales opportunities.
Helps the agent or merchant identify customers who need follow-up.
"""
import uuid
from typing import Any

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
                            "related_order_id": str(opp.related_order_id) if opp.related_order_id else None,
                            "notes": opp.notes,
                            "created_at": opp.created_at.isoformat() if opp.created_at else None,
                        }
                        for opp in opportunities
                    ],
                    "count": len(opportunities),
                },
            )

        except Exception as e:
            return ToolResult(success=False, error=f"Failed to get opportunities: {str(e)}")
''')

# ============================================================
# 3. CREATE FOLLOW-UP OPPORTUNITY TOOL
# ============================================================
write_file("app/agent/tools/create_follow_up.py", '''"""
create_follow_up_opportunity tool: Manually creates a sales opportunity.
Used when the agent detects interest but no immediate purchase.
"""
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.agent.tools.base import BaseTool, ToolResult
from app.services import lost_sales_service
from app.models.sales_opportunity import OpportunityType


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
                    "enum": ["abandoned_draft", "out_of_stock_inquiry", "price_inquiry", "general_interest"],
                    "description": "Type of opportunity",
                },
                "notes": {"type": "string", "description": "Context notes for the follow-up"},
                "related_product_id": {"type": "string", "description": "Product UUID (optional)"},
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
            related_product_id = uuid.UUID(args["related_product_id"]) if args.get("related_product_id") else None

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
            return ToolResult(success=False, error=f"Failed to create opportunity: {str(e)}")
''')

print("\n=== Part 2 Complete ===")
print("Created:")
print("  - app/agent/tools/check_cod_risk.py")
print("  - app/agent/tools/get_lost_sales.py")
print("  - app/agent/tools/create_follow_up.py")
print("\nNext: Update agent.py and run tests")
