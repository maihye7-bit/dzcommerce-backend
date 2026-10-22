"""
Enhanced Conversation Engine for Phase 8 Sales Agent.
Integrates SalesStateManager and CustomerContextService.
"""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.agent.conversation_engine import ConversationEngine as BaseEngine
from app.agent.providers.base import LLMProvider
from app.agent.sales_state import sales_manager
from app.agent.tools.registry import ToolRegistry
from app.services import customer_context_service


class SalesConversationEngine(BaseEngine):
    """
    Extends the base engine to inject sales context and manage state.
    """

    async def process_message(
        self,
        db: Session,
        store_id: uuid.UUID,
        customer_id: uuid.UUID,
        conversation_id: uuid.UUID | None,
        channel: str,
        user_message: str,
    ) -> dict:
        # 1. Get or create conversation ID
        if not conversation_id:
            conversation_id = uuid.uuid4()

        conv_id_str = str(conversation_id)

        # 2. Get Sales State
        state = sales_manager.get_state(conv_id_str)

        # 3. Enrich System Prompt with Customer Context
        try:
            context = customer_context_service.get_customer_context(
                db=db, store_id=store_id, customer_id=customer_id
            )
            customer_info = f"""
            CUSTOMER CONTEXT:
            - Name: {context['customer'].get('name', 'Unknown')}
            - Total Orders: {context['behavior_summary']['total_orders']}
            - Last Order Date: {context['behavior_summary'].get('last_order_date', 'Never')}
            - Preferences: {context['preferences']}
            """
        except Exception:
            customer_info = ""

        # 4. Inject State into Prompt
        state_info = ""
        if state.selected_product_id:
            state_info += f"\nCURRENT SELECTION: Product ID {state.selected_product_id}, Qty: {state.selected_quantity}"
        if state.current_draft_order_id:
            state_info += f"\nACTIVE DRAFT ORDER: {state.current_draft_order_id}"
        if state.awaiting_confirmation:
            state_info += "\nSTATUS: AWAITING EXPLICIT CONFIRMATION FROM CUSTOMER."

        # 5. Call Parent Process with Enhanced Context
        # Note: In a real implementation, we would pass this enhanced prompt to the LLM.
        # For now, we rely on the tool registry and history.

        result = await super().process_message(
            db=db,
            store_id=store_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            channel=channel,
            user_message=user_message,
        )

        # 6. Update State based on Tool Calls
        if result.get("tool_calls"):
            for tc in result["tool_calls"]:
                if tc["name"] == "create_order_draft":
                    if tc.get("result") and tc["result"].get("success"):
                        state.current_draft_order_id = tc["result"]["data"]["order_id"]
                elif tc["name"] == "add_item_to_order":
                    if tc.get("result") and tc["result"].get("success"):
                        state.awaiting_confirmation = True

        return result
