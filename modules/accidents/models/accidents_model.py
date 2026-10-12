from core.database import Database

def init_accidents_db():
    """تهيئة جدول الحوادث والتأكد من وجوده وهيكليته سليمة"""
    db = Database()
    query = """
    CREATE TABLE IF NOT EXISTS accidents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        accident_number TEXT,
        vehicle_plate TEXT,
        driver_name TEXT,
        accident_type TEXT,
        issuer TEXT,
        location TEXT,
        accident_datetime TEXT,
        repair_cost REAL,
        description TEXT,
        accident_attachment TEXT,
        accident_attachment_2 TEXT,
        status TEXT DEFAULT 'active',
        status_type TEXT DEFAULT 'جاري المتابعة',
        closure_reason TEXT,
        closure_notes TEXT,
        closed_at TEXT,
        payment_attachment TEXT
    );
    """
    db.execute(query)
    columns = {row["name"] for row in db.fetch_all("PRAGMA table_info(accidents)")}
    if "accident_attachment_2" not in columns:
        db.execute("ALTER TABLE accidents ADD COLUMN accident_attachment_2 TEXT")
    db.close()