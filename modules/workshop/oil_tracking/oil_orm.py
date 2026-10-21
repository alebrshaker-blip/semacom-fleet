from sqlalchemy import CheckConstraint, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base, DictMixin

_NOW_TEXT = text("to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')")


class OilChangeRecord(DictMixin, Base):
    __tablename__ = "oil_change_tracking"
    __table_args__ = (
        CheckConstraint("current_mileage IS NULL OR current_mileage >= 0", name="current_mileage_nonneg"),
        CheckConstraint("last_oil_mileage IS NULL OR last_oil_mileage >= 0", name="last_oil_mileage_nonneg"),
        CheckConstraint("distance_interval IS NULL OR distance_interval > 0", name="distance_interval_positive"),
        CheckConstraint("time_interval_months IS NULL OR time_interval_months > 0", name="time_interval_positive"),
        CheckConstraint("distance_alert_threshold IS NULL OR distance_alert_threshold >= 0", name="distance_threshold_nonneg"),
        CheckConstraint("time_alert_threshold IS NULL OR time_alert_threshold >= 0", name="time_threshold_nonneg"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vehicle_plate: Mapped[str] = mapped_column(Text, nullable=False)
    technician_name: Mapped[str] = mapped_column(Text, nullable=False)
    service_date: Mapped[str] = mapped_column(Text, nullable=False)
    current_mileage: Mapped[int | None] = mapped_column(Integer)
    last_oil_mileage: Mapped[int | None] = mapped_column(Integer)
    distance_interval: Mapped[int | None] = mapped_column(Integer, server_default="5000")
    time_interval_months: Mapped[int | None] = mapped_column(Integer, server_default="3")
    distance_alert_threshold: Mapped[int | None] = mapped_column(Integer, server_default="1000")
    time_alert_threshold: Mapped[int | None] = mapped_column(Integer, server_default="15")
    tracking_mode: Mapped[str | None] = mapped_column(Text, server_default="distance")
    overall_status: Mapped[str | None] = mapped_column(Text, server_default="سليم")
    notes: Mapped[str | None] = mapped_column(Text)
    document_number: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text, server_default=_NOW_TEXT)
