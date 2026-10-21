from core.database import init_orm_schema


class CompInspectionModel:
    @classmethod
    def init_db(cls):
        """إنشاء جداول الفحص الشامل من نماذج SQLAlchemy"""
        init_orm_schema()
