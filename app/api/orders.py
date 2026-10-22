from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload

from app.core.deps import get_current_user
from app.database import get_db
from app.models.customer import Customer
from app.models.order import Order
from app.models.store_user import StoreUser
from app.models.user import User

router = APIRouter(prefix="/api/orders", tags=["orders"])


@router.get("/")
def list_orders(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    store_ids = [
        store_id
        for (store_id,) in db.query(StoreUser.store_id)
        .filter(StoreUser.user_id == current_user.id)
        .all()
    ]
    orders = (
        db.query(Order)
        .options(joinedload(Order.items))
        .filter(Order.store_id.in_(store_ids))
        .order_by(Order.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    customer_ids = {order.customer_id for order in orders if order.customer_id}
    customers = {
        customer.id: customer
        for customer in db.query(Customer)
        .filter(Customer.id.in_(customer_ids))
        .all()
    } if customer_ids else {}
    return [
        {
            "id": str(o.id),
            "store_id": str(o.store_id),
            "customer_name": customers[o.customer_id].name
            if o.customer_id in customers
            else "Unknown",
            "total_amount": float(o.total),
            "status": o.status.value,
            "created_at": o.created_at.isoformat() if o.created_at else None,
        }
        for o in orders
    ]
