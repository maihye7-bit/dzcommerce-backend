"""
Phase 6 Part 1 - Channel Foundation Models & Migration
Run: python setup_phase6_part1.py
"""
import os

def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"  Created: {path}")

print("\n=== Phase 6 Part 1: Channel Foundation ===\n")

# ============================================================
# 1. CHANNEL ENUMS
# ============================================================
write_file("app/models/channel_enums.py", '''"""
Enums for social commerce channels and event types.
These are first-class concepts in the channel-agnostic architecture.
"""
import enum


class ChannelType(str, enum.Enum):
    """Supported social commerce channels."""
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"
    WHATSAPP = "whatsapp"
    API = "api"  # Existing direct API channel


class EventType(str, enum.Enum):
    """Types of inbound events from social platforms."""
    MESSAGE_RECEIVED = "message_received"
    COMMENT_CREATED = "comment_created"


class MessageType(str, enum.Enum):
    """Internal message classification."""
    TEXT = "text"
    COMMENT = "comment"
''')

# ============================================================
# 2. CHANNEL IDENTITY MODEL
# ============================================================
write_file("app/models/channel_identity.py", '''"""
ChannelIdentity: Maps external platform user IDs to internal customers.
A single Customer can have multiple ChannelIdentities (one per platform).
Strict tenant isolation via store_id.
"""
import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, func, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.channel_enums import ChannelType


class ChannelIdentity(Base):
    __tablename__ = "channel_identities"
    __table_args__ = (
        # Same external_id on same channel can't belong to two customers in same store
        UniqueConstraint(
            "store_id", "channel", "external_user_id",
            name="uq_channel_identity_store_channel_ext_user"
        ),
        Index("ix_channel_identities_customer", "store_id", "customer_id"),
        Index("ix_channel_identities_lookup", "store_id", "channel", "external_user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[ChannelType] = mapped_column(
        String(20), nullable=False
    )
    external_user_id: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    external_username: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
''')

# ============================================================
# 3. UPDATE CONVERSATION MODEL
# ============================================================
write_file("app/models/conversation.py", '''"""
Conversation model - Updated for Phase 6 channel support.
Added external_conversation_id for platform linkage.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, ForeignKey, Enum, func, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.channel_enums import ChannelType


class ConversationStatus(str, enum.Enum):
    ACTIVE = "active"
    HANDOFF = "handoff"
    CLOSED = "closed"


class MessageRole(str, enum.Enum):
    CUSTOMER = "customer"
    AGENT = "agent"
    SYSTEM = "system"


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_store_id", "store_id"),
        Index("ix_conversations_customer_id", "customer_id"),
        Index("ix_conversations_external", "store_id", "channel", "external_conversation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    external_conversation_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    status: Mapped[ConversationStatus] = mapped_column(
        Enum(ConversationStatus, name="conversation_status",
             values_callable=lambda e: [m.value for m in e]),
        default=ConversationStatus.ACTIVE, nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_conversation_id", "conversation_id"),
        Index("ix_messages_external_id", "external_message_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[MessageRole] = mapped_column(
        Enum(MessageRole, name="message_role",
             values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    external_message_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True
    )
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
''')

# ============================================================
# 4. MIGRATION 0006
# ============================================================
write_file("alembic/versions/0006_channel_foundation.py", '''"""channel foundation: channel_identities + conversation/message updates
Revision ID: 0006
Revises: 0005
Create Date: 2026-09-15
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create channel_identities table
    op.create_table(
        "channel_identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("store_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("external_user_id", sa.String(255), nullable=False),
        sa.Column("external_username", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("store_id", "channel", "external_user_id",
                           name="uq_channel_identity_store_channel_ext_user"),
    )
    op.create_index("ix_channel_identities_customer", "channel_identities", ["store_id", "customer_id"])
    op.create_index("ix_channel_identities_lookup", "channel_identities", ["store_id", "channel", "external_user_id"])

    # Add external_conversation_id to conversations
    op.add_column("conversations", sa.Column("external_conversation_id", sa.String(255), nullable=True))
    op.create_index("ix_conversations_external", "conversations", ["store_id", "channel", "external_conversation_id"])

    # Add message_type and external_message_id to messages
    op.add_column("messages", sa.Column("message_type", sa.String(20), nullable=True))
    op.add_column("messages", sa.Column("external_message_id", sa.String(255), nullable=True))
    op.create_index("ix_messages_external_id", "messages", ["external_message_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_messages_external_id", table_name="messages")
    op.drop_column("messages", "external_message_id")
    op.drop_column("messages", "message_type")
    op.drop_index("ix_conversations_external", table_name="conversations")
    op.drop_column("conversations", "external_conversation_id")
    op.drop_index("ix_channel_identities_lookup", table_name="channel_identities")
    op.drop_index("ix_channel_identities_customer", table_name="channel_identities")
    op.drop_table("channel_identities")
''')

# ============================================================
# 5. UPDATE models/__init__.py
# ============================================================
write_file("app/models/__init__.py", '''"""
Import every model here so that Base.metadata knows about all tables.
Phase 1: auth + multi-tenancy
Phase 2: products + inventory
Phase 3: customers, orders, conversations, messages, human_handoffs
Phase 4: customer_memories
Phase 5: order workflow (expanded statuses)
Phase 6: channel foundation (channel_identities, external IDs)
"""
from app.models.user import User
from app.models.store import Store
from app.models.store_user import StoreUser, StoreRole
from app.models.product import Product
from app.models.inventory import Inventory
from app.models.customer import Customer
from app.models.conversation import Conversation, ConversationStatus, MessageRole, Message
from app.models.order import Order, OrderItem, OrderStatus
from app.models.human_handoff import HumanHandoff
from app.models.customer_memory import CustomerMemory
from app.models.channel_enums import ChannelType, EventType, MessageType
from app.models.channel_identity import ChannelIdentity

__all__ = [
    "User", "Store", "StoreUser", "StoreRole", "Product", "Inventory",
    "Customer",
    "Conversation", "ConversationStatus", "MessageRole", "Message",
    "Order", "OrderItem", "OrderStatus",
    "HumanHandoff",
    "CustomerMemory",
    "ChannelType", "EventType", "MessageType",
    "ChannelIdentity",
]
''')

print("\n=== Part 1 Complete ===")
print("Created:")
print("  - app/models/channel_enums.py")
print("  - app/models/channel_identity.py")
print("  - Updated app/models/conversation.py")
print("  - alembic/versions/0006_channel_foundation.py")
print("  - Updated app/models/__init__.py")
print("\nNext: Run tests to verify no regressions")
