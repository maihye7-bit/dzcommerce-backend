"""
Phase 7 Part 1 - Infrastructure & Security
Run: python setup_phase7_part1.py
"""
import os

def write_file(path, content):
    dir_name = os.path.dirname(path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"  Created: {path}")

print("\n=== Phase 7 Part 1: Infrastructure & Security ===\n")

# ============================================================
# 1. CHANNEL ACCOUNT MODEL
# ============================================================
write_file("app/models/channel_account.py", '''"""
ChannelAccount: Maps a Store to its external platform accounts.
Each store can have one account per channel type.
Credentials/tokens are NEVER stored here - only non-sensitive identifiers.
Sensitive config comes from environment variables at runtime.
"""
import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, func, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ChannelAccount(Base):
    __tablename__ = "channel_accounts"
    __table_args__ = (
        # One account per channel per store
        UniqueConstraint("store_id", "channel", name="uq_channel_account_store_channel"),
        Index("ix_channel_accounts_external", "channel", "external_account_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    external_account_id: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="Page ID / IG Account ID / WA Phone Number ID"
    )
    external_account_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="Human-readable name (page name, business name)"
    )
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
''')

# ============================================================
# 2. WEBHOOK SECURITY SERVICE
# ============================================================
write_file("app/services/webhook_security.py", '''"""
WebhookSecurityService: Validates webhook signatures from Meta platforms.

Supports:
  - Facebook/Instagram: X-Hub-Signature-256 header (HMAC-SHA256)
  - WhatsApp Cloud API: X-Hub-Signature-256 header (HMAC-SHA256)

Both use the same HMAC-SHA256 mechanism with the app secret.
Reference: https://developers.facebook.com/docs/graph-api/webhooks/getting-started/
           https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks
"""
import hashlib
import hmac
import os
from typing import Optional


def _get_app_secret() -> str:
    """Get Meta app secret from environment. Never hard-code."""
    secret = os.environ.get("META_APP_SECRET", "")
    if not secret:
        raise RuntimeError(
            "META_APP_SECRET environment variable is not set. "
            "Webhook signature verification cannot proceed."
        )
    return secret


def verify_meta_signature(
    payload_body: bytes,
    signature_header: Optional[str],
    app_secret: Optional[str] = None,
) -> bool:
    """
    Verify X-Hub-Signature-256 header from Meta webhooks.
    
    Used by Facebook Messenger, Facebook Comments, Instagram DMs,
    Instagram Comments, and WhatsApp Cloud API.
    
    Args:
        payload_body: Raw request body as bytes
        signature_header: Value of X-Hub-Signature-256 header
        app_secret: Override for testing; defaults to env var
        
    Returns:
        True if signature is valid, False otherwise
    """
    if not signature_header:
        return False

    secret = app_secret or _get_app_secret()

    # Header format: sha256=<hex_digest>
    if not signature_header.startswith("sha256="):
        return False

    expected_hash = signature_header[7:]  # Strip "sha256=" prefix

    computed_hash = hmac.new(
        key=secret.encode("utf-8"),
        msg=payload_body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    # Constant-time comparison to prevent timing attacks
    return hmac.compare_digest(computed_hash, expected_hash)


def verify_whatsapp_verify_token(
    verify_token_param: str,
) -> bool:
    """
    Verify the hub.verify_token parameter during WhatsApp webhook setup.
    
    During initial webhook registration, WhatsApp sends a GET request with
    hub.mode=subscribe, hub.verify_token=<token>, hub.challenge=<challenge>.
    We must validate the token and echo back the challenge.
    """
    expected_token = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
    if not expected_token:
        raise RuntimeError("WHATSAPP_VERIFY_TOKEN environment variable is not set.")
    return hmac.compare_digest(verify_token_param, expected_token)


def verify_meta_verify_token(
    verify_token_param: str,
) -> bool:
    """
    Verify the hub.verify_token parameter during Facebook/Instagram webhook setup.
    Same mechanism as WhatsApp but may use a different token value.
    """
    expected_token = os.environ.get("META_VERIFY_TOKEN", "")
    if not expected_token:
        raise RuntimeError("META_VERIFY_TOKEN environment variable is not set.")
    return hmac.compare_digest(verify_token_param, expected_token)
''')

# ============================================================
# 3. MIGRATION 0007
# ============================================================
write_file("alembic/versions/0007_channel_accounts.py", '''"""channel accounts: store-to-platform mapping
Revision ID: 0007
Revises: 0006
Create Date: 2026-09-15
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "channel_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("store_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("external_account_id", sa.String(255), nullable=False),
        sa.Column("external_account_name", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("store_id", "channel", name="uq_channel_account_store_channel"),
    )
    op.create_index("ix_channel_accounts_external", "channel_accounts", ["channel", "external_account_id"])


def downgrade() -> None:
    op.drop_index("ix_channel_accounts_external", table_name="channel_accounts")
    op.drop_table("channel_accounts")
''')

# ============================================================
# 4. UPDATE models/__init__.py
# ============================================================
write_file("app/models/__init__.py", '''"""
Import every model here so that Base.metadata knows about all tables.
Phase 1: auth + multi-tenancy
Phase 2: products + inventory
Phase 3: customers, orders, conversations, messages, human_handoffs
Phase 4: customer_memories
Phase 5: order workflow (expanded statuses)
Phase 6: channel foundation (channel_identities, external IDs)
Phase 7: channel accounts (store-to-platform mapping)
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
]
''')

# ============================================================
# 5. SAMPLE .env.example
# ============================================================
write_file(".env.example", '''# ============================================
# DzCommerce AI - Environment Variables
# Copy this file to .env and fill in values
# NEVER commit .env to version control
# ============================================

# Database
DATABASE_URL=postgresql://user:password@localhost:5432/dzcommerce

# JWT Auth
SECRET_KEY=your-secret-key-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# Meta Platform (Facebook + Instagram)
META_APP_ID=
META_APP_SECRET=
META_VERIFY_TOKEN=
META_ACCESS_TOKEN=

# WhatsApp Cloud API
WHATSAPP_ACCESS_TOKEN=
WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_BUSINESS_ACCOUNT_ID=
WHATSAPP_VERIFY_TOKEN=
''')

print("\n=== Part 1 Complete ===")
print("Created:")
print("  - app/models/channel_account.py")
print("  - app/services/webhook_security.py")
print("  - alembic/versions/0007_channel_accounts.py")
print("  - Updated app/models/__init__.py")
print("  - .env.example")
print("\nNext: Run tests to verify no regressions")
