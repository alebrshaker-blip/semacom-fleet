from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from core.database import get_session, now_text
from modules.workshop.store.models.store_model import StoreItem, StoreTransaction


class StoreService:

    @classmethod
    def get_all_items(cls):
        """جلب جميع أصناف المستودع المسجلة"""
        with get_session() as session:
            return list(session.scalars(select(StoreItem).order_by(StoreItem.id.desc())))

    @classmethod
    def add_item(cls, item_code, name, category, unit, quantity, min_limit, location, unit_price, notes):
        """إضافة صنف جديد إلى المستودع مع تسجيل حركة توريد أولية"""
        try:
            with get_session() as session:
                session.add(StoreItem(
                    item_code=item_code, name=name, category=category, unit=unit,
                    quantity=quantity, min_limit=min_limit, location=location,
                    unit_price=unit_price, notes=notes,
                ))
                session.flush()
                if quantity > 0:
                    session.add(StoreTransaction(
                        item_code=item_code, transaction_type='in', quantity=quantity,
                        reference_number='INIT', recipient_or_supplier='رصيد افتتاحي',
                        transaction_date=now_text(), notes='إضافة أولية عند إنشاء الصنف',
                    ))
            return True, "تم إضافة الصنف بنجاح وتوثيق الرصيد."
        except IntegrityError:
            return False, "خطأ: كود الصنف (الباركود) مسجل مسبقاً، يرجى استخدام كود فريد."
        except Exception as e:
            return False, f"حدث خطأ غير متوقع: {str(e)}"

    @classmethod
    def delete_item(cls, item_id):
        """حذف صنف المستودع وحركاته المرتبطة كوحدة واحدة."""
        try:
            with get_session() as session:
                item = session.get(StoreItem, item_id, with_for_update=True)
                if item is None:
                    return False, 'الصنف غير موجود أو سبق حذفه.'
                session.execute(delete(StoreTransaction).where(StoreTransaction.item_code == item.item_code))
                session.delete(item)
            return True, 'تم حذف الصنف وحركاته المخزنية المرتبطة.'
        except Exception as error:
            return False, f'تعذر حذف الصنف: {error}'
