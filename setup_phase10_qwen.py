"""
Phase 10 - Real Qwen LLM Provider + Token/Cost/Context Foundation
Run: python setup_phase10_qwen.py
"""
import os

def write_file(path, content):
    dir_name = os.path.dirname(path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"  Created/Updated: {path}")

print("\n=== Phase 10: Qwen Integration & Billing Foundation ===\n")

# ============================================================
# 1. CENTRALIZED CONFIGURATION
# ============================================================
write_file("app/core/config.py", '''"""
Centralized configuration for the application.
Reads from environment variables with safe defaults.
"""
import os

# Agent Provider Selection
AGENT_PROVIDER = os.getenv("AGENT_PROVIDER", "mock")  # "mock" or "qwen"

# Qwen / DashScope Configuration
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen-max")
# DashScope OpenAI-compatible endpoint (International)
QWEN_BASE_URL = os.getenv("QWEN_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
QWEN_TIMEOUT = int(os.getenv("QWEN_TIMEOUT", "60"))

# Context Management
QWEN_RECENT_MESSAGES_LIMIT = int(os.getenv("QWEN_RECENT_MESSAGES_LIMIT", "10"))
QWEN_MAX_CONTEXT_TOKENS = int(os.getenv("QWEN_MAX_CONTEXT_TOKENS", "32000"))
''')

# ============================================================
# 2. PRICING CONFIGURATION (Provider-Agnostic)
# ============================================================
write_file("app/services/pricing_config.py", '''"""
Provider-agnostic pricing configuration.
Prices are per 1,000,000 tokens (USD).
This can later be moved to a database table for dynamic updates.
"""
from decimal import Decimal

# Example pricing structure (subject to change by providers)
MODEL_PRICING = {
    "qwen": {
        "qwen-max": {"input": Decimal("2.00"), "output": Decimal("6.00")},
        "qwen-plus": {"input": Decimal("0.80"), "output": Decimal("2.00")},
        "qwen-turbo": {"input": Decimal("0.30"), "output": Decimal("0.60")},
    },
    "mock": {
        "mock-model": {"input": Decimal("0.00"), "output": Decimal("0.00")},
    }
}

def get_pricing(provider: str, model: str) -> dict:
    """Get pricing for a specific provider and model."""
    provider_pricing = MODEL_PRICING.get(provider, {})
    return provider_pricing.get(model, {"input": Decimal("0.00"), "output": Decimal("0.00")})

def calculate_cost(provider: str, model: str, input_tokens: int, output_tokens: int) -> Decimal:
    """Calculate estimated cost for a request."""
    pricing = get_pricing(provider, model)
    input_cost = (Decimal(input_tokens) / Decimal("1000000")) * pricing["input"]
    output_cost = (Decimal(output_tokens) / Decimal("1000000")) * pricing["output"]
    return input_cost + output_cost
''')

# ============================================================
# 3. AI USAGE EVENT MODEL (Billing Foundation)
# ============================================================
write_file("app/models/ai_usage_event.py", '''"""
AIUsageEvent: Tracks LLM usage, tokens, and costs for billing and analytics.
Provider-agnostic foundation for future SaaS billing.
"""
import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Integer, Numeric, DateTime, ForeignKey, func, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class AIUsageEvent(Base):
    __tablename__ = "ai_usage_events"
    __table_args__ = (
        Index("ix_ai_usage_store", "store_id"),
        Index("ix_ai_usage_provider", "provider"),
        Index("ix_ai_usage_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    
    provider: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g., "qwen", "openai", "mock"
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    
    estimated_cost: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0.00"))
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
''')

# ============================================================
# 4. USAGE SERVICE
# ============================================================
write_file("app/services/usage_service.py", '''"""
UsageService: Records AI usage events and calculates costs.
"""
import uuid
import time
from decimal import Decimal
from sqlalchemy.orm import Session
from app.models.ai_usage_event import AIUsageEvent
from app.services.pricing_config import calculate_cost

def record_usage(
    db: Session,
    store_id: uuid.UUID,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
    conversation_id: uuid.UUID | None = None,
) -> AIUsageEvent:
    """Record an AI usage event and calculate estimated cost."""
    total_tokens = input_tokens + output_tokens
    cost = calculate_cost(provider, model, input_tokens, output_tokens)

    event = AIUsageEvent(
        store_id=store_id,
        conversation_id=conversation_id,
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        estimated_cost=cost,
        latency_ms=latency_ms,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event
''')

