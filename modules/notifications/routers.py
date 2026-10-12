from flask import Blueprint

from modules.notifications.controllers.notifications_controller import NotificationsController


notifications_bp = Blueprint(
    "notifications_bp",
    __name__,
    template_folder="views",
)

notifications_bp.add_url_rule("/", view_func=NotificationsController.index, methods=["GET"])
notifications_bp.add_url_rule(
    "/<notification_id>/<action>",
    view_func=NotificationsController.update,
    methods=["POST"],
)
notifications_bp.add_url_rule(
    "/delete-filtered",
    view_func=NotificationsController.delete_filtered,
    methods=["POST"],
)
notifications_bp.add_url_rule(
    "/mark-all-read",
    view_func=NotificationsController.mark_all_read,
    methods=["POST"],
)
