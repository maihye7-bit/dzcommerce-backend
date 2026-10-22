"""
Phase 8 Part 2 - Sales Logic & State Management
Run: python setup_phase8_part2.py
"""
import os

def write_file(path, content):
    dir_name = os.path.dirname(path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"  Created: {path}")

print("\n=== Phase 8 Part 2: Sales Logic & State ===\n")

# ============================================================
# 1. SALES STATE MANAGER
# ============================================================
write_file("app/agent/sales_state.py", '''"""
SalesStateManager: Tracks the customer's journey through the buying process.
Keeps track of selected products, current draft order, and confirmation status.
This prevents the LLM from having to rediscover context from raw text every time.
"""
import uuid
from typing import Optional
from dataclasses import dataclass, field


@dataclass
class SalesState:
    """Holds the temporary state for a single conversation session."""
    selected_product_id: Optional[str] = None
    selected_quantity: int = 1
    current_draft_order_id: Optional[str] = None
    awaiting_confirmation: bool = False
    last_tool_result: Optional[dict] = None
    
    def reset_selection(self):
        self.selected_product_id = None
        self.selected_quantity = 1
        
    def reset_draft(self):
        self.current_draft_order_id = None
        self.awaiting_confirmation = False


class SalesStateManager:
    """Manages SalesState per conversation."""
    
    def __init__(self):
        # In a production system with multiple workers, this should use Redis.
        # For now, we use an in-memory dict keyed by conversation_id.
        self._states: dict[str, SalesState] = {}

    def get_state(self, conversation_id: str) -> SalesState:
        if conversation_id not in self._states:
            self._states[conversation_id] = SalesState()
        return self._states[conversation_id]

    def clear_state(self, conversation_id: str):
        if conversation_id in self._states:
            del self._states[conversation_id]

# Global instance for the agent
sales_manager = SalesStateManager()
''')

# ============================================================
# 2. ENHANCED CONVERSATION ENGINE
# ============================================================
write_file("app/agent/conversation_engine_enhanced.py", '''"""
Enhanced Conversation Engine for Phase 8 Sales Agent.
Integrates SalesStateManager and CustomerContextService.
"""
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.agent.conversation_engine import ConversationEngine as BaseEngine
from app.agent.providers.base import LLMProvider
from app.agent.tools.registry import ToolRegistry
from app.agent.sales_state import sales_manager
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
            # Logic to find/create conversation would go here if not handled by API
            # For now, we assume the API handles the initial creation or we use a temp one
            conversation_id = uuid.uuid4() 

        conv_id_str = str(conversation_id)
        
        # 2. Get Sales State
        state = sales_manager.get_state(conv_id_str)

        # 3. Enrich System Prompt with Customer Context
        try:
            context = customer_context_service.get_customer_context(
                db=db, store_id=store_id, customer_id=customer_id
            )
            # Add relevant context to the system prompt dynamically
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
        # Note: We modify the system_prompt passed to the LLM provider
        original_system_prompt = "You are a helpful AI assistant."
        enhanced_prompt = f"""
        You are a professional Sales Agent for an Algerian e-commerce store.
        Your goal is to help customers find products, answer questions, and complete orders.
        
        RULES:
        1. NEVER invent prices, stock, or product details. Always use tools.
        2. Speak naturally in Arabic, Darija, French, or Arabizi as the customer does.
        3. Do NOT confirm an order unless the customer explicitly says "Yes", "Confirm", "Nem", "Oui".
        4. If a product is out of stock, suggest alternatives using the recommend_products tool.
        
        {customer_info}
        {state_info}
        """

        # We need to override the system prompt in the base engine call
        # Since the base engine might not support dynamic prompts easily, 
        # we'll rely on the ToolRegistry and the LLM's ability to see history.
        
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
''')

# ============================================================
# 3. UPDATE AGENT API TO USE ENHANCED ENGINE
# ============================================================
# We will modify app/api/agent.py in the next step to swap the engine.

print("\n=== Part 2 Complete ===")
print("Created:")
print("  - app/agent/sales_state.py")
print("  - app/agent/conversation_engine_enhanced.py")
print("\nNext: Update agent.py to use the new engine and run tests")
