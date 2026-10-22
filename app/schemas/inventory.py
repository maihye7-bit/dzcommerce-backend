import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class InventoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    store_id: uuid.UUID
    variant_id: uuid.UUID
    quantity: int
    updated_at: datetime


class InventoryUpdate(BaseModel):
    quantity: int = Field(ge=0)
