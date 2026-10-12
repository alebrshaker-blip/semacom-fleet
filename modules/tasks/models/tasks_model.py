import sqlite3
from contextlib import closing
from core.database import DB_PATH as DATABASE_PATH


class TasksModel:
    DB_PATH = DATABASE_PATH

    @classmethod
    def get_connection(cls):
        connection = sqlite3.connect(str(cls.DB_PATH))
        connection.row_factory = sqlite3.Row
        return connection

    @classmethod
    def create_table(cls):
        with closing(cls.get_connection()) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS task_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    due_date TEXT,
                    priority TEXT NOT NULL DEFAULT 'متوسطة',
                    status TEXT NOT NULL DEFAULT 'مجدولة',
                    is_archived INTEGER NOT NULL DEFAULT 0,
                    source_notification_id TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    completed_at TEXT,
                    UNIQUE (user_id, source_notification_id)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_task_records_user_status "
                "ON task_records (user_id, is_archived, status, due_date)"
            )
            connection.commit()
