import sqlite3
from modules.workshop.store.models.store_model import StoreItem
from core.database import DB_PATH as DATABASE_PATH

class StoreService:
    DB_PATH = DATABASE_PATH

    @classmethod
    def get_db_connection(cls):
        """إنشاء اتصال بقاعدة البيانات مع إرجاع الصفوف كقواميس لتسهيل التعامل"""
        conn = sqlite3.connect(str(cls.DB_PATH))
        conn.row_factory = sqlite3.Row
        return conn

    @classmethod
    def get_all_items(cls):
        """جلب جميع أصناف المستودع المسجلة"""
        conn = cls.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM store_items ORDER BY id DESC")
        rows = cursor.fetchall()
        conn.close()
        return [StoreItem.from_row(row) for row in rows]

    @classmethod
    def add_item(cls, item_code, name, category, unit, quantity, min_limit, location, unit_price, notes):
        """إضافة صنف جديد إلى المستودع مع تسجيل حركة توريد أولية"""
        conn = cls.get_db_connection()
        cursor = conn.cursor()
        try:
            # 1. إدخال الصنف الجديد
            cursor.execute("""
                INSERT INTO store_items (item_code, name, category, unit, quantity, min_limit, location, unit_price, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (item_code, name, category, unit, quantity, min_limit, location, unit_price, notes))
            
            # 2. تسجيل حركة مخزنية أولية (توريد رصيد افتتاحي) إذا كانت الكمية أكبر من الصفر
            if quantity > 0:
                cursor.execute("""
                    INSERT INTO store_transactions (item_code, transaction_type, quantity, reference_number, recipient_or_supplier, transaction_date, notes)
                    VALUES (?, 'in', ?, 'INIT', 'رصيد افتتاحي', datetime('now'), 'إضافة أولية عند إنشاء الصنف')
                """, (item_code, quantity))

            conn.commit()
            return True, "تم إضافة الصنف بنجاح وتوثيق الرصيد."
        except sqlite3.IntegrityError:
            conn.rollback()
            return False, "خطأ: كود الصنف (الباركود) مسجل مسبقاً، يرجى استخدام كود فريد."
        except Exception as e:
            conn.rollback()
            return False, f"حدث خطأ غير متوقع: {str(e)}"
        finally:
            conn.close()