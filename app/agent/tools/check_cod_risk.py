"""
check_cod_risk tool: Evaluates the Cash-on-Delivery risk for a customer.
Used by the Sales Agent to decide whether to ask for prepayment or confirm COD.
"""

import uuid
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
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

        except SQLAlchemyError:
            raise
        except Exception as e:
            return ToolResult(
                success=False, error=f"Failed to check COD risk: {str(e)}"
            )
