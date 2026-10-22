"""
ToolRegistry: Central registry for all agent tools.
FIXED: Tools now use isolated READ-ONLY sessions to prevent poisoning from main transaction errors.
"""
import uuid
from typing import Any, Dict, List
from sqlalchemy.orm import Session
from app.agent.tools.base import BaseTool, ToolResult
from app.database import SessionLocal # Import session factory

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
        Execute a tool asynchronously with an ISOLATED SESSION.
        This ensures that even if the main 'db' session is poisoned by a previous error,
        the tool can still read data successfully using a fresh connection.
        """
        tool = self.get_tool(tool_name)
        if not tool:
            return ToolResult(success=False, error=f"Tool '{tool_name}' not found")

        try:
            store_id_raw = context.get("store_id")
            
            if not store_id_raw:
                return ToolResult(success=False, error="Missing required context (store_id)")

            # Handle both UUID and string formats securely
            if isinstance(store_id_raw, uuid.UUID):
                store_id = store_id_raw
            else:
                store_id = uuid.UUID(str(store_id_raw))

            # CRITICAL FIX: Create a NEW session specifically for this tool execution
            # This isolates the tool from any transaction state issues in the main 'db' session.
            tool_db = SessionLocal()
            try:
                # Inject the new session into the context passed to the tool
                tool_context = {**context, "db": tool_db}
                
                result = await tool.execute(
                    store_id=store_id,
                    arguments=arguments,
                    context=tool_context,
                )
                return result
            finally:
                # Always close the isolated session to free up resources
                tool_db.close()

        except Exception as e:
            return ToolResult(success=False, error=str(e))
