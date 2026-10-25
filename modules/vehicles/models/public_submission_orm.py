from sqlalchemy import Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base, DictMixin

_NOW_TEXT = text("to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')")


class VehiclePublicSubmission(DictMixin, Base):
    """Reports submitted through a vehicle's public QR page."""

    __tablename__ = "vehicle_public_submissions"
    __table_args__ = (
        Index("ix_public_submissions_vehicle_submitted", "vehicle_id", "submitted_at"),
        Index("ix_public_submissions_status_submitted", "status", "submitted_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vehicle_id: Mapped[int] = mapped_column(Integer, nullable=False)
    submission_type: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_values: Mapped[str | None] = mapped_column(Text)
    photo_1: Mapped[str | None] = mapped_column(Text)
    photo_2: Mapped[str | None] = mapped_column(Text)
    photo_3: Mapped[str | None] = mapped_column(Text)
    photo_4: Mapped[str | None] = mapped_column(Text)
    photo_5: Mapped[str | None] = mapped_column(Text)
    video_1: Mapped[str | None] = mapped_column(Text)
    audio_1: Mapped[str | None] = mapped_column(Text)
    response: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="جديد")
    submitted_at: Mapped[str | None] = mapped_column(Text, server_default=_NOW_TEXT)
    reviewed_at: Mapped[str | None] = mapped_column(Text)
