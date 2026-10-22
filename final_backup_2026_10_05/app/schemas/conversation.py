import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    store_id: uuid.UUID
    customer_id: uuid.UUID
    channel: str
    status: str
    created_at: datetime


class AgentChatRequest(BaseModel):
    store_id: str
    conversation_id: Optional[str] = None
    customer_external_id: Optional[str] = None
    message: str
    channel: str = "api"


class ToolCallInfo(BaseModel):
    tool_name: str
    arguments: dict
    result: dict | str


class AgentChatResponse(BaseModel):
    response: str
    conversation_id: uuid.UUID
    handoff: bool
    tool_calls: list[ToolCallInfo] = []
