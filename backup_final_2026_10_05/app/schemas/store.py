import uuid

from pydantic import BaseModel, ConfigDict

from app.models.store_user import StoreRole


class StoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    is_active: bool


class MyStoreOut(StoreOut):
    role: StoreRole
