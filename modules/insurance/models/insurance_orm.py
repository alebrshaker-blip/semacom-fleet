from sqlalchemy import Float, ForeignKey, Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base, DictMixin


class InsurancePolicy(DictMixin, Base):
    __tablename__ = "insurance_policies"
    __table_args__ = (
        Index("ix_insurance_vehicle_end_date", "vehicle_plate", "end_date"),
        Index("ix_insurance_status_end_date", "status_type", "end_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    policy_number: Mapped[str] = mapped_column(Text, nullable=False)
    vehicle_plate: Mapped[str] = mapped_column(Text, nullable=False)
    insurance_company: Mapped[str] = mapped_column(Text, nullable=False)
    insurance_type: Mapped[str | None] = mapped_column(Text, server_default="شامل")
    start_date: Mapped[str] = mapped_column(Text, nullable=False)
    end_date: Mapped[str] = mapped_column(Text, nullable=False)
    policy_cost: Mapped[float | None] = mapped_column(Float, server_default="0")
    description: Mapped[str | None] = mapped_column(Text)
    policy_attachment: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text, server_default="active")
    status_type: Mapped[str | None] = mapped_column(Text, server_default="ساري")
    created_at: Mapped[str | None] = mapped_column(
        Text,
        server_default=text("to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')"),
    )
