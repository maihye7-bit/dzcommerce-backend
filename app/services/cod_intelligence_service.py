"""
CODIntelligenceService: Calculates and manages COD risk scores.
"""

import uuid

from sqlalchemy.orm import Session

from app.models.cod_risk import CODRiskScore
from app.models.order import Order, OrderStatus


def calculate_risk_score(
    db: Session,
    store_id: uuid.UUID,
    customer_id: uuid.UUID,
) -> CODRiskScore:
    """
    Calculate COD risk score based on order history.
    Formula: (Rejected + Returned) / Total Orders * 100
    Lower is better.
    """
    orders = (
        db.query(Order)
        .filter(
            Order.store_id == store_id,
            Order.customer_id == customer_id,
            Order.status.in_(
                [OrderStatus.CANCELLED, OrderStatus.DELIVERED]
            ),
        )
        .all()
    )

    total = len(orders)
    if total == 0:
        # New customer: Neutral risk (or slightly high due to lack of data)
        risk_value = 50
        rejected = 0
        returned = 0
    else:
        # In a real system, we'd have specific statuses for 'Rejected by Customer' or 'Returned'
        # For now, we'll assume CANCELLED after confirmation might indicate rejection
        # Or we can add specific fields later. Let's use a simple placeholder logic.
        rejected = sum(1 for o in orders if o.status == OrderStatus.CANCELLED)
        returned = 0  # Placeholder for future 'Returned' status

        risk_value = int((rejected + returned) / total * 100)

    # Upsert logic
    score_record = (
        db.query(CODRiskScore)
        .filter(
            CODRiskScore.store_id == store_id,
            CODRiskScore.customer_id == customer_id,
        )
        .first()
    )

    if not score_record:
        score_record = CODRiskScore(
            store_id=store_id,
            customer_id=customer_id,
            risk_score=risk_value,
            total_orders=total,
            rejected_orders=rejected,
            returned_orders=returned,
        )
        db.add(score_record)
    else:
        score_record.risk_score = risk_value
        score_record.total_orders = total
        score_record.rejected_orders = rejected
        score_record.returned_orders = returned

    db.commit()
    db.refresh(score_record)
    return score_record


def get_risk_score(
    db: Session,
    store_id: uuid.UUID,
    customer_id: uuid.UUID,
) -> CODRiskScore | None:
    """Get existing risk score without recalculating."""
    return (
        db.query(CODRiskScore)
        .filter(
            CODRiskScore.store_id == store_id,
            CODRiskScore.customer_id == customer_id,
        )
        .first()
    )
