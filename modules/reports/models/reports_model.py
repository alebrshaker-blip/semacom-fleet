import sqlite3
from pathlib import Path
from core.database import DB_PATH

class ReportsModel:
    def __init__(self):
        self.db_path = DB_PATH

    def get_connection(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def get_active_templates(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM report_templates WHERE is_active = 1")
            return [dict(row) for row in cursor.fetchall()]

    def get_template_by_key(self, template_key):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM report_templates WHERE template_key = ?", (template_key,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_all_generated_reports(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM generated_reports ORDER BY created_at DESC")
            return [dict(row) for row in cursor.fetchall()]