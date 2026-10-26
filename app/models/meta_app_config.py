"""
MetaAppConfig: Stores the global Meta (Facebook) App configuration.
"""
import uuid
from datetime import datetime

from sqlalchemy import (DateTime, ForeignKey, Index, String, UniqueConstraint,
                        func)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MetaAppConfig(Base):
    __tablename__ = "meta_app_config"
    # We'll store only one row; we can enforce that via a unique constraint on a constant.
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    app_id: Mapped[str] = mapped_column(String(255), nullable=False)
    app_secret: Mapped[str] = mapped_column(String(255), nullable=False)
    verification_token: Mapped[str] = mapped_column(String(255), nullable=False)
    # Optional: access token for making API calls on behalf of the app (not needed for webhook verification)
    access_token: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.onupdate(func.now())
    )

    # Ensure only one row exists
    __table_args__ = (
        UniqueConstraint("id", name="uq_meta_app_config_id"),
    )