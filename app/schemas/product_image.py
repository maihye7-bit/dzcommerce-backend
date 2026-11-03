import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional, List

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProductImageBase(BaseModel):
    """Base schema for product image metadata."""
    is_primary: bool = False
    display_order: int = 0


class ProductImageCreate(ProductImageBase):
    """Schema for creating a product image (metadata only, file uploaded separately)."""
    filename: str
    mime_type: str
    file_size: int
    width: Optional[int] = None
    height: Optional[int] = None

    @field_validator("mime_type")
    @classmethod
    def _validate_mime_type(cls, value: str) -> str:
        allowed = {"image/jpeg", "image/png", "image/webp"}
        if value not in allowed:
            raise ValueError(f"Unsupported mime type. Allowed: {', '.join(allowed)}")
        return value


class ProductImageUpdate(BaseModel):
    """Schema for updating product image metadata."""
    is_primary: Optional[bool] = None
    display_order: Optional[int] = None


class ProductImageOut(BaseModel):
    """Schema for product image response."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    store_id: uuid.UUID
    product_id: uuid.UUID
    image_url: str
    thumbnail_url: Optional[str]
    mime_type: str
    file_size: int
    width: Optional[int]
    height: Optional[int]
    is_primary: bool
    display_order: int
    processing_status: str
    embedding_model: Optional[str]
    embedding_version: Optional[str]
    created_at: datetime
    updated_at: datetime


class ProductImageReorder(BaseModel):
    """Schema for reordering product images."""
    image_ids: List[uuid.UUID]

    @field_validator("image_ids")
    @classmethod
    def _validate_not_empty(cls, value: List[uuid.UUID]) -> List[uuid.UUID]:
        if not value:
            raise ValueError("At least one image ID must be provided")
        return value


class ProductWithImagesOut(BaseModel):
    """Product output with images included."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    store_id: uuid.UUID
    name: str
    description: Optional[str]
    sku: Optional[str]
    price: Decimal
    is_active: bool
    created_at: datetime
    updated_at: datetime
    images: List[ProductImageOut] = []

    @field_validator("price", mode="before")
    @classmethod
    def _price_from_base_price(cls, value):
        """Handle both 'price' and 'base_price' fields."""
        if isinstance(value, dict):
            return value.get("base_price") or value.get("price")
        return value