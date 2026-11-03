"""
Models package initialization.
Imports all models to ensure they are registered with SQLAlchemy Base.
"""
from app.models.user import User
from app.models.store import Store
from app.models.store_user import StoreUser, StoreRole
from app.models.conversation import Conversation, Message
from app.models.customer import Customer
from app.models.product import Product, ProductVariant
from app.models.product_image import ProductImage
from app.models.inventory import InventoryItem
from app.models.order import Order, OrderItem
from app.models.channel_account import ChannelAccount
from app.models.ai_usage_event import AIUsageEvent

__all__ = [
    "User",
    "Store",
    "StoreUser",
    "StoreRole",
    "Conversation",
    "Message",
    "Customer",
    "Product",
    "ProductVariant",
    "ProductImage",
    "InventoryItem",
    "Order",
    "OrderItem",
    "ChannelAccount",
    "AIUsageEvent",
]
