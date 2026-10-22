import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.agent.tools.base import BaseTool, ToolResult
from app.models.human_handoff import HumanHandoff

VALID_REASONS = {
    "customer_requested_human",
    "agent_uncertainty",
    "outside_permissions",
    "complaint",
    "complex_return",
    "exceptional_order",
}


class HandoffToHumanTool(BaseTool):
    @property
    def name(self) -> str:
        return "handoff_to_human"

    @property
    def description(self) -> str:
        return "Transfer the conversation to a human operator."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "reason": {"type": "string"},
                "summary": {"type": "string"},
                "suggested_action": {"type": "string"},
            },
            "required": ["reason", "summary"],
        }

    async def execute(
        self,
        store_id: uuid.UUID,
        arguments: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        try:
            args = self.validate_arguments(arguments)
            reason = args.get("reason", "")
            if reason not in VALID_REASONS:
                return ToolResult(
                    success=False,
                    error=f"Invalid reason. Must be one of: {sorted(VALID_REASONS)}",
                )
            db: Session = context["db"]
            conversation_id = context.get("conversation_id")
            customer_id = context.get("customer_id")
            if not conversation_id or not customer_id:
                return ToolResult(
                    success=False, error="Missing conversation_id or customer_id"
                )
            handoff = HumanHandoff(
                store_id=store_id,
                conversation_id=conversation_id,
                customer_id=customer_id,
                reason=reason,
                summary=args.get("summary", "No summary provided"),
                suggested_action=args.get("suggested_action"),
            )
            db.add(handoff)
            db.flush()
            db.refresh(handoff)
            return ToolResult(
                success=True,
                data={
                    "handoff_id": str(handoff.id),
                    "reason": handoff.reason,
                    "message": "Conversation transferred to a human operator.",
                },
            )
        except Exception:
            raise
