import os
import sqlite3
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
configured_db_path = Path(os.environ.get("DATABASE_PATH", "database/semacom.db")).expanduser()
DB_PATH = (
    configured_db_path if configured_db_path.is_absolute() else BASE_DIR / configured_db_path
).resolve()
SCHEMA_PATH = BASE_DIR / "database" / "schema.sql"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# 🌟 1. إضافة دالة تحويل صفوف قاعدة البيانات إلى قواميس حقيقية تدعم .get()
def dict_factory(cursor, row):
    fields = [column[0] for column in cursor.description]
    return {key: value for key, value in zip(fields, row)}

class Database:
    def __init__(self):
        self.connection = sqlite3.connect(DB_PATH)
        # 🌟 2. استخدام الدالة المخصصة بدلاً من sqlite3.Row
        self.connection.row_factory = dict_factory
        self.cursor = self.connection.cursor()
        self.initialize_database()

    def initialize_database(self):
        with open(SCHEMA_PATH, "r", encoding="utf-8") as schema_file:
            schema_sql = schema_file.read()
            self.cursor.executescript(schema_sql)
            self.connection.commit()

    def fetch_all(self, query, params=()):
        self.cursor.execute(query, params)
        return self.cursor.fetchall()

    def execute(self, query, params=()):
        self.cursor.execute(query, params)
        self.connection.commit()

    def close(self):
        self.connection.close()