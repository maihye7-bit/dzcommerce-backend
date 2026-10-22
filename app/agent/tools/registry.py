"""
ToolRegistry: Central registry for all agent tools.
Tools share the database session owned by the caller.
"""
import uuid
from typing import Any, Dict, List
from app.agent.tools.base import BaseTool, ToolResult

class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        name = tool.name
        if name in self._tools:
            raise ValueError(f"Tool '{name}' is already registered")
        self._tools[name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list_tools(self) -> List[BaseTool]:
        return list(self._tools.values())

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            }
            for tool in self._tools.values()
        ]

    def get_tool(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def get_tools_schema(self) -> List[Dict[str, Any]]:
        schemas = []
        for tool in self._tools.values():
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.input_schema,
                    },
                }
            )
        return schemas

    async def aexecute(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        context: Dict[str, Any],
    ) -> ToolResult:
        """
        Execute a tool using the database session provided by the caller.
        """
        tool = self.get_tool(tool_name)
        if not tool:
            return ToolResult(
                success=False,
                error=f"Tool '{tool_name}' not found",
                error_code="TOOL_ERROR",
            )

        db = context.get("db")
        if db is None:
            raise RuntimeError("Database session missing in ToolContext")

        store_id_raw = context.get("store_id")
        
        if not store_id_raw:
            return ToolResult(
                success=False,
                error="Missing required context (store_id)",
                error_code="TOOL_ERROR",
            )

        # Handle both UUID and string formats securely
        if isinstance(store_id_raw, uuid.UUID):
            store_id = store_id_raw
        else:
            store_id = uuid.UUID(str(store_id_raw))

        return await tool.execute(
            store_id=store_id,
            arguments=arguments,
            context=context,
        )
