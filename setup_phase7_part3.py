"""
Phase 7 Part 3 - Webhook Endpoints & Processor
Run: python setup_phase7_part3.py
"""
import os

def write_file(path, content):
    dir_name = os.path.dirname(path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"  Created: {path}")

print("\n=== Phase 7 Part 3: Webhook Endpoints ===\n")

# ============================================================
# 1. WEBHOOK LOG MODEL
# ============================================================
write_file("app/models/webhook_log.py", '''"""
WebhookLog: Stores raw webhook payloads for debugging and audit.
"""
import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, ForeignKey, func, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WebhookLog(Base):
    __tablename__ = "webhook_logs"
    __table_args__ = (
        Index("ix_webhook_logs_store", "store_id"),
        Index("ix_webhook_logs_channel", "channel"),
        Index("ix_webhook_logs_external_id", "external_message_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    store_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="SET NULL"), nullable=True
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    external_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    is_processed: Mapped[bool] = mapped_column(default=False, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
''')

# ============================================================
# 2. WEBHOOK PROCESSOR SERVICE
# ============================================================
write_file("app/services/webhook_processor.py", '''"""
WebhookProcessor: The bridge between external webhooks and internal logic.
Handles verification, store resolution, and event dispatching.
"""
import uuid
import json
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.channel_account import ChannelAccount
from app.models.webhook_log import WebhookLog
from app.services import channel_service
from app.schemas.channel_events import InboundEvent
from app.channels.base import ChannelAdapter


async def process_webhook_event(
    db: Session,
    adapter: ChannelAdapter,
    raw_payload: dict[str, Any],
    signature_header: str | None = None,
    payload_bytes: bytes | None = None,
) -> dict:
    """
    Main entry point for all webhooks.
    1. Log the raw payload.
    2. Normalize the event using the adapter.
    3. Resolve the Store via ChannelAccount.
    4. Dispatch to ChannelService.
    """
    # 1. Log raw payload
    log_entry = WebhookLog(
        channel=adapter.channel_name,
        event_type="unknown",
        payload_json=raw_payload,
    )
    db.add(log_entry)
    db.flush()

    try:
        # 2. Normalize
        event = adapter.normalize_inbound_event(raw_payload)
        log_entry.event_type = event.event_type
        log_entry.external_message_id = event.external_message_id

        # 3. Resolve Store (Find which store owns this external account)
        # For Meta/WhatsApp, we usually identify by Page ID or Phone Number ID in metadata
        # Or we can look up by external_user_id if it's a DM to a specific business account
        # For simplicity in this phase, we assume the adapter metadata contains 'account_id'
        # which maps to ChannelAccount.external_account_id
        
        account_id = event.metadata.get("page_id") or \
                     event.metadata.get("ig_account_id") or \
                     event.metadata.get("phone_number")
        
        if not account_id:
            raise HTTPException(status_code=400, detail="Cannot identify target account from payload")

        account = (
            db.query(ChannelAccount)
            .filter(
                ChannelAccount.channel == adapter.channel_name,
                ChannelAccount.external_account_id == account_id,
                ChannelAccount.is_active == True
            )
            .first()
        )

        if not account:
            raise HTTPException(status_code=404, detail="No active store found for this account")

        log_entry.store_id = account.store_id

        # 4. Dispatch to Channel Service
        result = channel_service.handle_inbound_event(db, account.store_id, event)
        
        log_entry.is_processed = True
        db.commit()
        
        return result

    except Exception as e:
        log_entry.error_message = str(e)
        db.commit()
        raise HTTPException(status_code=500, detail=f"Webhook processing failed: {str(e)}")
''')

