from sqlalchemy import Float, ForeignKey, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base, DictMixin

_NOW_TEXT = text("to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')")


class Inspection(DictMixin, Base):
    __tablename__ = "inspections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vehicle_plate: Mapped[str] = mapped_column(Text, ForeignKey("vehicles.plate_number"), nullable=False)
    inspection_center: Mapped[str | None] = mapped_column(Text)
    inspection_date: Mapped[str | None] = mapped_column(Text)
    expiry_date: Mapped[str | None] = mapped_column(Text)
    result_status: Mapped[str | None] = mapped_column(Text, server_default="ناجح")
    inspection_cost: Mapped[float | None] = mapped_column(Float, server_default="0.0")
    attachment: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text, server_default="active")
    status_type: Mapped[str | None] = mapped_column(Text, server_default="ساري")
    created_at: Mapped[str | None] = mapped_column(Text, server_default=_NOW_TEXT)
