"""Dashboard layout and per-user read receipts over existing operational records."""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DashboardConfiguration(Base):
    __tablename__ = "dashboard_configurations"
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    industry: Mapped[str] = mapped_column(String(30), default="general")
    widgets: Mapped[list] = mapped_column(JSON)
    visible_modules: Mapped[list] = mapped_column(JSON)


class NotificationReceipt(Base):
    __tablename__ = "notification_receipts"
    __table_args__ = (UniqueConstraint("organization_id", "user_id", "notification_key"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    notification_key: Mapped[str] = mapped_column(String(120))
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