# ============================================================
# 3. API ROUTES (WEBHOOKS)
# ============================================================
write_file("app/api/webhooks.py", '''"""
Webhook endpoints for social channels.
Security: Signature verification + Tenant isolation.
"""
import os
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.webhook_security import verify_meta_signature
from app.services.webhook_processor import process_webhook_event
from app.channels.adapters.facebook_adapter import FacebookAdapter
from app.channels.adapters.instagram_adapter import InstagramAdapter
from app.channels.adapters.whatsapp_adapter import WhatsAppAdapter

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Initialize adapters (in production, these might be singletons or fetched from DI)
fb_adapter = FacebookAdapter()
ig_adapter = InstagramAdapter()
wa_adapter = WhatsAppAdapter()


@router.post("/meta")
async def meta_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Unified endpoint for Facebook and Instagram webhooks.
    Meta sends both to the same callback URL if configured.
    """
    # 1. Verify Signature
    signature = request.headers.get("X-Hub-Signature-256")
    body = await request.body()
    
    if not verify_meta_signature(body, signature):
        raise HTTPException(status_code=403, detail="Invalid signature")

    payload = await request.json()
    
    # 2. Determine channel from payload structure or metadata
    # Meta webhooks usually have 'object' field: 'page' (FB) or 'instagram' (IG)
    obj_type = payload.get("object", "")
    
    if obj_type == "instagram":
        adapter = ig_adapter
    else:
        # Default to Facebook for 'page' or other types
        adapter = fb_adapter

    return await process_webhook_event(db, adapter, payload)


@router.post("/whatsapp")
async def whatsapp_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Endpoint for WhatsApp Cloud API webhooks.
    """
    # 1. Verify Signature
    signature = request.headers.get("X-Hub-Signature-256")
    body = await request.body()
    
    if not verify_meta_signature(body, signature):
        raise HTTPException(status_code=403, detail="Invalid signature")

    payload = await request.json()
    return await process_webhook_event(db, wa_adapter, payload)


@router.get("/meta")
@router.get("/whatsapp")
async def verify_webhook(request: Request):
    """
    Verification handshake for Meta/WhatsApp webhook setup.
    """
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe":
        # Check token against env vars
        expected_token = os.environ.get("META_VERIFY_TOKEN")
        if token == expected_token:
            return int(challenge) if challenge else ""
        else:
            raise HTTPException(status_code=403, detail="Verification token mismatch")
    
    raise HTTPException(status_code=400, detail="Invalid verification request")
''')

# ============================================================
# 4. UPDATE models/__init__.py
# ============================================================
write_file("app/models/__init__.py", '''"""
Import every model here so that Base.metadata knows about all tables.
Phase 7: channel accounts + webhook logs
"""
from app.models.user import User
from app.models.store import Store
from app.models.store_user import StoreUser, StoreRole
from app.models.product import Product
from app.models.inventory import Inventory
from app.models.customer import Customer
from app.models.conversation import Conversation, ConversationStatus, MessageRole, Message
from app.models.order import Order, OrderItem, OrderStatus
from app.models.human_handoff import HumanHandoff
from app.models.customer_memory import CustomerMemory
from app.models.channel_enums import ChannelType, EventType, MessageType
from app.models.channel_identity import ChannelIdentity
from app.models.channel_account import ChannelAccount
from app.models.webhook_log import WebhookLog

__all__ = [
    "User", "Store", "StoreUser", "StoreRole", "Product", "Inventory",
    "Customer",
    "Conversation", "ConversationStatus", "MessageRole", "Message",
    "Order", "OrderItem", "OrderStatus",
    "HumanHandoff",
    "CustomerMemory",
    "ChannelType", "EventType", "MessageType",
    "ChannelIdentity",
    "ChannelAccount",
    "WebhookLog",
]
''')

# ============================================================
# 5. MIGRATION 0008
# ============================================================
write_file("alembic/versions/0008_webhook_logs.py", '''"""webhook logs: audit trail for inbound events
Revision ID: 0008
Revises: 0007
Create Date: 2026-09-15
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "webhook_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("store_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("stores.id", ondelete="SET NULL"), nullable=True),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("external_message_id", sa.String(255), nullable=True),
        sa.Column("payload_json", postgresql.JSONB, nullable=False),
        sa.Column("is_processed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_webhook_logs_store", "webhook_logs", ["store_id"])
    op.create_index("ix_webhook_logs_channel", "webhook_logs", ["channel"])
    op.create_index("ix_webhook_logs_external_id", "webhook_logs", ["external_message_id"])


def downgrade() -> None:
    op.drop_index("ix_webhook_logs_external_id", table_name="webhook_logs")
    op.drop_index("ix_webhook_logs_channel", table_name="webhook_logs")
    op.drop_index("ix_webhook_logs_store", table_name="webhook_logs")
    op.drop_table("webhook_logs")
''')

print("\n=== Part 3 Complete ===")
print("Created:")
print("  - app/models/webhook_log.py")
print("  - app/services/webhook_processor.py")
print("  - app/api/webhooks.py")
print("  - Updated app/models/__init__.py")
print("  - alembic/versions/0008_webhook_logs.py")
print("\nNext: Register routes in main.py and run tests")
