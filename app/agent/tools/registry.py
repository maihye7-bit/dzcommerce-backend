"""
ToolRegistry: Central registry for all agent tools.
Tools share the database session owned by the caller.
"""
import logging
import uuid
from typing import Any, Dict, List

from sqlalchemy.exc import SQLAlchemyError

from app.agent.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class ToolSessionUnusableError(RuntimeError):
    """Raised when a tool cannot recover its database savepoint."""


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

        transaction_before = _transaction_state(db)
        try:
            savepoint = db.begin_nested()
        except SQLAlchemyError as exc:
            _log_database_failure(
                tool_name,
                exc,
                transaction_before,
                _transaction_state(db),
                recovery_succeeded=False,
            )
            raise ToolSessionUnusableError(
                "Could not establish a savepoint for tool execution"
            ) from exc

        try:
            result = await tool.execute(
                store_id=store_id,
                arguments=arguments,
                context=context,
            )
            if not db.is_active:
                raise ToolSessionUnusableError(
                    "The database session became inactive during tool execution"
                )
            savepoint.commit()
        except Exception as exc:
            recovery_succeeded = False
            try:
                if savepoint.is_active:
                    savepoint.rollback()
                    recovery_succeeded = db.is_active
            except SQLAlchemyError:
                recovery_succeeded = False

            if isinstance(exc, (SQLAlchemyError, ToolSessionUnusableError)):
                _log_database_failure(
                    tool_name,
                    exc,
                    transaction_before,
                    _transaction_state(db),
                    recovery_succeeded=recovery_succeeded,
                )
                if not recovery_succeeded:
                    raise ToolSessionUnusableError(
                        "Could not recover the database session after tool failure"
                    ) from exc
                return ToolResult(
                    success=False,
                    error=(
                        "A temporary database error occurred; no result was "
                        "produced. This is not a NO_RESULTS result."
                    ),
                    error_code="DATABASE_ERROR",
                )
            if not recovery_succeeded:
                raise ToolSessionUnusableError(
                    "Could not recover the database session after tool failure"
                ) from exc
            raise

        logger.debug(
            "agent_tool_execution_succeeded tool=%s "
            "transaction_before=%s transaction_after=%s",
            tool_name,
            transaction_before,
            _transaction_state(db),
        )
        return result


def _transaction_state(db: Any) -> str:
    return (
        f"active={db.is_active},in_transaction={db.in_transaction()},"
        f"nested={db.get_nested_transaction() is not None}"
    )


def _log_database_failure(
    tool_name: str,
    exc: Exception,
    transaction_before: str,
    transaction_after: str,
    *,
    recovery_succeeded: bool,
) -> None:
    original = getattr(exc, "orig", None)
    sqlstate = getattr(original, "pgcode", None) or getattr(
        original, "sqlstate", None
    )
    logger.error(
        "agent_tool_database_failure tool=%s transaction_before=%s "
        "transaction_after=%s exception_class=%s dbapi_exception_class=%s "
        "sqlstate=%s savepoint_recovery_succeeded=%s",
        tool_name,
        transaction_before,
        transaction_after,
        type(exc).__name__,
        type(original).__name__ if original is not None else "unavailable",
        sqlstate or "unavailable",
        recovery_succeeded,
    )
