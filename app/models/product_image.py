"""
Product Image model - Stores product images with metadata and visual embeddings.
Supports multi-tenancy and visual recognition features.
"""
import uuid
from datetime import datetime
from sqlalchemy import (
    String,
    Boolean,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    DateTime,
    UniqueConstraint,
    Index,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class ProductImage(Base):
    __tablename__ = "product_images"
    __table_args__ = (
        ForeignKeyConstraint(
            ["store_id", "product_id"],
            ["products.store_id", "products.id"],
            name="fk_product_images_store_product",
            ondelete="CASCADE",
        ),
        UniqueConstraint("storage_key", name="uq_product_images_storage_key"),
        Index(
            "uq_product_images_primary_per_product",
            "store_id",
            "product_id",
            unique=True,
            postgresql_where=text("is_primary"),
            sqlite_where=text("is_primary = 1"),
        ),
        Index(
            "ix_product_images_store_product",
            "store_id",
            "product_id",
        ),
        Index(
            "ix_product_images_product_order",
            "store_id",
            "product_id",
            "display_order",
            "created_at",
            "id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )

    # Storage info
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)  # Object storage key/path
    image_url: Mapped[str] = mapped_column(String(1024), nullable=False)  # Public URL for display
    thumbnail_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)  # Optimized thumbnail

    # Image metadata
    mime_type: Mapped[str] = mapped_column(String(50), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Display management
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Visual recognition
    processing_status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedding_version: Mapped[str | None] = mapped_column(String(20), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    product = relationship(
        "Product",
        back_populates="images",
        foreign_keys=[product_id],
    )