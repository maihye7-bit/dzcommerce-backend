"""
API endpoints for retrieving conversation history.
Ensures safe data serialization to prevent frontend crashes.
"""

import uuid
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database import get_db
from app.models.conversation import Conversation, Message
from app.models.store_user import StoreUser
from app.models.user import User

router = APIRouter(prefix="/conversations", tags=["conversations"])

# --- Pydantic Schemas ---


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationSummary(BaseModel):
    id: str
    customer_external_id: str
    channel: str
    last_message_preview: str
    updated_at: datetime

    class Config:
        from_attributes = True


# --- Endpoints ---


@router.get("/", response_model=List[ConversationSummary])
def list_recent_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = 20,
):
    """
    Get recent conversations with safe defaults for null fields.
    """
    conversations = (
        db.query(Conversation)
        .join(StoreUser, StoreUser.store_id == Conversation.store_id)
        .filter(StoreUser.user_id == current_user.id)
        .order_by(Conversation.updated_at.desc())
        .limit(max(1, min(limit, 100)))
        .all()
    )

    results = []
    for conv in conversations:
        # Safe extraction of last message preview
        last_msg = (
            db.query(Message)
            .filter(Message.conversation_id == conv.id)
            .order_by(Message.created_at.desc())
            .first()
        )

        preview = ""
        if last_msg:
            raw_content = last_msg.content or ""
            preview = raw_content[:50].replace("\n", " ") + (
                "..." if len(raw_content) > 50 else ""
            )

        # SAFETY FIX: Ensure external_conversation_id is never None/Undefined in JSON
        ext_id = conv.external_conversation_id
        if not ext_id:
            ext_id = f"Guest-{str(conv.id)[:6]}"

        results.append(
            {
                "id": str(conv.id),
                "customer_external_id": str(ext_id),
                "channel": conv.channel or "unknown",
                "last_message_preview": preview,
                "updated_at": conv.updated_at,
            }
        )

    return results


@router.get("/{conversation_id}/messages", response_model=List[MessageOut])
def get_conversation_messages(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get full chat history for a specific conversation.
    """
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Conversation ID format")

    conversation = (
        db.query(Conversation)
        .join(StoreUser, StoreUser.store_id == Conversation.store_id)
        .filter(
            Conversation.id == conv_uuid,
            StoreUser.user_id == current_user.id,
        )
        .first()
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.asc())
        .all()
    )

    formatted_messages = []
    for msg in messages:
        formatted_messages.append(
            {
                "id": str(msg.id),
                "role": msg.role.value if hasattr(msg.role, "value") else str(msg.role),
                "content": msg.content or "",
                "created_at": msg.created_at,
            }
        )

    return formatted_messages
