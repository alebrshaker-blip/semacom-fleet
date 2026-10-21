from modules.violations.services.violations_service import init_violations_db


class ViolationModel:
    @staticmethod
    def create_table():
        """Kept for backwards compatibility; the schema now comes from the ORM model."""
        init_violations_db()
