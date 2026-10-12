from flask import flash, redirect, render_template, request, session, url_for

from modules.notifications.services.notifications_service import (
    CATEGORIES,
    NotificationsService,
)


def _current_user_id():
    return str(session.get("user_id") or session.get("username") or "system")


def _safe_filters():
    category = request.values.get("category", "all")
    if category not in CATEGORIES:
        category = "all"
    read_filter = request.values.get("read", "all")
    if read_filter not in {"all", "read", "unread"}:
        read_filter = "all"
    return category, read_filter


class NotificationsController:
    @staticmethod
    def index():
        category, read_filter = _safe_filters()
        notifications = NotificationsService.get_notifications(
            _current_user_id(),
            None if category == "all" else category,
            read_filter,
        )
        return render_template(
            "notifications_index.html",
            notifications=notifications,
            categories=CATEGORIES,
            selected_category=category,
            selected_read_filter=read_filter,
        )

    @staticmethod
    def update(notification_id, action):
        user_id = _current_user_id()
        if action == "read":
            NotificationsService.update_state(user_id, notification_id, is_read=1)
        elif action == "unread":
            NotificationsService.update_state(user_id, notification_id, is_read=0)
        elif action == "pin":
            NotificationsService.update_state(user_id, notification_id, is_pinned=1)
        elif action == "unpin":
            NotificationsService.update_state(user_id, notification_id, is_pinned=0)
        elif action == "delete":
            NotificationsService.update_state(user_id, notification_id, is_deleted=1)
        else:
            flash("الإجراء المطلوب غير معروف.", "danger")
            return redirect(url_for("notifications_bp.index"))
        return redirect(url_for("notifications_bp.index", **_safe_filters_as_kwargs()))

    @staticmethod
    def delete_filtered():
        category, read_filter = _safe_filters()
        count = NotificationsService.mark_filtered_deleted(
            _current_user_id(),
            None if category == "all" else category,
            read_filter,
        )
        flash(f"تم حذف {count} إشعار من النتائج المعروضة.", "success")
        return redirect(url_for("notifications_bp.index", **_safe_filters_as_kwargs()))

    @staticmethod
    def mark_all_read():
        count = NotificationsService.mark_all_read(_current_user_id())
        flash(f"تم تعليم {count} إشعار كمقروء.", "success")
        return redirect(url_for("notifications_bp.index", **_safe_filters_as_kwargs()))


def _safe_filters_as_kwargs():
    category, read_filter = _safe_filters()
    return {"category": category, "read": read_filter}
