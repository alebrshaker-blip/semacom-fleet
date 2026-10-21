from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class Driver(Base):
    __tablename__ = "drivers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    national_id: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    nationality: Mapped[str | None] = mapped_column(Text)
    job_title: Mapped[str | None] = mapped_column(Text)
    department: Mapped[str | None] = mapped_column(Text)
    license_number: Mapped[str | None] = mapped_column(Text)
    license_type: Mapped[str | None] = mapped_column(Text)
    restrictions_count: Mapped[int | None] = mapped_column(Integer, default=0, server_default="0")
    license_issue_date: Mapped[str | None] = mapped_column(Text)
    license_expiry_date: Mapped[str | None] = mapped_column(Text)

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
