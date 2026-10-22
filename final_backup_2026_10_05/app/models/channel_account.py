"""
ChannelAccount: Maps a Store to its external platform accounts.
Each store can have one account per channel type.
Credentials/tokens are NEVER stored here - only non-sensitive identifiers.
Sensitive config comes from environment variables at runtime.
"""

import uuid
from datetime import datetime

from sqlalchemy import (DateTime, ForeignKey, Index, String, UniqueConstraint,
                        func)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ChannelAccount(Base):
    __tablename__ = "channel_accounts"
    __table_args__ = (
        # One account per channel per store
        UniqueConstraint(
            "store_id", "channel", name="uq_channel_account_store_channel"
        ),
        Index("ix_channel_accounts_external", "channel", "external_account_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    external_account_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Page ID / IG Account ID / WA Phone Number ID",
    )
    external_account_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Human-readable name (page name, business name)",
    )
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
