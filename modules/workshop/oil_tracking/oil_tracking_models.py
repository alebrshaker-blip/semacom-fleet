from core import database as dbapi


class OilTrackingModel:
    @staticmethod
    def get_db_connection():
        conn = dbapi.connect()
        conn.row_factory = dbapi.Row
        return conn

    @classmethod
    def init_db(cls):
        """Create the oil_change_tracking table and any missing columns from the ORM model."""
        dbapi.init_orm_schema()
