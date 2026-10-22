import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.store_user import StoreRole


class StoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    is_active: bool


class MyStoreOut(StoreOut):
    role: StoreRole


class StoreUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            raise ValueError("name cannot be empty")
        return value
