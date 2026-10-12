from datetime import date

from flask import flash, redirect, render_template, request, session, url_for

from modules.notifications.services.notifications_service import NotificationsService
from modules.tasks.services.tasks_service import (
    PRIORITIES,
    STATUSES,
    TasksService,
)


def _current_user_id():
    return str(session.get("user_id") or session.get("username") or "system")


def _task_filters():
    archived = request.values.get("archived") == "1"
    status = request.values.get("status", "all")
    priority = request.values.get("priority", "all")
    if status not in STATUSES:
        status = "all"
    if priority not in PRIORITIES:
        priority = "all"
    return archived, status, priority


def _redirect_to_list():
    archived = request.values.get("archived") == "1"
    status = request.values.get("status_filter", request.values.get("status", "all"))
    priority = request.values.get("priority_filter", request.values.get("priority", "all"))
    if status not in STATUSES:
        status = "all"
    if priority not in PRIORITIES:
        priority = "all"
    return redirect(url_for(
        "tasks_bp.index",
        archived=int(archived),
        status=status,
        priority=priority,
    ))


class TasksController:
    @staticmethod
    def index():
        archived, status, priority = _task_filters()
        user_id = _current_user_id()
        tasks = TasksService.get_all_tasks(user_id, archived, status, priority)
        active_counts = TasksService.count_tasks(user_id, False)
        archived_counts = TasksService.count_tasks(user_id, True)
        return render_template(
            "tasks_index.html",
            tasks=tasks,
            active_counts=active_counts,
            archived_counts=archived_counts,
            priorities=PRIORITIES,
            statuses=STATUSES,
            selected_archived=archived,
            selected_status=status,
            selected_priority=priority,
            today=date.today().isoformat(),
            new_task=request.args.get("new_task", default=None, type=str),
            source_notification_id=None,
            duplicate_source=False,
        )

    @staticmethod
    def from_notification(notification_id):
        user_id = _current_user_id()
        notification = next(
            (
                item for item in NotificationsService.get_notifications(user_id)
                if item["id"] == notification_id
            ),
            None,
        )
        if not notification:
            flash("الإشعار غير متاح أو سبق حذفه.", "warning")
            return redirect(url_for("notifications_bp.index"))
        existing = TasksService.get_task_by_source(user_id, notification_id)
        if existing:
            flash("سبق تحويل هذا الإشعار إلى مهمة.", "info")
            return redirect(url_for("tasks_bp.index"))
        default_task = {
            "title": notification["title"],
            "description": notification["message"],
            "due_date": "",
            "priority": "عاجلة" if notification["severity"] == "danger" else "عالية",
        }
        return render_template(
            "tasks_index.html",
            tasks=TasksService.get_all_tasks(user_id),
            active_counts=TasksService.count_tasks(user_id, False),
            archived_counts=TasksService.count_tasks(user_id, True),
            priorities=PRIORITIES,
            statuses=STATUSES,
            selected_archived=False,
            selected_status="all",
            selected_priority="all",
            today=date.today().isoformat(),
            new_task=default_task,
            source_notification_id=notification_id,
            duplicate_source=False,
        )

    @staticmethod
    def add():
        task_id = None
        try:
            source_notification_id = request.form.get("source_notification_id") or None
            if source_notification_id and not any(
                notification["id"] == source_notification_id
                for notification in NotificationsService.get_notifications(_current_user_id())
            ):
                raise ValueError("الإشعار غير متاح لتحويله إلى مهمة.")
            task_id = TasksService.create_task(
                _current_user_id(), request.form, source_notification_id
            )
            if source_notification_id:
                NotificationsService.update_state(
                    _current_user_id(), source_notification_id, is_read=1
                )
            flash("تمت إضافة المهمة إلى السجل.", "success")
        except ValueError as error:
            flash(str(error), "warning")
        if task_id and request.form.get("source_notification_id"):
            return redirect(url_for("tasks_bp.index", task=task_id))
        return _redirect_to_list()

    @staticmethod
    def update(task_id):
        try:
            TasksService.update_task(_current_user_id(), task_id, request.form)
            flash("تم تحديث المهمة.", "success")
        except ValueError as error:
            flash(str(error), "warning")
        return _redirect_to_list()

    @staticmethod
    def archive(task_id, archived):
        try:
            TasksService.set_archived(_current_user_id(), task_id, archived)
            flash("تم أرشفة المهمة." if archived else "تمت استعادة المهمة من الأرشيف.", "success")
        except ValueError as error:
            flash(str(error), "warning")
        if not archived:
            return redirect(url_for("tasks_bp.index"))
        return _redirect_to_list()

    @staticmethod
    def archive_task(task_id):
        return TasksController.archive(task_id, True)

    @staticmethod
    def restore_task(task_id):
        return TasksController.archive(task_id, False)

    @staticmethod
    def delete(task_id):
        try:
            TasksService.delete_task(_current_user_id(), task_id)
            flash("تم حذف المهمة.", "success")
        except ValueError as error:
            flash(str(error), "warning")
        return _redirect_to_list()
