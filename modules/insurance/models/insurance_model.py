from core.database import Database
from utils.expiry_status import get_expiry_status

class InsuranceModel:

    @staticmethod
    def create_table():
        db = Database()
        db.execute("""
            CREATE TABLE IF NOT EXISTS insurance_policies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                policy_number TEXT NOT NULL,
                vehicle_plate TEXT NOT NULL,
                insurance_company TEXT NOT NULL,
                insurance_type TEXT DEFAULT 'شامل',
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                policy_cost REAL DEFAULT 0.0,
                description TEXT,
                policy_attachment TEXT,
                status TEXT DEFAULT 'active',
                status_type TEXT DEFAULT 'ساري',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (vehicle_plate) REFERENCES vehicles(plate_number)
            )
        """)
        columns = {
            row["name"] for row in db.fetch_all("PRAGMA table_info(insurance_policies)")
        }
        for name, column_type in (
            ("status", "TEXT DEFAULT 'active'"),
            ("status_type", "TEXT DEFAULT 'ساري'"),
        ):
            if name not in columns:
                db.execute(f'ALTER TABLE insurance_policies ADD COLUMN "{name}" {column_type}')
        db.close()

    @staticmethod
    def get_all(tab='active'):
        db = Database()
        policies = db.fetch_all("SELECT * FROM insurance_policies ORDER BY id DESC")
        for policy in policies:
            state = get_expiry_status(
                policy.get("end_date"), "ساري", "قارب على الانتهاء", "منتهية"
            )
            policy_status = "expired" if state == "منتهية" else policy.get("status", "active")
            db.execute(
                "UPDATE insurance_policies SET status = ?, status_type = ? WHERE id = ?",
                (policy_status, state, policy.get("id")),
            )
        if tab == 'active':
            query = "SELECT * FROM insurance_policies WHERE status = 'active' ORDER BY id DESC"
        else:
            query = "SELECT * FROM insurance_policies WHERE status = 'expired' ORDER BY id DESC"
        policies = db.fetch_all(query)
        db.close()
        return policies

    @staticmethod
    def add_policy(data, attachment_filename):
        db = Database()
        db.execute("""
            INSERT INTO insurance_policies (
                policy_number, vehicle_plate, insurance_company, insurance_type,
                start_date, end_date, policy_cost, description, policy_attachment, status, status_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 'ساري')
        """, (
            data.get('policy_number'),
            data.get('vehicle_plate'),
            data.get('insurance_company'),
            data.get('insurance_type'),
            data.get('start_date'),
            data.get('end_date'),
            float(data.get('policy_cost') or 0.0),
            data.get('description'),
            attachment_filename
        ))
        db.close()

    @staticmethod
    def expire_policy(policy_id):
        db = Database()
        db.execute("""
            UPDATE insurance_policies 
            SET status = 'expired', status_type = 'منتهي' 
            WHERE id = ?
        """, (policy_id,))
        db.close()

    @staticmethod
    def delete_policy(policy_id):
        db = Database()
        db.execute("DELETE FROM insurance_policies WHERE id = ?", (policy_id,))
        db.close()