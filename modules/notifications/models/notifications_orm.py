from sqlalchemy import Integer, PrimaryKeyConstraint, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base, DictMixin


class NotificationUserState(DictMixin, Base):
    __tablename__ = "notification_user_state"
    __table_args__ = (PrimaryKeyConstraint("user_id", "notification_id"),)

    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    notification_id: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_pinned: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_deleted: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    updated_at: Mapped[str] = mapped_column(
        Text, nullable=False,
    )


class EmailDeliveryRun(DictMixin, Base):
    __tablename__ = "email_delivery_runs"

    delivery_key: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[str] = mapped_column(
        Text, nullable=False,
        server_default=text("to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')"),
    )
    completed_at: Mapped[str | None] = mapped_column(Text)
