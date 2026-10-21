from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from core.database import get_session
from modules.workshop.equ.models.asset_orm import WorkshopAssetRecord
from modules.workshop.equ.models.equ_model import WorkshopAsset


def _record_to_asset(record):
    return WorkshopAsset.from_row({
        column.name: getattr(record, column.name)
        for column in WorkshopAssetRecord.__table__.columns
    })


class EquService:

    @classmethod
    def get_all_assets(cls):
        """جلب كافة أصول وعدّ الورشة"""
        with get_session() as session:
            records = session.scalars(
                select(WorkshopAssetRecord).order_by(WorkshopAssetRecord.id.desc())
            ).all()
            return [_record_to_asset(record) for record in records]

    @classmethod
    def add_asset(cls, asset_code, name, category, status, location, purchase_date, condition_status, notes):
        """إضافة أصل أو عدة جديدة للورشة"""
        try:
            with get_session() as session:
                session.add(WorkshopAssetRecord(
                    asset_code=asset_code, name=name, category=category, status=status,
                    location=location, purchase_date=purchase_date,
                    condition_status=condition_status, notes=notes,
                ))
            return True, "تم تسجيل الأصل أو العدّة بنجاح."
        except IntegrityError:
            return False, "خطأ: كود الأصل مسجل مسبقاً، يرجى استخدام كود فريد."
        except SQLAlchemyError as error:
            return False, f"حدث خطأ غير متوقع: {error}"

    @classmethod
    def update_asset(cls, asset_id, **fields):
        allowed = {"asset_code", "name", "category", "status", "location",
                   "purchase_date", "condition_status", "notes"}
        try:
            with get_session() as session:
                record = session.get(WorkshopAssetRecord, asset_id)
                if record is None:
                    return False, 'الأصل غير موجود.'
                for key, value in fields.items():
                    if key in allowed:
                        setattr(record, key, value)
            return True, 'تم تحديث بيانات الأصل.'
        except IntegrityError:
            return False, "خطأ: كود الأصل مسجل مسبقاً، يرجى استخدام كود فريد."
        except SQLAlchemyError as error:
            return False, f"حدث خطأ غير متوقع: {error}"

    @classmethod
    def delete_asset(cls, asset_id):
        try:
            with get_session() as session:
                record = session.get(WorkshopAssetRecord, asset_id)
                if record is None:
                    return False, 'الأصل غير موجود أو سبق حذفه.'
                session.delete(record)
            return True, 'تم حذف الأصل من سجلات الورشة.'
        except SQLAlchemyError as error:
            return False, f'تعذر حذف الأصل: {error}'
