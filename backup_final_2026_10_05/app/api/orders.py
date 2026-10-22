from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.order import Order  # تأكد من وجود الموديل

router = APIRouter(prefix="/api/orders", tags=["orders"])


@router.get("/")
def list_orders(db: Session = Depends(get_db)):
    orders = db.query(Order).all()
    return [
        {
            "id": str(o.id),
            "customer_name": getattr(o.customer, "name", "Unknown"),  # يعتمد على علاقتك
            "total_amount": float(o.total_amount),
            "status": o.status,
            "created_at": o.created_at.isoformat() if o.created_at else None,
        }
        for o in orders
    ]
