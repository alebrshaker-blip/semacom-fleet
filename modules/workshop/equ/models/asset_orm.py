from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class WorkshopAssetRecord(Base):
    __tablename__ = "workshop_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str | None] = mapped_column(Text, default="متاح", server_default="متاح")
    location: Mapped[str | None] = mapped_column(Text)
    purchase_date: Mapped[str | None] = mapped_column(Text)
    condition_status: Mapped[str | None] = mapped_column(Text, default="جيد", server_default="جيد")
    notes: Mapped[str | None] = mapped_column(Text)
