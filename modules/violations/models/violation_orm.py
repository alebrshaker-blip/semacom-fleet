from sqlalchemy import Float, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base, DictMixin


class Violation(DictMixin, Base):
    __tablename__ = "violations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    violation_number: Mapped[str | None] = mapped_column(Text)
    vehicle_plate: Mapped[str | None] = mapped_column(Text)
    driver_name: Mapped[str | None] = mapped_column(Text)
    violation_type: Mapped[str | None] = mapped_column(Text)
    issuer: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    violation_datetime: Mapped[str | None] = mapped_column(Text)
    fine_amount: Mapped[float | None] = mapped_column(Float)
    description: Mapped[str | None] = mapped_column(Text)
    violation_attachment: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text, default="active", server_default="active")
    status_type: Mapped[str | None] = mapped_column(Text, default="نشطة", server_default="نشطة")
    payment_date: Mapped[str | None] = mapped_column(Text)
    payment_receipt: Mapped[str | None] = mapped_column(Text)
    payment_amount: Mapped[float | None] = mapped_column(Float)
    payment_notes: Mapped[str | None] = mapped_column(Text)
    payment_attachment: Mapped[str | None] = mapped_column(Text)
    closure_reason: Mapped[str | None] = mapped_column(Text)
    closure_notes: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[str | None] = mapped_column(Text)
