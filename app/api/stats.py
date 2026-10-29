import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import get_store_membership
from app.database import get_db
from app.models.customer import Customer
from app.models.order import Order
from app.models.product import Product
from app.models.store_user import StoreUser
from app.models.conversation import Conversation

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/dashboard")
def get_dashboard_stats(
    store_id: uuid.UUID = Query(...),
    membership: StoreUser = Depends(get_store_membership),
    db: Session = Depends(get_db),
):
    """
    Returns aggregated statistics for the merchant dashboard.
    """
    store_id = membership.store_id
    total_orders = db.query(Order).filter(Order.store_id == store_id).count()

    # حساب الإيرادات الكلية
    total_revenue_result = (
        db.query(func.sum(Order.total))
        .filter(Order.store_id == store_id)
        .scalar()
    )
    total_revenue = float(total_revenue_result) if total_revenue_result else 0.0

    total_customers = db.query(Customer).filter(Customer.store_id == store_id).count()
    total_products = db.query(Product).filter(Product.store_id == store_id).count()
    active_conversations = (
        db.query(Conversation)
        .filter(Conversation.store_id == store_id, Conversation.status == "active")
        .count()
    )

    return {
        "total_orders": total_orders,
        "total_revenue": total_revenue,
        "total_customers": total_customers,
        "total_products": total_products,
        "ai_handled_percentage": 85,
        "active_conversations": active_conversations,
        "cod_risk_count": 0,
    }
