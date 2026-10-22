import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.agent.conversation_engine import ConversationEngine
# Import Providers
from app.agent.providers.mock_provider import MockLLMProvider
from app.agent.providers.qwen_provider import QwenLLMProvider
from app.agent.tools.add_item_to_order import AddItemToOrderTool
from app.agent.tools.cancel_order import CancelOrderTool
from app.agent.tools.check_cod_risk import CheckCODRiskTool
from app.agent.tools.check_inventory import CheckInventoryTool
from app.agent.tools.confirm_order import ConfirmOrderTool
from app.agent.tools.create_follow_up import CreateFollowUpOpportunityTool
from app.agent.tools.create_order_draft import CreateOrderDraftTool
from app.agent.tools.get_customer_context import GetCustomerContextTool
from app.agent.tools.get_lost_sales import GetLostSalesOpportunitiesTool
from app.agent.tools.get_order import GetOrderTool
from app.agent.tools.get_price import GetPriceTool
from app.agent.tools.get_product_details import GetProductDetailsTool
from app.agent.tools.handoff_to_human import HandoffToHumanTool
from app.agent.tools.list_catalog import ListCatalogProductsTool
from app.agent.tools.recommend_products import RecommendProductsTool
from app.agent.tools.registry import ToolRegistry
# Import Tools (Phases 3-9)
from app.agent.tools.search_products import SearchProductsTool
from app.core.config import AGENT_PROVIDER
from app.core.deps import get_current_user
from app.database import get_db
from app.models.customer import Customer
from app.models.channel_identity import ChannelIdentity
from app.models.store_user import StoreUser
from app.models.user import User
from app.schemas.conversation import (AgentChatRequest, AgentChatResponse,
                                      ToolCallInfo)

router = APIRouter(prefix="/api/agent", tags=["agent"])


def _build_engine() -> ConversationEngine:
    registry = ToolRegistry()
    # Register all tools
    for tool in [
        SearchProductsTool(),
        CheckInventoryTool(),
        GetPriceTool(),
        HandoffToHumanTool(),
        GetCustomerContextTool(),
        CreateOrderDraftTool(),
        AddItemToOrderTool(),
        GetOrderTool(),
        ConfirmOrderTool(),
        CancelOrderTool(),
        GetProductDetailsTool(),
        ListCatalogProductsTool(),
        RecommendProductsTool(),
        CheckCODRiskTool(),
        GetLostSalesOpportunitiesTool(),
        CreateFollowUpOpportunityTool(),
    ]:
        registry.register(tool)

    # Select Provider based on Environment
    if AGENT_PROVIDER == "qwen":
        provider = QwenLLMProvider()
    else:
        provider = MockLLMProvider()

    return ConversationEngine(provider, registry)


@router.post("/chat", response_model=AgentChatResponse)
async def agent_chat(
    payload: AgentChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        store_id = uuid.UUID(payload.store_id)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Store not found"
        )

    membership = (
        db.query(StoreUser)
        .filter(StoreUser.store_id == store_id, StoreUser.user_id == current_user.id)
        .first()
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Store not found"
        )

    customer = None
    if payload.customer_external_id:
        identity = (
            db.query(ChannelIdentity)
            .filter(
                ChannelIdentity.store_id == store_id,
                ChannelIdentity.channel == payload.channel,
                ChannelIdentity.external_user_id == payload.customer_external_id,
            )
            .first()
        )
        if identity:
            customer = (
                db.query(Customer)
                .filter(
                    Customer.id == identity.customer_id,
                    Customer.store_id == store_id,
                )
                .first()
            )
    if not customer:
        customer = Customer(
            store_id=store_id,
            name="API Customer",
        )
        db.add(customer)
        db.flush()
        if payload.customer_external_id:
            db.add(
                ChannelIdentity(
                    store_id=store_id,
                    customer_id=customer.id,
                    channel=payload.channel,
                    external_user_id=payload.customer_external_id,
                )
            )
            db.flush()

    engine = _build_engine()
    result = await engine.process_message(
        db=db,
        store_id=store_id,
        customer_id=customer.id,
        conversation_id=(
            uuid.UUID(payload.conversation_id) if payload.conversation_id else None
        ),
        channel=payload.channel,
        user_message=payload.message,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    # Safe tool call building
    tool_calls = []
    for tc in result.get("tool_calls", []):
        try:
            tool_calls.append(
                ToolCallInfo(name=tc.get("name", ""), arguments=tc.get("arguments", {}))
            )
        except Exception:
            pass

    return AgentChatResponse(
        response=result["response"],
        conversation_id=uuid.UUID(result["conversation_id"]),
        handoff=result["handoff"],
        tool_calls=tool_calls,
    )
