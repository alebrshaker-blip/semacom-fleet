import sqlite3
from core.database import DB_PATH

class OilTrackingModel:
    @staticmethod
    def get_db_connection():
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        return conn

    @classmethod
    def init_db(cls):
        """إنشاء الجدول والتأكد من إضافة الأعمدة الجديدة تلقائياً"""
        conn = cls.get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS oil_change_tracking (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle_plate TEXT NOT NULL,
                technician_name TEXT NOT NULL,
                service_date TEXT NOT NULL,
                current_mileage TEXT,
                last_oil_mileage TEXT,
                distance_interval INTEGER DEFAULT 5000,
                time_interval_months INTEGER DEFAULT 3,
                distance_alert_threshold INTEGER DEFAULT 1000,
                time_alert_threshold INTEGER DEFAULT 15,
                tracking_mode TEXT DEFAULT 'distance',
                overall_status TEXT DEFAULT 'سليم',
                notes TEXT,
                document_number TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("PRAGMA table_info(oil_change_tracking)")
        existing_columns = [col[1] for col in cursor.fetchall()]
        
        required_columns = [
            ("distance_alert_threshold", "INTEGER DEFAULT 1000"),
            ("time_alert_threshold", "INTEGER DEFAULT 15"),
            ("time_interval_months", "INTEGER DEFAULT 3"),
            ("distance_interval", "INTEGER DEFAULT 5000"),
            ("tracking_mode", "TEXT DEFAULT 'distance'")
        ]
        
        for col_name, col_type in required_columns:
            if col_name not in existing_columns:
                try:
                    cursor.execute(f"ALTER TABLE oil_change_tracking ADD COLUMN {col_name} {col_type};")
                except Exception:
                    pass

        conn.commit()
        conn.close()