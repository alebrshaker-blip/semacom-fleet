from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base, DictMixin


class TeamMember(DictMixin, Base):
    __tablename__ = "team_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    full_name: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)
    national_id: Mapped[str | None] = mapped_column(Text)
    nationality: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    job_title: Mapped[str | None] = mapped_column(Text)
    qualification: Mapped[str | None] = mapped_column(Text)
    specialization: Mapped[str | None] = mapped_column(Text)
    license_number: Mapped[str | None] = mapped_column(Text)
    license_type: Mapped[str | None] = mapped_column(Text)
    license_issue_date: Mapped[str | None] = mapped_column(Text)
    license_expiry_date: Mapped[str | None] = mapped_column(Text)
    license_status: Mapped[str | None] = mapped_column(Text, server_default="غير محدد")


class TeamField(DictMixin, Base):
    __tablename__ = "team_fields"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str | None] = mapped_column(Text, unique=True)
    label: Mapped[str | None] = mapped_column(Text)
    required: Mapped[int | None] = mapped_column(Integer, server_default="0")
