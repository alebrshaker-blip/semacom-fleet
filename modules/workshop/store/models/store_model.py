from sqlalchemy import Float, ForeignKey, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base, DictMixin

_NOW_TEXT = text("to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')")


class StoreItem(DictMixin, Base):
    __tablename__ = "store_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str | None] = mapped_column(Text, server_default="قطعة")
    quantity: Mapped[int | None] = mapped_column(Integer, server_default="0")
    min_limit: Mapped[int | None] = mapped_column(Integer, server_default="5")
    location: Mapped[str | None] = mapped_column(Text)
    unit_price: Mapped[float | None] = mapped_column(Float, server_default="0.0")
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text, server_default=_NOW_TEXT)

    @property
    def is_low_stock(self):
        return (self.quantity or 0) <= (self.min_limit or 0)

    def to_dict(self):
        data = super().to_dict()
        data['is_low_stock'] = self.is_low_stock
        return data


class StoreTransaction(DictMixin, Base):
    __tablename__ = "store_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_code: Mapped[str] = mapped_column(Text, ForeignKey("store_items.item_code"), nullable=False)
    transaction_type: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    reference_number: Mapped[str | None] = mapped_column(Text)
    recipient_or_supplier: Mapped[str | None] = mapped_column(Text)
    transaction_date: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text, server_default=_NOW_TEXT)
