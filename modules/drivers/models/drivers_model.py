import os
import sqlite3
from core.database import DB_PATH as DATABASE_PATH

DB_PATH = str(DATABASE_PATH)

def get_db_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_driver_db():
    conn = get_db_connection()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS drivers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            national_id TEXT,
            phone TEXT,
            nationality TEXT,
            job_title TEXT,
            department TEXT,
            license_number TEXT,
            license_type TEXT,
            restrictions_count INTEGER DEFAULT 0,
            license_issue_date TEXT,
            license_expiry_date TEXT
        )
    ''')
    columns = {row['name'] for row in conn.execute("PRAGMA table_info(drivers)")}
    if 'license_type' not in columns:
        conn.execute("ALTER TABLE drivers ADD COLUMN license_type TEXT")
    conn.commit()
    conn.close()

def get_all_drivers(search_query=""):
    init_driver_db()
    conn = get_db_connection()
    if search_query:
        query = "%" + search_query + "%"
        drivers = conn.execute('''
            SELECT * FROM drivers 
            WHERE name LIKE ? OR national_id LIKE ? OR phone LIKE ? OR license_number LIKE ?
        ''', (query, query, query, query)).fetchall()
    else:
        drivers = conn.execute('SELECT * FROM drivers').fetchall()
    conn.close()
    return drivers

def add_driver(form_data):
    init_driver_db()
    conn = get_db_connection()
    try:
        conn.execute('''
            INSERT INTO drivers (
                name, national_id, phone, nationality, job_title, 
                department, license_number, license_type, restrictions_count, 
                license_issue_date, license_expiry_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            form_data.get('name'),
            form_data.get('national_id'),
            form_data.get('phone'),
            form_data.get('nationality'),
            form_data.get('job_title'),
            form_data.get('department'),
            form_data.get('license_number'),
            form_data.get('license_type'),
            form_data.get('restrictions_count', 0) or 0,
            form_data.get('license_issue_date'),
            form_data.get('license_expiry_date')
        ))
        conn.commit()
        return True, "تمت إضافة الموظف بنجاح"
    except sqlite3.IntegrityError:
        return False, "خطأ: اسم الموظف موجود مسبقاً ولا يمكن تكراره!"
    except Exception as e:
        return False, f"خطأ: {str(e)}"
    finally:
        conn.close()

def delete_driver(driver_id):
    conn = get_db_connection()
    conn.execute('DELETE FROM drivers WHERE id = ?', (driver_id,))
    conn.commit()
    conn.close()