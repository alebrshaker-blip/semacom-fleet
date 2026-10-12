from datetime import datetime
import sqlite3
from core.database import DB_PATH

def generate_work_order_no(maintenance_type):
    prefixes = {
        'internal': 'INT',
        'external': 'EXT',
        'emergency': 'EMR',
        'exceptional': 'EXC'
    }
    prefix = prefixes.get(maintenance_type, 'GEN')
    
    now = datetime.now()
    day_str = now.strftime('%d')
    month_str = now.strftime('%m')
    year_str = now.strftime('%y')  # أول رقمين من السنة (مثلاً 26)
    
    conn = sqlite3.connect(str(DB_PATH))
    try:
        cur = conn.cursor()
        
        # نمط البحث لحساب التسلسل اليومي لنفس النوع
        date_pattern = f"%{day_str}{month_str}{year_str}"
        cur.execute("SELECT COUNT(*) FROM maintenance_orders WHERE order_no LIKE ? AND type = ?", (f"{prefix}%{date_pattern}", maintenance_type))
        count = cur.fetchone()[0]
        seq = str(count + 1).zfill(2) # رقمين تسلسليين (01, 02, ...)
        return f"{prefix}{seq}{day_str}{month_str}{year_str}"
    finally:
        conn.close()