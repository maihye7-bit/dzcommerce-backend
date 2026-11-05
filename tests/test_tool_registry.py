"""Unit tests for the ToolRegistry."""
import uuid

import pytest
from app.agent.tools.base import BaseTool, ToolResult
from app.agent.tools.registry import ToolRegistry
from app.agent.tools.search_products import SearchProductsTool
from app.agent.tools.check_inventory import CheckInventoryTool
from app.agent.tools.get_price import GetPriceTool
from app.agent.tools.handoff_to_human import HandoffToHumanTool


class CapturingTool(BaseTool):
    name = "capturing"

    @property
    def description(self):
        return "Captures the execution context for tests."

    @property
    def input_schema(self):
        return {}

    async def execute(self, store_id, arguments, context=None):
        self.store_id = store_id
        self.arguments = arguments
        self.context = context
        return ToolResult(success=True)


class TestToolRegistry:
    def test_register_and_get(self):
        registry = ToolRegistry()
        tool = SearchProductsTool()
        registry.register(tool)
        assert registry.get("search_products") is tool

    def test_duplicate_registration_raises(self):
        registry = ToolRegistry()
        registry.register(SearchProductsTool())
        with pytest.raises(ValueError, match="already registered"):
            registry.register(SearchProductsTool())

    def test_list_tools(self):
        registry = ToolRegistry()
        registry.register(SearchProductsTool())
        registry.register(CheckInventoryTool())
        assert len(registry.list_tools()) == 2

    def test_get_tool_definitions_format(self):
        registry = ToolRegistry()
        registry.register(SearchProductsTool())
        defs = registry.get_tool_definitions()
        assert len(defs) == 1
        assert "name" in defs[0]
        assert "description" in defs[0]
        assert "parameters" in defs[0]

    def test_all_phase3_tools_registered(self):
        registry = ToolRegistry()
        registry.register(SearchProductsTool())
        registry.register(CheckInventoryTool())
        registry.register(GetPriceTool())
        registry.register(HandoffToHumanTool())
        names = {t.name for t in registry.list_tools()}
        assert names == {"search_products", "check_inventory", "get_price", "handoff_to_human"}

    def test_unknown_tool_returns_none(self):
        registry = ToolRegistry()
        assert registry.get("nonexistent_tool") is None

    @pytest.mark.asyncio
    async def test_aexecute_passes_through_caller_database_session(self, db_session):
        registry = ToolRegistry()
        tool = CapturingTool()
        registry.register(tool)
        context = {"db": db_session, "store_id": uuid.uuid4()}

        result = await registry.aexecute(
            tool_name=tool.name,
            arguments={},
            context=context,
        )

        assert result.success
        assert tool.context is context
        assert tool.context["db"] is db_session

    @pytest.mark.asyncio
    async def test_aexecute_requires_database_session(self):
        registry = ToolRegistry()
        registry.register(CapturingTool())

        with pytest.raises(RuntimeError, match="Database session missing"):
            await registry.aexecute(
                tool_name="capturing",
                arguments={},
                context={"store_id": uuid.uuid4()},
            )
