from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class StoreMetaConnection(BaseModel):
    status: Literal["incomplete", "connected"]
    connected: bool
    verified: bool = False
    pageId: str | None = None
    pageName: str | None = None


class StoreMetaConnectionRequest(BaseModel):
    page_name: str = Field(min_length=1, max_length=255)
    page_id: str = Field(min_length=1, max_length=255)
    page_access_token: str = Field(min_length=20, max_length=4096)

    @model_validator(mode="before")
    @classmethod
    def accept_camel_case_fields(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        value = value.copy()
        for field_name, alias in (
            ("page_name", "pageName"),
            ("page_id", "pageId"),
            ("page_access_token", "pageAccessToken"),
        ):
            if alias in value:
                value[field_name] = value.pop(alias)
        return value

    @field_validator("page_name", "page_id", "page_access_token")
    @classmethod
    def trim_required_values(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field is required")
        return value