from core.database import init_orm_schema


class NotificationsModel:

    @classmethod
    def create_table(cls):
        init_orm_schema()
