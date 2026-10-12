import sqlite3
from pathlib import Path
from core.database import DB_PATH

def get_db_connection():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn, DB_PATH

def init_handover_db():
    conn, _ = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS handover_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vehicle_info TEXT,
            driver_info TEXT,
            handover_type TEXT,
            odometer TEXT,
            fuel_level TEXT,
            body_condition TEXT,
            interior_condition TEXT,
            tires_condition TEXT,
            mechanical_condition TEXT,
            electrical_condition TEXT,
            electrical_technician TEXT,
            mechanical_technician TEXT,
            handover_date TEXT,
            notes TEXT
        )
    """)
    conn.commit()
    conn.close()

def get_all_records(search_query=None):
    conn, _ = get_db_connection()
    cur = conn.cursor()
    if search_query:
        like_pattern = f"%{search_query}%"
        cur.execute("""
            SELECT * FROM handover_records 
            WHERE vehicle_info LIKE ? OR driver_info LIKE ? OR electrical_technician LIKE ? OR mechanical_technician LIKE ?
        """, (like_pattern, like_pattern, like_pattern, like_pattern))
    else:
        cur.execute("SELECT * FROM handover_records ORDER BY id DESC")
    records = cur.fetchall()
    conn.close()
    return records

def insert_handover_record(data):
    conn, _ = get_db_connection()
    cur = conn.cursor()
    keys = list(data.keys())
    values = list(data.values())
    columns_str = ", ".join([f'"{k}"' for k in keys])
    placeholders_str = ", ".join(["?" for _ in keys])

    query = f"INSERT INTO handover_records ({columns_str}) VALUES ({placeholders_str})"
    cur.execute(query, values)
    conn.commit()
    conn.close()

def delete_handover_record(record_id):
    conn, _ = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM handover_records WHERE id = ?", (record_id,))
    conn.commit()
    conn.close()