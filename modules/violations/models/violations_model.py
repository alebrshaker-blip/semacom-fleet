from core.database import Database

class ViolationModel:
    @staticmethod
    def create_table():
        """إنشاء جدول المخالفات والتأكد من وجود جميع الأعمدة المطلوبة بما فيها driver_name"""
        db = Database()
        query = """
        CREATE TABLE IF NOT EXISTS violations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            violation_number TEXT,
            vehicle_plate TEXT NOT NULL,
            driver_name TEXT,
            violation_type TEXT NOT NULL,
            issuer TEXT,
            location TEXT,
            violation_datetime TEXT NOT NULL,
            fine_amount REAL NOT NULL,
            status_type TEXT DEFAULT 'معلقة',
            description TEXT,
            violation_attachment TEXT,
            closure_reason TEXT,
            closure_notes TEXT,
            payment_attachment TEXT,
            closed_at TEXT
        );
        """
        db.execute(query)
        
        # التأكد من إضافة عمود driver_name في حال كان الجدول منشأ مسبقاً
        try:
            db.execute("ALTER TABLE violations ADD COLUMN driver_name TEXT;")
        except Exception:
            pass  # العمود موجود مسبقاً
            
        db.close()