from fastapi import APIRouter, Depends
from sqlalchemy import func  # <--- مهم جداً: استيراد func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.customer import Customer
from app.models.order import Order
from app.models.product import Product

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/dashboard")
def get_dashboard_stats(db: Session = Depends(get_db)):
    """
    Returns aggregated statistics for the merchant dashboard.
    """
    total_orders = db.query(Order).count()

    # حساب الإيرادات الكلية
    total_revenue_result = db.query(func.sum(Order.total_amount)).scalar()
    total_revenue = float(total_revenue_result) if total_revenue_result else 0.0

    total_customers = db.query(Customer).count()
    total_products = db.query(Product).count()

    return {
        "total_orders": total_orders,
        "total_revenue": total_revenue,
        "total_customers": total_customers,
        "total_products": total_products,
        "ai_handled_percentage": 85,
        "active_conversations": 0,
        "cod_risk_count": 0,
    }
