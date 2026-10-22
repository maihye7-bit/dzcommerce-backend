import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.agent.tools.base import BaseTool, ToolResult
from app.models.store import Store


class StoreInfoTool(BaseTool):
    @property
    def name(self) -> str:
        return "store_info"

    @property
    def description(self) -> str:
        return "Read verified address and delivery information for the current store."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        }

    async def execute(
        self,
        store_id: uuid.UUID,
        arguments: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        del arguments
        if not context or not isinstance(context.get("db"), Session):
            return ToolResult(
                success=False,
                error="Store information context is unavailable.",
                error_code="TOOL_ERROR",
            )
        store = (
            context["db"]
            .query(Store)
            .filter(Store.id == store_id)
            .one_or_none()
        )
        if store is None:
            return ToolResult(
                success=False,
                error="Store not found.",
                error_code="NOT_FOUND",
            )
        return ToolResult(
            success=True,
            data={
                "store_name": store.name,
                "address": store.address,
                "delivery_policy_text": store.delivery_policy_text,
                "served_wilayas": store.served_wilayas,
            },
        )
