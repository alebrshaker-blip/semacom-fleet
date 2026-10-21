from sqlalchemy import CheckConstraint, ForeignKey, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base, DictMixin

_NOW_TEXT = text("to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')")


class ComprehensiveInspection(DictMixin, Base):
    __tablename__ = "comprehensive_inspections"
    __table_args__ = (
        CheckConstraint("current_mileage IS NULL OR current_mileage >= 0", name="current_mileage_nonneg"),
        CheckConstraint("oil_change_mileage IS NULL OR oil_change_mileage >= 0", name="oil_change_mileage_nonneg"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vehicle_plate: Mapped[str] = mapped_column(Text, nullable=False)
    inspector_name: Mapped[str] = mapped_column(Text, nullable=False)
    inspector_names_json: Mapped[str | None] = mapped_column(Text)
    inspector_ids_json: Mapped[str | None] = mapped_column(Text)
    inspection_date: Mapped[str] = mapped_column(Text, nullable=False)
    current_mileage: Mapped[int | None] = mapped_column(Integer)
    oil_change_mileage: Mapped[int | None] = mapped_column(Integer)
    overall_status: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    document_number: Mapped[str | None] = mapped_column(Text, server_default="No.000000")
    created_at: Mapped[str | None] = mapped_column(Text, server_default=_NOW_TEXT)


class ComprehensiveInspectionItem(DictMixin, Base):
    __tablename__ = "comprehensive_inspection_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inspection_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("comprehensive_inspections.id", ondelete="CASCADE")
    )
    category: Mapped[str | None] = mapped_column(Text)
    item_name: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text)
    item_notes: Mapped[str | None] = mapped_column(Text)