# ============================================================
# 5. CONVERSATION CONTEXT BUILDER
# ============================================================
write_file("app/agent/context_builder.py", '''"""
ConversationContextBuilder: Constructs deliberate, bounded context for the LLM.
Prevents sending unlimited history and ensures authoritative facts are included.
"""
import uuid
from sqlalchemy.orm import Session
from app.agent.providers.base import LLMMessage
from app.models.conversation import Message
from app.models.order import Order, OrderStatus
from app.services import customer_context_service
from app.core.config import QWEN_RECENT_MESSAGES_LIMIT

SYSTEM_PROMPT = """أنت موظف مبيعات ذكي (AI Commerce Employee) لمتجر إلكتروني جزائري.
مهمتك: مساعدة العملاء في العثور على المنتجات، الإجابة على الأسئلة، وإتمام الطلبات.

قواعد صارمة:
1. لا تخترع أبداً أسعاراً، مخزوناً، أو تفاصيل منتجات. استخدم الأدوات المتاحة للحصول على البيانات الحقيقية.
2. تحدث بلغة العميل (العربية، الدارجة الجزائرية، العربيزي، أو الفرنسية) بنفس أسلوبه.
3. لا تؤكد الطلب إلا إذا وافق العميل صراحة بـ "نعم"، "أكد"، "Oui"، "Confirm".
4. إذا كان المنتج غير متوفر، اقترح بدائل باستخدام الأدوات.
5. كن محترفاً، ودوداً، ومباشراً.
"""

class ConversationContextBuilder:
    def __init__(self, db: Session, store_id: uuid.UUID, customer_id: uuid.UUID, conversation_id: uuid.UUID):
        self.db = db
        self.store_id = store_id
        self.customer_id = customer_id
        self.conversation_id = conversation_id

    async def build(self, current_message: str) -> list[LLMMessage]:
        messages = []
        
        # Layer 1: System Instructions
        messages.append(LLMMessage(role="system", content=SYSTEM_PROMPT))

        # Layer 2: Customer Context & Commerce State
        context_info = self._get_commerce_context()
        if context_info:
            messages.append(LLMMessage(role="system", content=f"سياق العميل والطلب الحالي:\n{context_info}"))

        # Layer 3: Recent Conversation History (Bounded)
        history = self._get_recent_history()
        messages.extend(history)

        # Layer 4: Current Message
        messages.append(LLMMessage(role="user", content=current_message))

        return messages

    def _get_commerce_context(self) -> str:
        """Fetch authoritative customer and active draft order data."""
        parts = []
        
        # Customer Info
        try:
            ctx = customer_context_service.get_customer_context(self.db, self.store_id, self.customer_id)
            cust = ctx.get("customer", {})
            parts.append(f"- اسم العميل: {cust.get('name', 'غير معروف')}")
            parts.append(f"- إجمالي الطلبات السابقة: {ctx.get('behavior_summary', {}).get('total_orders', 0)}")
        except Exception:
            pass

        # Active Draft Order
        draft = (
            self.db.query(Order)
            .filter(
                Order.store_id == self.store_id,
                Order.customer_id == self.customer_id,
                Order.status == OrderStatus.DRAFT
            )
            .order_by(Order.created_at.desc())
            .first()
        )
        if draft and draft.items:
            items_str = ", ".join([f"{i.product_name} (الكمية: {i.quantity}, السعر: {i.unit_price})" for i in draft.items])
            parts.append(f"- مسودة طلب نشطة حالياً: {items_str} | المجموع: {draft.total_amount} دج")
        else:
            parts.append("- لا توجد مسودة طلب نشطة حالياً.")

        return "\n".join(parts)

    def _get_recent_history(self) -> list[LLMMessage]:
        """Fetch bounded recent messages from the database."""
        msgs = (
            self.db.query(Message)
            .filter(Message.conversation_id == self.conversation_id)
            .order_by(Message.created_at.desc())
            .limit(QWEN_RECENT_MESSAGES_LIMIT)
            .all()
        )
        
        # Reverse to chronological order
        msgs.reverse()
        
        history = []
        for m in msgs:
            role = "user" if m.role == "user" else "assistant"
            history.append(LLMMessage(role=role, content=m.content))
            
        return history
''')

