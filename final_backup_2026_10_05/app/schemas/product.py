import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProductBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    sku: Optional[str] = Field(default=None, max_length=64)
    price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name cannot be empty")
        return value

    @field_validator("sku")
    @classmethod
    def _blank_sku_to_none(cls, value: Optional[str]) -> Optional[str]:
        """An empty/whitespace SKU is treated as "no SKU" (NULL), not as
        the literal empty string -- otherwise two products with sku=""
        in the same store would collide on the unique constraint."""
        if value is not None and value.strip() == "":
            return None
        return value


class ProductCreate(ProductBase):
    # Optional convenience: set the starting stock in the same request
    # that creates the product, instead of a separate inventory call.
    initial_quantity: int = Field(default=0, ge=0)


class ProductUpdate(BaseModel):
    """
    All fields optional for PATCH semantics. The router calls
    `.model_dump(exclude_unset=True)` so that only fields the client
    actually sent are applied -- a field omitted from the request body
    is left untouched, while a field explicitly sent as null does get
    applied (relevant for clearing `description` or `sku`).
    """

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    sku: Optional[str] = Field(default=None, max_length=64)
    price: Optional[Decimal] = Field(
        default=None, ge=0, max_digits=12, decimal_places=2
    )
    is_active: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError("name cannot be empty")
        return value

    @field_validator("sku")
    @classmethod
    def _blank_sku_to_none(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value.strip() == "":
            return None
        return value


class ProductOut(BaseModel):
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
