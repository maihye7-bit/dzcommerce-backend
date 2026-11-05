"""
ChannelIdentity: Maps external platform user IDs to internal customers.
A single Customer can have multiple ChannelIdentities (one per platform).
Strict tenant isolation via store_id.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.channel_enums import ChannelType


class ChannelIdentity(Base):
    __tablename__ = "channel_identities"
    __table_args__ = (
        # Same external_id on same channel can't belong to two customers in same store
        UniqueConstraint(
            "store_id",
            "channel",
            "external_account_id",
            "external_user_id",
            name="uq_channel_identity_store_channel_ext_user",
        ),
        Index("ix_channel_identities_customer", "store_id", "customer_id"),
        Index(
            "ix_channel_identities_lookup",
            "store_id",
            "channel",
            "external_account_id",
            "external_user_id",
        ),
        Index(
            "uq_channel_identity_legacy_user",
            "store_id",
            "channel",
            "external_user_id",
            unique=True,
            postgresql_where=text("external_account_id IS NULL"),
            sqlite_where=text("external_account_id IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel: Mapped[ChannelType] = mapped_column(String(20), nullable=False)
    external_account_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    external_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    external_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
