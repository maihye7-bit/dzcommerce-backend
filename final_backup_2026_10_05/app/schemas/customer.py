import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    store_id: uuid.UUID
    external_id: Optional[str]
    name: Optional[str]
    phone: Optional[str]
    email: Optional[str]
    language: Optional[str]
    created_at: datetime