# ============================================================
# 6. REAL QWEN LLM PROVIDER
# ============================================================
write_file("app/agent/providers/qwen_provider.py", '''"""
QwenLLMProvider: Real integration with Qwen via DashScope OpenAI-compatible API.
Handles tool calling, token tracking, and error normalization.
"""
import time
import json
from openai import AsyncOpenAI, APIError, APITimeoutError
from app.agent.providers.base import LLMProvider, LLMMessage, LLMResponse
from app.core.config import QWEN_API_KEY, QWEN_MODEL, QWEN_BASE_URL, QWEN_TIMEOUT

class QwenLLMProvider(LLMProvider):
    def __init__(self):
        if not QWEN_API_KEY:
            raise ValueError("QWEN_API_KEY is not set. Cannot initialize QwenLLMProvider.")
        
        self.client = AsyncOpenAI(
            api_key=QWEN_API_KEY,
            base_url=QWEN_BASE_URL,
            timeout=float(QWEN_TIMEOUT),
        )
        self.model = QWEN_MODEL

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[dict] | None = None,
        system_prompt: str | None = None,
    ) -> LLMResponse:
        start_time = time.time()
        
        # Map internal messages to OpenAI format
        openai_messages = [{"role": m.role, "content": m.content} for m in messages]
        
        # Map tools to OpenAI function calling format
        openai_tools = None
        if tools:
            openai_tools = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t.get("parameters", {}),
                    }
                }
                for t in tools
            ]

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=openai_messages,
                tools=openai_tools,
                tool_choice="auto" if openai_tools else None,
            )
            
            latency_ms = int((time.time() - start_time) * 1000)
            choice = response.choices[0]
            msg = choice.message

            # Extract token usage
            usage = response.usage
            input_tokens = usage.prompt_tokens if usage else 0
            output_tokens = usage.completion_tokens if usage else 0

            # Handle Tool Calls
            if msg.tool_calls:
                tool_calls = []
                for tc in msg.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        args = {}
                    tool_calls.append({
                        "name": tc.function.name,
                        "arguments": args,
                        "id": tc.id,
                    })
                
                return LLMResponse(
                    content=msg.content,
                    tool_calls=tool_calls,
                    finish_reason="tool_calls",
                    usage={"input_tokens": input_tokens, "output_tokens": output_tokens, "latency_ms": latency_ms, "model": self.model},
                )
            
            # Normal text response
            return LLMResponse(
                content=msg.content or "",
                finish_reason=choice.finish_reason,
                usage={"input_tokens": input_tokens, "output_tokens": output_tokens, "latency_ms": latency_ms, "model": self.model},
            )

        except APITimeoutError:
            return LLMResponse(content="عذراً، حدث تأخير في الاستجابة. يرجى المحاولة مرة أخرى.", finish_reason="error")
        except APIError as e:
            return LLMResponse(content=f"عذراً، حدث خطأ في الاتصال بالذكاء الاصطناعي.", finish_reason="error")
        except Exception as e:
            return LLMResponse(content="عذراً، حدث خطأ غير متوقع.", finish_reason="error")
''')

# ============================================================
# 7. UPDATE MODELS __init__.py
# ============================================================
write_file("app/models/__init__.py", '''"""
Import every model here so that Base.metadata knows about all tables.
"""
from app.models.user import User
from app.models.store import Store
from app.models.store_user import StoreUser, StoreRole
from app.models.product import Product
from app.models.inventory import Inventory
from app.models.customer import Customer
from app.models.conversation import Conversation, ConversationStatus, MessageRole, Message
from app.models.order import Order, OrderItem, OrderStatus
from app.models.human_handoff import HumanHandoff
from app.models.customer_memory import CustomerMemory
from app.models.channel_enums import ChannelType, EventType, MessageType
from app.models.channel_identity import ChannelIdentity
from app.models.channel_account import ChannelAccount
from app.models.webhook_log import WebhookLog
from app.models.sales_opportunity import SalesOpportunity, OpportunityStatus, OpportunityType
from app.models.cod_risk import CODRiskScore
from app.models.ai_usage_event import AIUsageEvent

__all__ = [
    "User", "Store", "StoreUser", "StoreRole", "Product", "Inventory",
    "Customer", "Conversation", "ConversationStatus", "MessageRole", "Message",
    "Order", "OrderItem", "OrderStatus", "HumanHandoff", "CustomerMemory",
    "ChannelType", "EventType", "MessageType", "ChannelIdentity", "ChannelAccount",
    "WebhookLog", "SalesOpportunity", "OpportunityStatus", "OpportunityType",
    "CODRiskScore", "AIUsageEvent",
]
''')

