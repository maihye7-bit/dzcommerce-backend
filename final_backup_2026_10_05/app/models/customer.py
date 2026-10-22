"""
Customer model - Independent customer profile linked to stores.
"""
import uuid
from datetime import datetime
# تأكد من وجود DateTime هنا 👇
from sqlalchemy import String, ForeignKey, func, DateTime 
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)
    
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    
    # External identifiers for social channels
    facebook_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    whatsapp_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
