from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StoreMetaConnection(BaseModel):
    status: Literal["incomplete", "connected"]
    connected: bool
    verified: bool = False
    pageId: str | None = None
    pageName: str | None = None


class StoreMetaConnectionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    page_name: str = Field(alias="pageName", min_length=1, max_length=255)
    page_id: str = Field(alias="pageId", min_length=1, max_length=255)
    page_access_token: str = Field(
        alias="pageAccessToken", min_length=20, max_length=4096
    )

    @field_validator("page_name", "page_id", "page_access_token")
    @classmethod
    def trim_required_values(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field is required")
        return value