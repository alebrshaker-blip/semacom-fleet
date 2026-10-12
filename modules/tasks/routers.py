from flask import Blueprint

from modules.tasks.controllers.tasks_controller import TasksController


tasks_bp = Blueprint(
    "tasks_bp",
    __name__,
    template_folder="views",
)

tasks_bp.add_url_rule("/", view_func=TasksController.index, methods=["GET"])
tasks_bp.add_url_rule("/add", view_func=TasksController.add, methods=["POST"])
tasks_bp.add_url_rule(
    "/from-notification/<path:notification_id>",
    view_func=TasksController.from_notification,
    methods=["GET"],
)
tasks_bp.add_url_rule(
    "/<int:task_id>/update",
    view_func=TasksController.update,
    methods=["POST"],
)
tasks_bp.add_url_rule(
    "/<int:task_id>/archive",
    view_func=TasksController.archive_task,
    endpoint="archive",
    methods=["POST"],
)
tasks_bp.add_url_rule(
    "/<int:task_id>/restore",
    view_func=TasksController.restore_task,
    endpoint="restore",
    methods=["POST"],
)
tasks_bp.add_url_rule(
    "/<int:task_id>/delete",
    view_func=TasksController.delete,
    methods=["POST"],
)
