"""Agent tools package - Auto-registers all available tools."""
from app.agent.tools.registry import ToolRegistry
from app.agent.tools.search_products import SearchProductsTool
from app.agent.tools.get_product_details import GetProductDetailsTool
from app.agent.tools.check_inventory import CheckInventoryTool
from app.agent.tools.create_order_draft import CreateOrderDraftTool
from app.agent.tools.update_order_draft import UpdateOrderDraftTool
from app.agent.tools.confirm_order import ConfirmOrderTool # NEW IMPORT

# Create global registry instance
tool_registry = ToolRegistry()

# Register tools automatically on import
_tools_to_register = [
    SearchProductsTool(),
    GetProductDetailsTool(),
    CheckInventoryTool(),
    CreateOrderDraftTool(),
    UpdateOrderDraftTool(),
    ConfirmOrderTool(), # NEW REGISTRATION
]

for tool in _tools_to_register:
    if not tool_registry.get(tool.name):
        tool_registry.register(tool)

__all__ = ["tool_registry"]
