from sqlalchemy import Float, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base, DictMixin


class Accident(DictMixin, Base):
    __tablename__ = "accidents"
    __table_args__ = (
        Index("ix_accidents_vehicle_datetime", "vehicle_plate", "accident_datetime"),
        Index("ix_accidents_status_datetime", "status_type", "accident_datetime"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    accident_number: Mapped[str | None] = mapped_column(Text)
    vehicle_plate: Mapped[str | None] = mapped_column(Text)
    driver_name: Mapped[str | None] = mapped_column(Text)
    accident_type: Mapped[str | None] = mapped_column(Text)
    issuer: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    accident_datetime: Mapped[str | None] = mapped_column(Text)
    repair_cost: Mapped[float | None] = mapped_column(Float)
    description: Mapped[str | None] = mapped_column(Text)
    accident_attachment: Mapped[str | None] = mapped_column(Text)
    accident_attachment_2: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text, server_default="active")
    status_type: Mapped[str | None] = mapped_column(Text, server_default="جاري المتابعة")
    closure_reason: Mapped[str | None] = mapped_column(Text)
    closure_notes: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[str | None] = mapped_column(Text)
    payment_attachment: Mapped[str | None] = mapped_column(Text)
    document_number: Mapped[str | None] = mapped_column(Text)
