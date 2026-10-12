import sqlite3
from contextlib import closing
from core.database import DB_PATH as DATABASE_PATH


class NotificationsModel:
    DB_PATH = DATABASE_PATH

    @classmethod
    def get_connection(cls):
        connection = sqlite3.connect(str(cls.DB_PATH))
        connection.row_factory = sqlite3.Row
        return connection

    @classmethod
    def create_table(cls):
        with closing(cls.get_connection()) as connection:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type = 'table' AND name = 'notification_user_state'"
            ).fetchone()
            if exists:
                return
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS notification_user_state (
                    user_id TEXT NOT NULL,
                    notification_id TEXT NOT NULL,
                    is_read INTEGER NOT NULL DEFAULT 0,
                    is_pinned INTEGER NOT NULL DEFAULT 0,
                    is_deleted INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, notification_id)
                )
                """
            )
            connection.commit()
