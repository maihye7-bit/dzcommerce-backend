"""
Pydantic schemas for customer context responses.
These define the structured output of CustomerContextService.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict


class CustomerInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    language: Optional[str] = None
    created_at: datetime


class OrderSummary(BaseModel):
    id: uuid.UUID
    status: str
    total_amount: Decimal
    currency: str
    created_at: datetime
    item_count: int = 0


class PreviousProduct(BaseModel):
    product_id: uuid.UUID
    product_name: str
    quantity: int
    unit_price: Decimal
    order_date: datetime


class ConversationSummary(BaseModel):
    id: uuid.UUID
    channel: str
    status: str
    created_at: datetime
    last_message: Optional[str] = None
    message_count: int = 0


class MemoryEntry(BaseModel):
    memory_type: str
    key: str
    value: str
    confidence: float
    created_at: datetime


class BehaviorSummary(BaseModel):
    total_orders: int = 0
    completed_orders: int = 0
    cancelled_orders: int = 0
    open_orders: int = 0
    total_purchased_quantity: int = 0
    total_spent: Decimal = Decimal("0")
    last_order_date: Optional[datetime] = None


class CustomerContext(BaseModel):
    customer: CustomerInfo
    recent_orders: list[OrderSummary] = []
    open_orders: list[OrderSummary] = []
    previous_products: list[PreviousProduct] = []
    recent_conversations: list[ConversationSummary] = []
    preferences: list[MemoryEntry] = []
    behavior_summary: BehaviorSummary = BehaviorSummary()
