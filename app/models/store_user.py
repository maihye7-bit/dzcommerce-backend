import enum
import uuid
from datetime import datetime
from sqlalchemy import DateTime, Enum, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

class StoreRole(str, enum.Enum):
    OWNER = "owner"
    STAFF = "staff"

class StoreUser(Base):
    __tablename__ = "store_users"
    __table_args__ = (UniqueConstraint("store_id", "user_id", name="uq_store_user"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[StoreRole] = mapped_column(
        Enum(StoreRole, name="store_role", values_callable=lambda e: [m.value for m in e]),
        default=StoreRole.STAFF, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    store: Mapped["Store"] = relationship("Store", back_populates="user_links")
    user: Mapped["User"] = relationship("User", back_populates="store_links")
