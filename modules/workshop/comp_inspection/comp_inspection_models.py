import sqlite3
from core.database import DB_PATH

class CompInspectionModel:
    @staticmethod
    def get_db_connection():
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        return conn

    @classmethod
    def init_db(cls):
        """إنشاء الجداول الخاصة بالفحص الشامل في قاعدة بيانات النظام الموحدة"""
        conn = cls.get_db_connection()
        cursor = conn.cursor()
        
        # جدول الفحص الشامل الرئيسي
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS comprehensive_inspections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle_plate TEXT NOT NULL,
                inspector_name TEXT NOT NULL,
                inspection_date TEXT NOT NULL,
                current_mileage TEXT,
                oil_change_mileage TEXT,
                overall_status TEXT,
                notes TEXT,
                document_number TEXT DEFAULT 'No.000000',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # جدول بنود الفحص التفصيلية
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS comprehensive_inspection_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                inspection_id INTEGER,
                category TEXT,      
                item_name TEXT,     
                status TEXT,        
                item_notes TEXT,
                FOREIGN KEY (inspection_id) REFERENCES comprehensive_inspections(id) ON DELETE CASCADE
            )
        """)
        conn.commit()
        conn.close()