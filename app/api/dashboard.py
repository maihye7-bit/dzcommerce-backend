from __future__ import annotations

import uuid
from typing import Any

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func
from sqlalchemy.orm import Session, joinedload

from app.core.deps import get_current_user, get_store_membership
from app.database import get_db
from app.models.conversation import Conversation
from app.models.ai_usage_event import AIUsageEvent
from app.models.inventory import InventoryItem
from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Product, ProductVariant
from app.models.store_user import StoreUser
from app.models.user import User

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/usage")
def get_dashboard_usage(
    store_id: uuid.UUID = Query(...),
    membership: StoreUser = Depends(get_store_membership),
    db: Session = Depends(get_db),
) -> dict[str, int | float]:
    store_id = membership.store_id
    today = func.date(AIUsageEvent.created_at) == date.today()
    totals = (
        db.query(
            func.count(AIUsageEvent.id).label("total_events"),
            func.coalesce(func.sum(AIUsageEvent.input_tokens), 0).label(
                "total_input_tokens"
            ),
            func.coalesce(func.sum(AIUsageEvent.output_tokens), 0).label(
                "total_output_tokens"
            ),
            func.coalesce(func.sum(AIUsageEvent.total_tokens), 0).label(
                "total_tokens"
            ),
            func.coalesce(func.sum(AIUsageEvent.estimated_cost), 0).label(
                "estimated_cost_usd"
            ),
            func.count(case((today, AIUsageEvent.id))).label("events_today"),
        )
        .filter(AIUsageEvent.store_id == store_id)
        .one()
    )
    return {
        "total_events": int(totals.total_events or 0),
        "total_input_tokens": int(totals.total_input_tokens or 0),
        "total_output_tokens": int(totals.total_output_tokens or 0),
        "total_tokens": int(totals.total_tokens or 0),
        "estimated_cost_usd": float(totals.estimated_cost_usd or 0),
        "events_today": int(totals.events_today or 0),
    }


@router.get("/stats")
def get_dashboard_stats(
    store_id: uuid.UUID = Query(...),
    membership: StoreUser = Depends(get_store_membership),
    db: Session = Depends(get_db),
) -> dict[str, int | float]:
    store_id = membership.store_id
    total_orders = (
        db.query(func.count(Order.id))
        .filter(
            Order.store_id == store_id,
            Order.status == OrderStatus.CONFIRMED,
        )
        .scalar()
    )
    total_revenue = (
        db.query(func.coalesce(func.sum(Order.total), 0))
        .filter(
            Order.store_id == store_id,
            Order.status == OrderStatus.CONFIRMED,
        )
        .scalar()
    )
    low_stock_items_count = (
        db.query(func.count(InventoryItem.id))
        .filter(
            InventoryItem.store_id == store_id,
            InventoryItem.quantity < 5,
        )
        .scalar()
    )
    orders_today = (
        db.query(func.count(Order.id))
        .filter(
            Order.store_id == store_id,
            func.date(Order.created_at) == date.today(),
        )
        .scalar()
    )

    return {
        "total_orders": int(total_orders or 0),
        "total_revenue": float(total_revenue or 0),
        "low_stock_items_count": int(low_stock_items_count or 0),
        "orders_today": int(orders_today or 0),
    }


