from sqlalchemy import ForeignKey, Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base, DictMixin

_NOW_TEXT = text("to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')")


class User(DictMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    google_drive_email: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str | None] = mapped_column(Text, server_default="admin")
    is_active: Mapped[int | None] = mapped_column(Integer, server_default="1")
    created_at: Mapped[str | None] = mapped_column(Text, server_default=_NOW_TEXT)
    updated_at: Mapped[str | None] = mapped_column(Text, server_default=_NOW_TEXT)


class SystemSetting(DictMixin, Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)
    setting_type: Mapped[str | None] = mapped_column(Text, server_default="string")
    group_name: Mapped[str | None] = mapped_column(Text, server_default="general")
    description: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(Text, server_default=_NOW_TEXT)


class PasswordResetToken(DictMixin, Base):
    __tablename__ = "password_reset_tokens"
    __table_args__ = (
        Index("idx_password_reset_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    expires_at: Mapped[str] = mapped_column(Text, nullable=False)
    used_at: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=_NOW_TEXT)


class DriverField(DictMixin, Base):
    __tablename__ = "driver_fields"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    required: Mapped[int | None] = mapped_column(Integer, server_default="0")
