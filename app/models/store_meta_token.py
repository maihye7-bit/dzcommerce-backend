"""
StoreMetaToken: Stores the Meta (Facebook) connection details for a store.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class StoreMetaToken(Base):
    __tablename__ = "store_meta_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    page_id: Mapped[str] = mapped_column(String(255), nullable=False)
    page_name: Mapped[str] = mapped_column(String(255), nullable=False)
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    instagram_page_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Ensure only one token per store
    __table_args__ = (
        UniqueConstraint("store_id", name="uq_store_meta_token_store_id"),
    )