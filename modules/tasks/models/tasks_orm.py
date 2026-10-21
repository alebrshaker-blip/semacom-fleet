from sqlalchemy import Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base, DictMixin

_NOW_TEXT = text("to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')")


class TaskRecord(DictMixin, Base):
    __tablename__ = "task_records"
    __table_args__ = (
        UniqueConstraint("user_id", "source_notification_id"),
        Index("idx_task_records_user_status", "user_id", "is_archived", "status", "due_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(Text, nullable=False, server_default="متوسطة")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="مجدولة")
    is_archived: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    source_notification_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=_NOW_TEXT)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=_NOW_TEXT)
    completed_at: Mapped[str | None] = mapped_column(Text)
