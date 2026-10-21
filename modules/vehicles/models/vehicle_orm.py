from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base

AVAILABLE = "متاحة"

CORE_COLUMNS = (
    "vehicle_code", "plate_number", "vehicle_type", "model", "manufacturer", "color",
    "fuel_type", "engine_number", "chassis_number", "status", "workshop_status", "ownership",
)


class Vehicle(Base):
    """Core vehicle columns. User-defined custom fields are extra TEXT columns on
    the same table (see VehicleField) and are handled by the repository."""

    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plate_number: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    vehicle_code: Mapped[str | None] = mapped_column(Text)
    vehicle_type: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    manufacturer: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str | None] = mapped_column(Text)
    fuel_type: Mapped[str | None] = mapped_column(Text)
    engine_number: Mapped[str | None] = mapped_column(Text)
    chassis_number: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text, default=AVAILABLE, server_default=AVAILABLE)
    workshop_status: Mapped[str | None] = mapped_column(Text, default=AVAILABLE, server_default=AVAILABLE)
    ownership: Mapped[str | None] = mapped_column(Text)

    archive: Mapped["VehicleArchive | None"] = relationship(
        back_populates="vehicle", uselist=False, passive_deletes=True
    )


class VehicleField(Base):
    __tablename__ = "vehicle_fields"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    required: Mapped[int | None] = mapped_column(Integer, default=0, server_default="0")


class VehicleArchive(Base):
    __tablename__ = "vehicle_archive"
    __table_args__ = (
        CheckConstraint("sale_value IS NULL OR sale_value >= 0", name="sale_value_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vehicle_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("vehicles.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    buyer_name: Mapped[str | None] = mapped_column(Text)
    sale_value: Mapped[float | None] = mapped_column(Float)
    handover_date: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    previous_status: Mapped[str | None] = mapped_column(Text)
    previous_workshop_status: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[str] = mapped_column(
        Text, nullable=False,
        server_default=text("to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')"),
    )

    vehicle: Mapped[Vehicle] = relationship(back_populates="archive")
