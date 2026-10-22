"""
Unified Conversation & Message Models for Phase 13.
FIXED: Removed duplicate class definitions and Enum conflicts.
Single source of truth for conversation state and order drafts.
"""
import uuid
from datetime import datetime
from sqlalchemy import String, Text, DateTime, ForeignKey, func, JSON
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class ConversationStatus:
    ACTIVE = "active"
    CLOSED = "closed"
    HANDOFF = "handoff"


class MessageRole:
    CUSTOMER = "customer"
    AGENT = "agent"
    SYSTEM = "system"


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), 
        ForeignKey("stores.id", ondelete="CASCADE"), 
        nullable=False,
        index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), 
        ForeignKey("customers.id", ondelete="CASCADE"), 
        nullable=False,
        index=True
    )
    
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    
    # UNIFIED AS STRING to match DB migration and avoid Enum conflicts
    status: Mapped[str] = mapped_column(
        String(20), 
        default=ConversationStatus.ACTIVE, 
        nullable=False
    )
    
    external_conversation_id: Mapped[str | None] = mapped_column(
        String(255), 
        nullable=True
    )
    
    # PHASE 13 CORE FEATURE: Structured Order Draft Storage
    # MutableDict tracks in-place mutations; DB column type stays JSON (no migration).
    active_draft_json: Mapped[dict | None] = mapped_column(
        MutableDict.as_mutable(JSON),
        nullable=True
    )

    # NEW FIELD FOR STRUCTURED CONTEXT (Selected Product, etc.)
    metadata_json: Mapped[dict | None] = mapped_column(
        MutableDict.as_mutable(JSON),
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now(), 
        onupdate=func.now()
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", 
        cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), 
        primary_key=True, 
        default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), 
        ForeignKey("conversations.id", ondelete="CASCADE"), 
        nullable=False,
        index=True
    )
    
    # UNIFIED AS STRING
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    
    message_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    
    # CRITICAL FOR IDEMPOTENCY: Must remain UNIQUE
    external_message_id: Mapped[str | None] = mapped_column(
        String(255), 
        nullable=True,
        unique=True 
    )
    
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now()
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