# ============================================================
# 8. UPDATE CONVERSATION ENGINE (Integrate Context & Usage)
# ============================================================
write_file("app/agent/conversation_engine.py", '''"""
ConversationEngine: Orchestrates LLMProvider, ContextBuilder, and ToolRegistry.
"""
import uuid
import time
from sqlalchemy.orm import Session
from app.agent.providers.base import LLMMessage
from app.agent.tools.registry import ToolRegistry
from app.agent.context_builder import ConversationContextBuilder
from app.services import usage_service

HANDOFF_KEYWORDS = ["human", "person", "agent", "بشري", "انسان", "موظف", "دعم"]

def _detect_handoff_intent(message: str) -> bool:
    if not message: return False
    lower = message.lower().strip()
    return any(kw in lower for kw in HANDOFF_KEYWORDS)

class ConversationEngine:
    def __init__(self, llm_provider, tool_registry: ToolRegistry):
        self.llm = llm_provider
        self.registry = tool_registry

    async def process_message(
        self, db: Session, store_id: uuid.UUID, customer_id: uuid.UUID,
        conversation_id: uuid.UUID | None, channel: str, user_message: str,
    ) -> dict:
        conv_id = conversation_id or uuid.uuid4()
        start_time = time.time()

        # 1. Build Deliberate Context
        context_builder = ConversationContextBuilder(db, store_id, customer_id, conv_id)
        messages = await context_builder.build(user_message)

        # 2. Get Tools
        tools = self.registry.get_tool_definitions()

        # 3. Call LLM Provider
        response = await self.llm.chat(messages=messages, tools=tools)

        # 4. Log Usage (if real provider returned usage data)
        if hasattr(response, "usage") and response.usage:
            usage = response.usage
            usage_service.record_usage(
                db=db, store_id=store_id,
                provider="qwen", model=usage.get("model", "unknown"),
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                latency_ms=usage.get("latency_ms", 0),
                conversation_id=conv_id,
            )

        # 5. Build Result
        result = {
            "conversation_id": str(conv_id),
            "response": response.content or "",
            "handoff": False,
            "tool_calls": [],
        }

        # 6. Handle Handoff Intent Fallback
        if _detect_handoff_intent(user_message) and not response.tool_calls:
            response.tool_calls = [{"name": "handoff_to_human", "arguments": {"reason": "customer_requested_human", "summary": "Customer requested human"}}]

        # 7. Execute Tools
        if response.tool_calls:
            for tc in response.tool_calls:
                tool_name = tc.get("name", "")
                tool_args = tc.get("arguments", {})
                
                tool_result = await self.registry.aexecute(
                    tool_name=tool_name, arguments=tool_args,
                    context={"db": db, "store_id": store_id, "customer_id": customer_id, "conversation_id": conv_id, "channel": channel},
                )
                
                if tool_name == "handoff_to_human" and tool_result.success:
                    result["handoff"] = True
                    
                result["tool_calls"].append(tc)

        return result
''')

