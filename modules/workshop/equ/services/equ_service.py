import sqlite3
from modules.workshop.equ.models.equ_model import WorkshopAsset
from core.database import DB_PATH as DATABASE_PATH

class EquService:
    DB_PATH = DATABASE_PATH

    @classmethod
    def get_db_connection(cls):
        conn = sqlite3.connect(str(cls.DB_PATH))
        conn.row_factory = sqlite3.Row
        return conn

    @classmethod
    def get_all_assets(cls):
        """جلب كافة أصول وعدّ الورشة"""
        conn = cls.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM workshop_assets ORDER BY id DESC")
        rows = cursor.fetchall()
        conn.close()
        return [WorkshopAsset.from_row(row) for row in rows]

    @classmethod
    def add_asset(cls, asset_code, name, category, status, location, purchase_date, condition_status, notes):
        """إضافة أصل أو عدة جديدة للورشة"""
        conn = cls.get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO workshop_assets (asset_code, name, category, status, location, purchase_date, condition_status, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (asset_code, name, category, status, location, purchase_date, condition_status, notes))
            conn.commit()
            return True, "تم تسجيل الأصل أو العدّة بنجاح."
        except sqlite3.IntegrityError:
            conn.rollback()
            return False, "خطأ: كود الأصل مسجل مسبقاً، يرجى استخدام كود فريد."
        except Exception as e:
            conn.rollback()
            return False, f"حدث خطأ غير متوقع: {str(e)}"
        finally:
            conn.close()