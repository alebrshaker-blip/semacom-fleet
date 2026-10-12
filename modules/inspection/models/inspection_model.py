import sqlite3
from core.database import DB_PATH as DATABASE_PATH

class InspectionModel:
    DB_PATH = DATABASE_PATH

    @staticmethod
    def get_connection():
        conn = sqlite3.connect(str(InspectionModel.DB_PATH))
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def create_table():
        conn = InspectionModel.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS inspections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle_plate TEXT NOT NULL,
                inspection_center TEXT NOT NULL,
                inspection_date TEXT NOT NULL,
                expiry_date TEXT NOT NULL,
                result_status TEXT DEFAULT 'ناجح',
                inspection_cost REAL DEFAULT 0.0,
                attachment TEXT,
                notes TEXT,
                status TEXT DEFAULT 'active',
                status_type TEXT DEFAULT 'ساري',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (vehicle_plate) REFERENCES vehicles(plate_number)
            )
        ''')
        columns = {row['name'] for row in cursor.execute("PRAGMA table_info(inspections)")}
        for name, column_type in (
            ('inspection_center', 'TEXT'),
            ('inspection_date', 'TEXT'),
            ('expiry_date', 'TEXT'),
            ('result_status', "TEXT DEFAULT 'ناجح'"),
            ('inspection_cost', 'REAL DEFAULT 0.0'),
            ('attachment', 'TEXT'),
            ('notes', 'TEXT'),
            ('status', "TEXT DEFAULT 'active'"),
            ('status_type', "TEXT DEFAULT 'ساري'"),
        ):
            if name not in columns:
                cursor.execute(f'ALTER TABLE inspections ADD COLUMN "{name}" {column_type}')

        tables = {
            row['name'] for row in cursor.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if 'vehicle_inspections' in tables and cursor.execute(
            "SELECT COUNT(*) FROM inspections"
        ).fetchone()[0] == 0:
            source_columns = {
                row['name'] for row in cursor.execute("PRAGMA table_info(vehicle_inspections)")
            }
            target_columns = [
                'id', 'vehicle_plate', 'inspection_center', 'inspection_date', 'expiry_date',
                'result_status', 'inspection_cost', 'attachment', 'notes', 'status', 'status_type',
            ]
            available_columns = [name for name in target_columns if name in source_columns]
            if 'vehicle_plate' in available_columns:
                column_sql = ', '.join(f'"{name}"' for name in available_columns)
                cursor.execute(
                    f'INSERT OR IGNORE INTO inspections ({column_sql}) '
                    f'SELECT {column_sql} FROM vehicle_inspections'
                )
        conn.commit()
        conn.close()

    @staticmethod
    def get_all(status_type='active'):
        conn = InspectionModel.get_connection()
        cursor = conn.cursor()
        if status_type == 'active':
            cursor.execute("SELECT * FROM inspections WHERE status = 'active' ORDER BY expiry_date ASC")
        else:
            cursor.execute("SELECT * FROM inspections WHERE status = 'expired' ORDER BY expiry_date DESC")
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    @staticmethod
    def add_inspection(form_data, attachment_filename):
        conn = InspectionModel.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO inspections 
            (vehicle_plate, inspection_center, inspection_date, expiry_date, result_status, inspection_cost, attachment, notes, status, status_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', 'ساري')
        ''', (
            form_data.get('vehicle_plate') or form_data.get('plate_number'),
            form_data.get('inspection_center') or form_data.get('inspector_name', '-'),
            form_data.get('inspection_date'),
            form_data.get('expiry_date'),
            form_data.get('result_status') or form_data.get('result', 'ناجح'),
            float(form_data.get('inspection_cost') or 0.0),
            attachment_filename,
            form_data.get('notes')
        ))
        conn.commit()
        conn.close()

    @staticmethod
    def expire_inspection(inspection_id):
        conn = InspectionModel.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE inspections SET status = 'expired', status_type = 'منتهي' WHERE id = ?", (inspection_id,))
        conn.commit()
        conn.close()

    @staticmethod
    def delete_inspection(inspection_id):
        conn = InspectionModel.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM inspections WHERE id = ?", (inspection_id,))
        conn.commit()
        conn.close()