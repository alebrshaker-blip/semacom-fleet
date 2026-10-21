from core.database import init_orm_schema


def init_accidents_db():
    """تهيئة جدول الحوادث عبر نماذج ORM (إنشاء الجدول والأعمدة الناقصة)."""
    init_orm_schema()