@router.get("/orders")
def list_dashboard_orders(
    store_id: uuid.UUID = Query(...),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    membership: StoreUser = Depends(get_store_membership),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    store_id = membership.store_id
    confirmed_orders = db.query(Order).filter(
        Order.store_id == store_id,
        Order.status == OrderStatus.CONFIRMED,
    )
    total = confirmed_orders.count()
    orders = (
        confirmed_orders.options(joinedload(Order.items))
        .order_by(Order.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {
        "items": [
            {
                "id": str(order.id),
                "store_id": str(order.store_id),
                "customer_id": str(order.customer_id) if order.customer_id else None,
                "conversation_id": (
                    str(order.conversation_id) if order.conversation_id else None
                ),
                "status": order.status.value,
                "subtotal": float(order.subtotal),
                "shipping_cost": float(order.shipping_cost),
                "total": float(order.total),
                "wilaya": order.wilaya,
                "created_at": (
                    order.created_at.isoformat() if order.created_at else None
                ),
                "items": [
                    {
                        "id": str(item.id),
                        "product_id": str(item.product_id) if item.product_id else None,
                        "variant_id": str(item.variant_id) if item.variant_id else None,
                        "quantity": item.quantity,
                        "unit_price": float(item.unit_price),
                    }
                    for item in order.items
                ],
            }
            for order in orders
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/orders/{order_id}")
def get_dashboard_order(
    order_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    membership = (
        db.query(StoreUser)
        .join(Order, Order.store_id == StoreUser.store_id)
        .filter(Order.id == order_id, StoreUser.user_id == current_user.id)
        .first()
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Order not found"
        )

    store_id = membership.store_id
    order = (
        db.query(Order)
        .options(joinedload(Order.items))
        .filter(Order.id == order_id, Order.store_id == store_id)
        .first()
    )
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Order not found"
        )

    product_ids = {item.product_id for item in order.items if item.product_id}
    variant_ids = {item.variant_id for item in order.items if item.variant_id}
    products = (
        {
            product.id: product.name
            for product in db.query(Product)
            .filter(
                Product.id.in_(product_ids),
                Product.store_id == store_id,
            )
            .all()
        }
        if product_ids
        else {}
    )
    variants = (
        {
            variant.id: variant.name
            for variant in db.query(ProductVariant)
            .join(Product, Product.id == ProductVariant.product_id)
            .filter(
                ProductVariant.id.in_(variant_ids),
                Product.store_id == store_id,
            )
            .all()
        }
        if variant_ids
        else {}
    )

    return {
        "id": str(order.id),
        "store_id": str(order.store_id),
        "customer_id": str(order.customer_id) if order.customer_id else None,
        "conversation_id": (
            str(order.conversation_id) if order.conversation_id else None
        ),
        "status": order.status.value,
        "subtotal": float(order.subtotal),
        "shipping_cost": float(order.shipping_cost),
        "total": float(order.total),
        "wilaya": order.wilaya,
        "shipping_address": order.shipping_address,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "items": [
            {
                "id": str(item.id),
                "product_id": str(item.product_id) if item.product_id else None,
                "product_name": products.get(item.product_id),
                "variant_id": str(item.variant_id) if item.variant_id else None,
                "variant_name": variants.get(item.variant_id),
                "quantity": item.quantity,
                "unit_price": float(item.unit_price),
                "line_total": float(item.unit_price * item.quantity),
            }
            for item in order.items
        ],
    }


@router.get("/analytics/top-products")
def get_top_products(
    store_id: uuid.UUID = Query(...),
    membership: StoreUser = Depends(get_store_membership),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    store_id = membership.store_id
    results = (
        db.query(
            Product.id.label("product_id"),
            Product.name.label("product_name"),
            ProductVariant.name.label("variant_name"),
            func.sum(OrderItem.quantity).label("count"),
            func.sum(OrderItem.quantity * OrderItem.unit_price).label("revenue"),
        )
        .join(OrderItem, OrderItem.product_id == Product.id)
        .join(Order, Order.id == OrderItem.order_id)
        .outerjoin(ProductVariant, ProductVariant.id == OrderItem.variant_id)
        .filter(
            Product.store_id == store_id,
            Order.store_id == store_id,
            Order.status == OrderStatus.CONFIRMED,
        )
        .group_by(
            Product.id,
            Product.name,
            ProductVariant.id,
            ProductVariant.name,
        )
        .order_by(
            func.sum(OrderItem.quantity).desc(),
            Product.name.asc(),
            ProductVariant.name.asc(),
        )
        .limit(5)
        .all()
    )
    return [
        {
            "product_id": str(row.product_id),
            "product_name": row.product_name,
            "variant_name": row.variant_name,
            "count": int(row.count or 0),
            "revenue": float(row.revenue or 0),
        }
        for row in results
    ]


@router.get("/conversations")
def list_dashboard_conversations(
    store_id: uuid.UUID = Query(...),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    membership: StoreUser = Depends(get_store_membership),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    store_id = membership.store_id
    conversations_for_store = db.query(Conversation).filter(
        Conversation.store_id == store_id
    )
    total = conversations_for_store.count()
    conversations = (
        conversations_for_store.order_by(Conversation.updated_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {
        "items": [
            {
                "id": str(conversation.id),
                "store_id": str(conversation.store_id),
                "customer_id": str(conversation.customer_id),
                "channel": conversation.channel,
                "status": conversation.status,
                "commerce_stage": (
                    (conversation.metadata_json or {}).get("commerce_stage")
                ),
                "metadata_json": conversation.metadata_json or {},
                "active_draft_json": conversation.active_draft_json,
                "created_at": (
                    conversation.created_at.isoformat()
                    if conversation.created_at
                    else None
                ),
                "updated_at": (
                    conversation.updated_at.isoformat()
                    if conversation.updated_at
                    else None
                ),
            }
            for conversation in conversations
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }
