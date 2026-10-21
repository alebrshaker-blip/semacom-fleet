from datetime import date

from sqlalchemy import case, delete, func, select, update
from sqlalchemy.exc import IntegrityError

from core.database import get_session, now_text
from modules.tasks.models.tasks_model import TasksModel
from modules.tasks.models.tasks_orm import TaskRecord


PRIORITIES = ("عاجلة", "عالية", "متوسطة", "منخفضة")
STATUSES = ("مجدولة", "قيد التنفيذ", "مكتملة")


def _validate_due_date(due_date):
    if due_date:
        try:
            date.fromisoformat(due_date)
        except ValueError as error:
            raise ValueError("تاريخ الاستحقاق غير صحيح.") from error


class TasksService:
    @staticmethod
    def initialize():
        TasksModel.create_table()

    @staticmethod
    def get_all_tasks(user_id, archived=False, status="all", priority="all"):
        conditions = [
            TaskRecord.user_id == str(user_id),
            TaskRecord.is_archived == int(archived),
        ]
        if status in STATUSES:
            conditions.append(TaskRecord.status == status)
        if priority in PRIORITIES:
            conditions.append(TaskRecord.priority == priority)

        priority_rank = case(
            (TaskRecord.priority == "عاجلة", 0),
            (TaskRecord.priority == "عالية", 1),
            (TaskRecord.priority == "متوسطة", 2),
            else_=3,
        )
        no_due_date = case(
            (TaskRecord.due_date.is_(None), 1),
            (TaskRecord.due_date == "", 1),
            else_=0,
        )
        with get_session() as session:
            rows = session.scalars(
                select(TaskRecord).where(*conditions).order_by(
                    priority_rank, no_due_date, TaskRecord.due_date.asc(),
                    TaskRecord.created_at.desc(),
                )
            ).all()
            return [row.to_dict() for row in rows]

    @staticmethod
    def get_task(user_id, task_id):
        with get_session() as session:
            row = session.scalar(
                select(TaskRecord).where(
                    TaskRecord.id == int(task_id), TaskRecord.user_id == str(user_id)
                )
            )
            return row.to_dict() if row else None

    @staticmethod
    def get_task_by_source(user_id, source_notification_id):
        with get_session() as session:
            row = session.scalar(
                select(TaskRecord).where(
                    TaskRecord.user_id == str(user_id),
                    TaskRecord.source_notification_id == source_notification_id,
                )
            )
            return row.to_dict() if row else None

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
        _validate_due_date(due_date)

        try:
            with get_session() as session:
                task = TaskRecord(
                    user_id=str(user_id), title=title, description=description,
                    due_date=due_date, priority=priority, status="مجدولة",
                    source_notification_id=source_notification_id,
                )
                session.add(task)
                session.flush()
                return task.id
        except IntegrityError as error:
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
        _validate_due_date(due_date)

        completed_at = task["completed_at"]
        if status == "مكتملة" and task["status"] != "مكتملة":
            completed_at = date.today().isoformat()
        elif status != "مكتملة":
            completed_at = None
        with get_session() as session:
            session.execute(
                update(TaskRecord)
                .where(TaskRecord.id == int(task_id), TaskRecord.user_id == str(user_id))
                .values(
                    title=title, description=description, due_date=due_date,
                    priority=priority, status=status, completed_at=completed_at,
                    updated_at=now_text(),
                )
            )

    @staticmethod
    def set_archived(user_id, task_id, archived):
        with get_session() as session:
            result = session.execute(
                update(TaskRecord)
                .where(TaskRecord.id == int(task_id), TaskRecord.user_id == str(user_id))
                .values(is_archived=int(archived), updated_at=now_text())
            )
            if result.rowcount == 0:
                raise ValueError("المهمة غير موجودة.")

    @staticmethod
    def delete_task(user_id, task_id):
        with get_session() as session:
            result = session.execute(
                delete(TaskRecord).where(
                    TaskRecord.id == int(task_id), TaskRecord.user_id == str(user_id)
                )
            )
            if result.rowcount == 0:
                raise ValueError("المهمة غير موجودة.")

    @staticmethod
    def count_tasks(user_id, archived=False):
        with get_session() as session:
            rows = session.execute(
                select(TaskRecord.status, func.count())
                .where(TaskRecord.user_id == str(user_id),
                       TaskRecord.is_archived == int(archived))
                .group_by(TaskRecord.status)
            ).all()
            return {status: count for status, count in rows}