# ============================================================
# 9. UPDATE AGENT API (Provider Selection)
# ============================================================
write_file("app/api/agent.py", '''import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.models.store_user import StoreUser
from app.models.customer import Customer
from app.schemas.conversation import AgentChatRequest, AgentChatResponse, ToolCallInfo
from app.agent.conversation_engine import ConversationEngine
from app.agent.tools.registry import ToolRegistry
from app.core.config import AGENT_PROVIDER

# Import Providers
from app.agent.providers.mock_provider import MockLLMProvider
from app.agent.providers.qwen_provider import QwenLLMProvider

# Import Tools (Phases 3-9)
from app.agent.tools.search_products import SearchProductsTool
from app.agent.tools.check_inventory import CheckInventoryTool
from app.agent.tools.get_price import GetPriceTool
from app.agent.tools.handoff_to_human import HandoffToHumanTool
from app.agent.tools.get_customer_context import GetCustomerContextTool
from app.agent.tools.create_order_draft import CreateOrderDraftTool
from app.agent.tools.add_item_to_order import AddItemToOrderTool
from app.agent.tools.get_order import GetOrderTool
from app.agent.tools.confirm_order import ConfirmOrderTool
from app.agent.tools.cancel_order import CancelOrderTool
from app.agent.tools.get_product_details import GetProductDetailsTool
from app.agent.tools.recommend_products import RecommendProductsTool
from app.agent.tools.check_cod_risk import CheckCODRiskTool
from app.agent.tools.get_lost_sales import GetLostSalesOpportunitiesTool
from app.agent.tools.create_follow_up import CreateFollowUpOpportunityTool

router = APIRouter(prefix="/api/agent", tags=["agent"])

def _build_engine() -> ConversationEngine:
    registry = ToolRegistry()
    # Register all tools
    for tool in [SearchProductsTool(), CheckInventoryTool(), GetPriceTool(), HandoffToHumanTool(),
                 GetCustomerContextTool(), CreateOrderDraftTool(), AddItemToOrderTool(), GetOrderTool(),
                 ConfirmOrderTool(), CancelOrderTool(), GetProductDetailsTool(), RecommendProductsTool(),
                 CheckCODRiskTool(), GetLostSalesOpportunitiesTool(), CreateFollowUpOpportunityTool()]:
        registry.register(tool)

    # Select Provider based on Environment
    if AGENT_PROVIDER == "qwen":
        provider = QwenLLMProvider()
    else:
        provider = MockLLMProvider()

    return ConversationEngine(provider, registry)

@router.post("/chat", response_model=AgentChatResponse)
async def agent_chat(payload: AgentChatRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        store_id = uuid.UUID(payload.store_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store not found")

    membership = db.query(StoreUser).filter(StoreUser.store_id == store_id, StoreUser.user_id == current_user.id).first()
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store not found")

    customer = None
    if payload.customer_external_id:
        customer = db.query(Customer).filter(Customer.store_id == store_id, Customer.external_id == payload.customer_external_id).first()
    if not customer:
        customer = Customer(store_id=store_id, external_id=payload.customer_external_id, name="API Customer")
        db.add(customer)
        db.flush()

    engine = _build_engine()
    result = await engine.process_message(
        db=db, store_id=store_id, customer_id=customer.id,
        conversation_id=uuid.UUID(payload.conversation_id) if payload.conversation_id else None,
        channel=payload.channel, user_message=payload.message,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    # Safe tool call building
    tool_calls = []
    for tc in result.get("tool_calls", []):
        try:
            tool_calls.append(ToolCallInfo(name=tc.get("name", ""), arguments=tc.get("arguments", {})))
        except Exception:
            pass

    return AgentChatResponse(
        response=result["response"],
        conversation_id=uuid.UUID(result["conversation_id"]),
        handoff=result["handoff"],
        tool_calls=tool_calls,
    )
''')

# ============================================================
# 10. MIGRATION 0010 (AI Usage Events)
# ============================================================
write_file("alembic/versions/0010_ai_usage_events.py", '''"""ai usage events for billing foundation
Revision ID: 0010
Revises: 0009
Create Date: 2026-09-16
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: Union[str, None] = "0009"

def upgrade() -> None:
    op.create_table(
        "ai_usage_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost", sa.Numeric(10, 6), nullable=False, server_default="0.00"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_ai_usage_store", "ai_usage_events", ["store_id"])
    op.create_index("ix_ai_usage_provider", "ai_usage_events", ["provider"])
    op.create_index("ix_ai_usage_created", "ai_usage_events", ["created_at"])

def downgrade() -> None:
    op.drop_index("ix_ai_usage_created", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_provider", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_store", table_name="ai_usage_events")
    op.drop_table("ai_usage_events")
''')

print("\n=== Phase 10 Setup Complete ===")
print("Next steps:")
print("1. Run: alembic upgrade head")
print("2. Run: python -m pytest -v")
