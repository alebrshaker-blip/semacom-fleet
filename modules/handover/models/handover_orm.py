from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base, DictMixin


class Handover(DictMixin, Base):
    __tablename__ = "handovers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    handover_type: Mapped[str | None] = mapped_column(Text)
    vehicle_id: Mapped[int | None] = mapped_column(Integer)
    handover_date: Mapped[str | None] = mapped_column(Text)
    vehicle_info: Mapped[str | None] = mapped_column(Text)
    driver_info: Mapped[str | None] = mapped_column(Text)
    purpose: Mapped[str | None] = mapped_column(Text)
    department: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    odometer: Mapped[str | None] = mapped_column(Text)
    fuel_level: Mapped[str | None] = mapped_column(Text)
    body_condition: Mapped[str | None] = mapped_column(Text)
    interior_condition: Mapped[str | None] = mapped_column(Text)
    tires_condition: Mapped[str | None] = mapped_column(Text)
    mechanical_condition: Mapped[str | None] = mapped_column(Text)
    electrical_condition: Mapped[str | None] = mapped_column(Text)
    electrical_technician: Mapped[str | None] = mapped_column(Text)
    mechanical_technician: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text)
    is_certified: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    certified_at: Mapped[str | None] = mapped_column(Text)
    certified_by: Mapped[str | None] = mapped_column(Text)
    document_number: Mapped[str | None] = mapped_column(Text)
    report_data: Mapped[str | None] = mapped_column(Text)
    report_file_path: Mapped[str | None] = mapped_column(Text)


class HandoverRecord(DictMixin, Base):
    """Legacy flat handover log kept for backward compatibility."""

    __tablename__ = "handover_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vehicle_info: Mapped[str | None] = mapped_column(Text)
    driver_info: Mapped[str | None] = mapped_column(Text)
    handover_type: Mapped[str | None] = mapped_column(Text)
    odometer: Mapped[str | None] = mapped_column(Text)
    fuel_level: Mapped[str | None] = mapped_column(Text)
    body_condition: Mapped[str | None] = mapped_column(Text)
    interior_condition: Mapped[str | None] = mapped_column(Text)
    tires_condition: Mapped[str | None] = mapped_column(Text)
    mechanical_condition: Mapped[str | None] = mapped_column(Text)
    electrical_condition: Mapped[str | None] = mapped_column(Text)
    electrical_technician: Mapped[str | None] = mapped_column(Text)
    mechanical_technician: Mapped[str | None] = mapped_column(Text)
    handover_date: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
