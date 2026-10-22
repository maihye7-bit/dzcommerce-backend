"""
LostSalesService: Identifies and manages lost sales opportunities.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.order import Order, OrderStatus
from app.models.sales_opportunity import (OpportunityStatus, OpportunityType,
                                          SalesOpportunity)


def create_opportunity(
    db: Session,
    store_id: uuid.UUID,
    customer_id: uuid.UUID,
    opp_type: OpportunityType,
    related_order_id: uuid.UUID | None = None,
    related_product_id: uuid.UUID | None = None,
    notes: str | None = None,
) -> SalesOpportunity:
    """Create a new sales opportunity record."""
    opp = SalesOpportunity(
        store_id=store_id,
        customer_id=customer_id,
        opportunity_type=opp_type,
        related_order_id=related_order_id,
        related_product_id=related_product_id,
        notes=notes,
    )
    db.add(opp)
    db.commit()
    db.refresh(opp)
    return opp


def get_open_opportunities(
    db: Session,
    store_id: uuid.UUID,
    limit: int = 50,
) -> list[SalesOpportunity]:
    """Get open opportunities for a store, sorted by oldest first."""
    return (
        db.query(SalesOpportunity)
        .filter(
            SalesOpportunity.store_id == store_id,
            SalesOpportunity.status == OpportunityStatus.OPEN,
        )
        .order_by(SalesOpportunity.created_at.asc())
        .limit(limit)
        .all()
    )


def mark_as_followed_up(
    db: Session,
    opportunity_id: uuid.UUID,
) -> SalesOpportunity:
    """Mark an opportunity as followed up."""
    opp = (
        db.query(SalesOpportunity).filter(SalesOpportunity.id == opportunity_id).first()
    )
    if opp:
        opp.status = OpportunityStatus.FOLLOWED_UP
        opp.last_contacted_at = datetime.utcnow()
        db.commit()
        db.refresh(opp)
    return opp


def check_abandoned_drafts(
    db: Session,
    store_id: uuid.UUID,
    hours_threshold: int = 24,
) -> list[SalesOpportunity]:
    """
    Check for drafts created more than X hours ago that are still in DRAFT status.
    Creates opportunities if they don't already exist.
    """
    cutoff_time = datetime.utcnow() - timedelta(hours=hours_threshold)

    abandoned_orders = (
        db.query(Order)
        .filter(
            Order.store_id == store_id,
            Order.status == OrderStatus.DRAFT,
            Order.created_at < cutoff_time,
        )
        .all()
    )

    new_opportunities = []
    for order in abandoned_orders:
        # Check if opportunity already exists for this order
        existing = (
            db.query(SalesOpportunity)
            .filter(
                SalesOpportunity.related_order_id == order.id,
                SalesOpportunity.opportunity_type == OpportunityType.ABANDONED_DRAFT,
                SalesOpportunity.status == OpportunityStatus.OPEN,
            )
            .first()
        )

        if not existing:
            opp = create_opportunity(
                db=db,
                store_id=store_id,
                customer_id=order.customer_id,
                opp_type=OpportunityType.ABANDONED_DRAFT,
                related_order_id=order.id,
                notes=f"Draft order {order.id} abandoned for >{hours_threshold} hours.",
            )
            new_opportunities.append(opp)

    return new_opportunities
