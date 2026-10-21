from core import database as dbapi
from pathlib import Path

def dict_factory(cursor, row):
    """تحويل صفوف قاعدة البيانات إلى قواميس لسهولة الاستخدام .get()"""
    fields = [column[0] for column in cursor.description]
    return {key: value for key, value in zip(fields, row)}


class MaintenanceModel:
    @staticmethod
    def get_connection():
        conn = dbapi.connect()
        conn.row_factory = dict_factory
        return conn

    @classmethod
    def execute_query(cls, query, params=()):
        conn = cls.get_connection()
        cur = conn.cursor()
        try:
            cur.execute(query, params)
            conn.commit()
        finally:
            conn.close()

    @classmethod
    def fetch_all(cls, query, params=()):
        conn = cls.get_connection()
        cur = conn.cursor()
        try:
            cur.execute(query, params)
            result = cur.fetchall()
        finally:
            conn.close()
        return result

    @classmethod
    def fetch_one(cls, query, params=()):
        conn = cls.get_connection()
        cur = conn.cursor()
        try:
            cur.execute(query, params)
            result = cur.fetchone()
        finally:
            conn.close()
        return result


def init_maintenance_table():
    """Create maintenance_orders from the ORM model, plus the shared team_members table."""
    from core.database import engine, sync_columns
    from modules.workshop.maintenance.models.maintenance_orm import MaintenanceOrder

    MaintenanceOrder.__table__.create(bind=engine, checkfirst=True)
    sync_columns()

    MaintenanceModel.execute_query("""
    CREATE TABLE IF NOT EXISTS team_members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT,
        name TEXT,
        job_title TEXT,
        phone TEXT
    )
    """)