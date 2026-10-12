import sqlite3
from contextlib import closing
from datetime import date

from modules.tasks.models.tasks_model import TasksModel


PRIORITIES = ("عاجلة", "عالية", "متوسطة", "منخفضة")
STATUSES = ("مجدولة", "قيد التنفيذ", "مكتملة")


class TasksService:
    @staticmethod
    def initialize():
        TasksModel.create_table()

    @staticmethod
    def get_all_tasks(user_id, archived=False, status="all", priority="all"):
        TasksModel.create_table()
        conditions = ["user_id = ?", "is_archived = ?"]
        params = [str(user_id), int(archived)]
        if status in STATUSES:
            conditions.append("status = ?")
            params.append(status)
        if priority in PRIORITIES:
            conditions.append("priority = ?")
            params.append(priority)

        with closing(TasksModel.get_connection()) as connection:
            rows = connection.execute(
                f"""SELECT * FROM task_records
                    WHERE {' AND '.join(conditions)}
                    ORDER BY
                        CASE priority
                            WHEN 'عاجلة' THEN 0
                            WHEN 'عالية' THEN 1
                            WHEN 'متوسطة' THEN 2
                            ELSE 3
                        END,
                        CASE WHEN due_date IS NULL OR due_date = '' THEN 1 ELSE 0 END,
                        due_date ASC,
                        created_at DESC""",
                params,
            ).fetchall()
            return [dict(row) for row in rows]

    @staticmethod
    def get_task(user_id, task_id):
        TasksModel.create_table()
        with closing(TasksModel.get_connection()) as connection:
            row = connection.execute(
                "SELECT * FROM task_records WHERE id = ? AND user_id = ?",
                (task_id, str(user_id)),
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def get_task_by_source(user_id, source_notification_id):
        TasksModel.create_table()
        with closing(TasksModel.get_connection()) as connection:
            row = connection.execute(
                """SELECT * FROM task_records
                   WHERE user_id = ? AND source_notification_id = ?""",
                (str(user_id), source_notification_id),
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def create_task(user_id, data, source_notification_id=None):
        title = (data.get("title") or "").strip()
        description = (data.get("description") or "").strip()
        due_date = (data.get("due_date") or "").strip() or None
        priority = data.get("priority", "متوسطة")
        if not title:
            raise ValueError("عنوان المهمة مطلوب.")
        if priority not in PRIORITIES:
            raise ValueError("درجة الأولوية غير صحيحة.")
        if due_date:
            try:
                date.fromisoformat(due_date)
            except ValueError as error:
                raise ValueError("تاريخ الاستحقاق غير صحيح.") from error

        TasksModel.create_table()
        try:
            with closing(TasksModel.get_connection()) as connection:
                cursor = connection.execute(
                    """INSERT INTO task_records
                       (user_id, title, description, due_date, priority, status,
                        source_notification_id)
                       VALUES (?, ?, ?, ?, ?, 'مجدولة', ?)""",
                    (
                        str(user_id), title, description, due_date, priority,
                        source_notification_id,
                    ),
                )
                connection.commit()
                return cursor.lastrowid
        except sqlite3.IntegrityError as error:
            if source_notification_id:
                raise ValueError("سبق إنشاء مهمة من هذا الإشعار.") from error
            raise

    @staticmethod
    def update_task(user_id, task_id, data):
        task = TasksService.get_task(user_id, task_id)
        if not task:
            raise ValueError("المهمة غير موجودة.")
        title = (data.get("title") or "").strip()
        description = (data.get("description") or "").strip()
        due_date = (data.get("due_date") or "").strip() or None
        priority = data.get("priority", task["priority"])
        status = data.get("status", task["status"])
        if not title:
            raise ValueError("عنوان المهمة مطلوب.")
        if priority not in PRIORITIES or status not in STATUSES:
            raise ValueError("قيمة الأولوية أو الحالة غير صحيحة.")
        if due_date:
            try:
                date.fromisoformat(due_date)
            except ValueError as error:
                raise ValueError("تاريخ الاستحقاق غير صحيح.") from error

        completed_at = task["completed_at"]
        if status == "مكتملة" and task["status"] != "مكتملة":
            completed_at = date.today().isoformat()
        elif status != "مكتملة":
            completed_at = None
        with closing(TasksModel.get_connection()) as connection:
            connection.execute(
                """UPDATE task_records
                   SET title = ?, description = ?, due_date = ?, priority = ?,
                       status = ?, completed_at = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND user_id = ?""",
                (
                    title, description, due_date, priority, status, completed_at,
                    task_id, str(user_id),
                ),
            )
            connection.commit()

    @staticmethod
    def set_archived(user_id, task_id, archived):
        TasksModel.create_table()
        with closing(TasksModel.get_connection()) as connection:
            cursor = connection.execute(
                """UPDATE task_records SET is_archived = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND user_id = ?""",
                (int(archived), task_id, str(user_id)),
            )
            connection.commit()
            if cursor.rowcount == 0:
                raise ValueError("المهمة غير موجودة.")

    @staticmethod
    def delete_task(user_id, task_id):
        TasksModel.create_table()
        with closing(TasksModel.get_connection()) as connection:
            cursor = connection.execute(
                "DELETE FROM task_records WHERE id = ? AND user_id = ?",
                (task_id, str(user_id)),
            )
            connection.commit()
            if cursor.rowcount == 0:
                raise ValueError("المهمة غير موجودة.")

    @staticmethod
    def count_tasks(user_id, archived=False):
        TasksModel.create_table()
        with closing(TasksModel.get_connection()) as connection:
            rows = connection.execute(
                """SELECT status, COUNT(*) AS count FROM task_records
                   WHERE user_id = ? AND is_archived = ? GROUP BY status""",
                (str(user_id), int(archived)),
            ).fetchall()
            return {row["status"]: row["count"] for row in rows}
