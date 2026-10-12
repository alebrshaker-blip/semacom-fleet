import logging
import re
import calendar
from contextlib import closing
from datetime import date, datetime, timedelta

from modules.notifications.models.notifications_model import NotificationsModel


logger = logging.getLogger(__name__)

CATEGORIES = {
    "vehicle_reports": "بلاغات المركبات",
    "driver_licenses": "رخص السائقين",
    "maintenance": "أوامر الصيانة",
    "comprehensive_inspection": "الفحص الشامل",
    "store": "المستودع",
    "team_licenses": "رخص فريق العمل",
    "workshop_assets": "أصول الورشة",
    "oil": "تغيير الزيوت",
    "violations": "المخالفات المرورية",
    "inspections": "الفحص الدوري",
    "insurance": "التأمينات",
    "accidents": "الحوادث",
}


def _parse_date(value):
    if not value:
        return None
    text = str(value).strip()
    for parser in (
        lambda item: datetime.fromisoformat(item.replace("Z", "+00:00")).date(),
        lambda item: datetime.strptime(item[:10], "%d/%m/%Y").date(),
        lambda item: datetime.strptime(item[:10], "%d-%m-%Y").date(),
    ):
        try:
            return parser(text)
        except (ValueError, TypeError):
            continue
    return None


def _expiry_alert(record_id, category, label, expiry_value, title, target):
    expiry = _parse_date(expiry_value)
    if expiry is None:
        return None
    remaining = (expiry - date.today()).days
    if remaining > 30:
        return None
    if remaining < 0:
        summary = f"{label} منتهية منذ {abs(remaining)} يوم"
        severity = "danger"
    elif remaining == 0:
        summary = f"{label} تنتهي اليوم"
        severity = "danger"
    else:
        summary = f"{label} تنتهي خلال {remaining} يوم"
        severity = "warning"
    return _notification(
        f"{category}:{record_id}", category, title, summary, target,
        severity, expiry.isoformat()
    )


def _notification(identifier, category, title, message, url, severity="warning", created_at=None):
    return {
        "id": identifier,
        "category": category,
        "category_label": CATEGORIES[category],
        "title": title,
        "message": str(message or ""),
        "url": url,
        "severity": severity,
        "created_at": created_at or "",
    }


def _table_columns(connection, table):
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    if not exists:
        return set()
    return {row["name"] for row in connection.execute(f'PRAGMA table_info("{table}")')}


def _rows(connection, table, required, query, parameters=()):
    columns = _table_columns(connection, table)
    if not set(required).issubset(columns):
        return []
    return [dict(row) for row in connection.execute(query, parameters).fetchall()]


def _duration_deadline(start_value, expected_value):
    start = _parse_date(start_value)
    expected = (expected_value or "").strip()
    if not start or not expected:
        return None
    absolute_date = _parse_date(expected)
    if absolute_date:
        return absolute_date

    normalized = expected.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    match = re.search(r"(\d+)\s*([^\d\s]+)", normalized)
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2).lower()
    if any(word in unit for word in ("ساعة", "ساع", "hour", "hr")):
        days = max(1, (amount + 23) // 24)
    elif any(word in unit for word in ("أسبوع", "اسبوع", "week")):
        days = amount * 7
    elif any(word in unit for word in ("شهر", "month")):
        days = amount * 30
    else:
        days = amount
    return start + timedelta(days=days)


class NotificationsService:
    @staticmethod
    def _get_source_notifications(connection):
        notifications = []

        # Fresh vehicle QR reports submitted for equipment-management review.
        for row in _rows(
            connection, "vehicle_public_submissions",
            ("id", "submission_type", "message", "status", "submitted_at"),
            """SELECT s.id, s.submission_type, s.message, s.status, s.submitted_at,
                      v.vehicle_code, v.plate_number
               FROM vehicle_public_submissions s
               LEFT JOIN vehicles v ON v.id = s.vehicle_id
               WHERE s.status = 'جديد' ORDER BY s.id DESC""",
        ):
            vehicle = row.get("plate_number") or row.get("vehicle_code") or "مركبة"
            notifications.append(_notification(
                f"vehicle_reports:{row['id']}", "vehicle_reports",
                f"بلاغ جديد للمركبة {vehicle}",
                f"{row.get('submission_type') or 'بلاغ'}: {row.get('message') or ''}",
                "/vehicles/public-submissions", "info", row.get("submitted_at")
            ))

        # Driver license expiry.
        for row in _rows(
            connection, "drivers", ("id", "name", "license_expiry_date"),
            "SELECT id, name, license_expiry_date FROM drivers WHERE license_expiry_date IS NOT NULL",
        ):
            alert = _expiry_alert(
                row["id"], "driver_licenses", "رخصة السائق",
                row.get("license_expiry_date"),
                f"رخصة السائق {row.get('name') or ''}", "/drivers/"
            )
            if alert:
                notifications.append(alert)

        # Open maintenance jobs with a deadline that can be derived from their expected duration.
        maintenance_columns = _table_columns(connection, "maintenance_orders")
        if {"id", "type", "status", "order_no"}.issubset(maintenance_columns):
            orders = [dict(row) for row in connection.execute(
                "SELECT * FROM maintenance_orders WHERE status = 'open' ORDER BY id DESC"
            ).fetchall()]
            for row in orders:
                expected = row.get("expected_completion_time") or row.get("expected_time")
                start = row.get("order_date") or row.get("send_datetime") or row.get("incident_datetime")
                deadline = _duration_deadline(start, expected)
                if deadline and deadline < date.today():
                    notifications.append(_notification(
                        f"maintenance:{row['id']}", "maintenance",
                        f"أمر الصيانة {row.get('order_no') or row['id']} تجاوز موعد الإنجاز",
                        f"المركبة {row.get('plate_number') or row.get('vehicle_code') or '-'} — الموعد المتوقع {deadline.isoformat()}",
                        f"/workshop/maintenance/list/{row.get('type') or 'internal'}?status=open",
                        "danger", deadline.isoformat()
                    ))

        # Comprehensive inspection items requiring attention.
        if {"id", "inspection_id", "status", "item_name"}.issubset(
            _table_columns(connection, "comprehensive_inspection_items")
        ):
            for row in connection.execute(
                """SELECT i.id, i.inspection_id, i.item_name, i.status, i.item_notes,
                          c.vehicle_plate, c.inspection_date
                   FROM comprehensive_inspection_items i
                   LEFT JOIN comprehensive_inspections c ON c.id = i.inspection_id
                   WHERE lower(i.status) IN ('warning', 'fail')
                      OR i.status IN ('تنبيه', 'تالف') ORDER BY i.id DESC"""
            ).fetchall():
                item = dict(row)
                failed = str(item.get("status", "")).lower() in ("fail", "تالف")
                notifications.append(_notification(
                    f"comprehensive_inspection:{item['id']}", "comprehensive_inspection",
                    f"بند فحص يحتاج متابعة: {item.get('item_name') or ''}",
                    f"المركبة {item.get('vehicle_plate') or '-'} — {item.get('item_notes') or item.get('status') or ''}",
                    "/workshop/comp-inspection/",
                    "danger" if failed else "warning", item.get("inspection_date")
                ))

        # Stock threshold.
        for row in _rows(
            connection, "store_items", ("id", "name", "quantity", "min_limit"),
            "SELECT id, name, quantity, min_limit FROM store_items WHERE quantity <= min_limit",
        ):
            notifications.append(_notification(
                f"store:{row['id']}", "store",
                f"مخزون منخفض: {row.get('name') or ''}",
                f"الكمية الحالية {row.get('quantity', 0)}، وحد التنبيه {row.get('min_limit', 0)}",
                "/workshop/store/", "warning"
            ))

        # Workshop team license expiry.
        for row in _rows(
            connection, "team_members", ("id", "full_name", "license_expiry_date"),
            "SELECT id, full_name, license_expiry_date FROM team_members WHERE license_expiry_date IS NOT NULL",
        ):
            alert = _expiry_alert(
                row["id"], "team_licenses", "رخصة عضو فريق العمل",
                row.get("license_expiry_date"),
                f"رخصة {row.get('full_name') or 'عضو فريق العمل'}",
                "/workshop/team/"
            )
            if alert:
                notifications.append(alert)

        # Workshop assets explicitly marked for urgent maintenance.
        for row in _rows(
            connection, "workshop_assets",
            ("id", "asset_code", "name", "condition_status"),
            "SELECT id, asset_code, name, condition_status FROM workshop_assets",
        ):
            if row.get("condition_status") == "يحتاج صيانة عاجلة":
                notifications.append(_notification(
                    f"workshop_assets:{row['id']}", "workshop_assets",
                    f"أصل يحتاج صيانة عاجلة: {row.get('name') or ''}",
                    f"كود الأصل {row.get('asset_code') or '-'}",
                    "/workshop/equ/", "danger"
                ))

        # Reuse the oil module's own business rule for alert thresholds.
        if {"id", "vehicle_plate", "current_mileage", "last_oil_mileage"}.issubset(
            _table_columns(connection, "oil_change_tracking")
        ):
            from modules.workshop.oil_tracking.oil_tracking_service import OilTrackingService
            records = connection.execute("SELECT * FROM oil_change_tracking ORDER BY id DESC").fetchall()
            for raw in records:
                record = dict(raw)
                try:
                    if record.get("tracking_mode") == "time":
                        service_date = _parse_date(record.get("service_date"))
                        if service_date is None:
                            continue
                        months = max(1, int(record.get("time_interval_months") or 3))
                        month_index = service_date.month - 1 + months
                        year = service_date.year + month_index // 12
                        month = month_index % 12 + 1
                        target = service_date.replace(
                            year=year,
                            month=month,
                            day=min(service_date.day, calendar.monthrange(year, month)[1]),
                        )
                        remaining = (target - date.today()).days
                        threshold = max(0, int(record.get("time_alert_threshold") or 15))
                        is_alert = remaining <= threshold
                        message = (
                            f"تجاوز موعد تغيير الزيت منذ {abs(remaining)} يوم"
                            if remaining < 0
                            else f"موعد تغيير الزيت خلال {remaining} يوم"
                        )
                        oil_severity = "danger" if remaining < 0 else "warning"
                    else:
                        _, message, is_alert = OilTrackingService.calculate_status(record)
                        oil_severity = "danger" if "انتهت" in message else "warning"
                except (TypeError, ValueError) as error:
                    logger.warning("Unable to calculate oil alert for record %s: %s", record.get("id"), error)
                    continue
                if is_alert:
                    notifications.append(_notification(
                        f"oil:{record['id']}", "oil",
                        f"موعد تغيير الزيت للمركبة {record.get('vehicle_plate') or ''}",
                        message, "/workshop/oil-tracking/", oil_severity
                    ))

        # Unsettled traffic violations.
        for row in _rows(
            connection, "violations", ("id", "vehicle_plate", "violation_number", "status", "violation_datetime"),
            """SELECT id, vehicle_plate, violation_number, status, violation_datetime, violation_type
               FROM violations WHERE status = 'active' OR status IS NULL ORDER BY id DESC""",
        ):
            notifications.append(_notification(
                f"violations:{row['id']}", "violations",
                f"مخالفة مرورية غير مسددة {row.get('violation_number') or ''}",
                f"المركبة {row.get('vehicle_plate') or '-'} — {row.get('violation_type') or ''}",
                "/violations/", "warning", row.get("violation_datetime")
            ))

        # Periodic inspection expiry.
        for row in _rows(
            connection, "inspections", ("id", "vehicle_plate", "expiry_date", "result_status"),
            "SELECT id, vehicle_plate, expiry_date, result_status FROM inspections WHERE expiry_date IS NOT NULL",
        ):
            if row.get("result_status") not in ("ناجح", "Pass", "pass"):
                continue
            alert = _expiry_alert(
                row["id"], "inspections", "الفحص الدوري",
                row.get("expiry_date"),
                f"فحص المركبة {row.get('vehicle_plate') or ''}",
                "/inspection/"
            )
            if alert:
                notifications.append(alert)

        # Insurance expiry.
        for row in _rows(
            connection, "insurance_policies", ("id", "vehicle_plate", "end_date"),
            "SELECT id, vehicle_plate, end_date FROM insurance_policies WHERE end_date IS NOT NULL",
        ):
            alert = _expiry_alert(
                row["id"], "insurance", "وثيقة التأمين",
                row.get("end_date"),
                f"تأمين المركبة {row.get('vehicle_plate') or ''}",
                "/insurance/"
            )
            if alert:
                notifications.append(alert)

        # Accidents awaiting closure.
        for row in _rows(
            connection, "accidents", ("id", "accident_number", "vehicle_plate", "status", "accident_datetime"),
            """SELECT id, accident_number, vehicle_plate, status, accident_datetime
               FROM accidents WHERE status = 'active' OR status IS NULL ORDER BY id DESC""",
        ):
            notifications.append(_notification(
                f"accidents:{row['id']}", "accidents",
                f"حادث مروري قيد المتابعة {row.get('accident_number') or ''}",
                f"المركبة {row.get('vehicle_plate') or '-'}",
                "/accidents/", "danger", row.get("accident_datetime")
            ))

        return notifications

    @classmethod
    def get_notifications(cls, user_id, category=None, read_filter="all"):
        NotificationsModel.create_table()
        with closing(NotificationsModel.get_connection()) as connection:
            notifications = cls._get_source_notifications(connection)
            states = {
                row["notification_id"]: dict(row)
                for row in connection.execute(
                    "SELECT * FROM notification_user_state WHERE user_id = ?", (str(user_id),)
                ).fetchall()
            }

        active = []
        for notification in notifications:
            state = states.get(notification["id"], {})
            if state.get("is_deleted"):
                continue
            notification["is_read"] = bool(state.get("is_read", 0))
            notification["is_pinned"] = bool(state.get("is_pinned", 0))
            active.append(notification)

        if category in CATEGORIES:
            active = [item for item in active if item["category"] == category]
        if read_filter == "unread":
            active = [item for item in active if not item["is_read"]]
        elif read_filter == "read":
            active = [item for item in active if item["is_read"]]

        severity_order = {"danger": 0, "warning": 1, "info": 2}
        active.sort(
            key=lambda item: (
                not item["is_pinned"],
                severity_order.get(item["severity"], 3),
                -(_parse_date(item["created_at"]) or date.min).toordinal(),
                item["id"],
            ),
        )
        return active

    @classmethod
    def unread_count(cls, user_id):
        return sum(
            not item["is_read"]
            for item in cls.get_notifications(user_id)
        )

    @staticmethod
    def update_state(user_id, notification_id, **values):
        allowed = {"is_read", "is_pinned", "is_deleted"}
        updates = {key: int(value) for key, value in values.items() if key in allowed}
        if not updates:
            return
        NotificationsModel.create_table()
        columns = ", ".join(f"{column} = excluded.{column}" for column in updates)
        fields = ", ".join(updates)
        placeholders = ", ".join("?" for _ in updates)
        with closing(NotificationsModel.get_connection()) as connection:
            connection.execute(
                f"""INSERT INTO notification_user_state
                    (user_id, notification_id, {fields})
                    VALUES (?, ?, {placeholders})
                    ON CONFLICT(user_id, notification_id) DO UPDATE SET
                    {columns}, updated_at = CURRENT_TIMESTAMP""",
                (str(user_id), notification_id, *updates.values()),
            )
            connection.commit()

    @classmethod
    def mark_filtered_deleted(cls, user_id, category=None, read_filter="all"):
        notifications = cls.get_notifications(user_id, category, read_filter)
        NotificationsModel.create_table()
        with closing(NotificationsModel.get_connection()) as connection:
            connection.executemany(
                """INSERT INTO notification_user_state
                   (user_id, notification_id, is_deleted)
                   VALUES (?, ?, 1)
                   ON CONFLICT(user_id, notification_id) DO UPDATE SET
                   is_deleted = 1, updated_at = CURRENT_TIMESTAMP""",
                [(str(user_id), item["id"]) for item in notifications],
            )
            connection.commit()
        return len(notifications)

    @staticmethod
    def mark_all_read(user_id):
        notifications = NotificationsService.get_notifications(user_id, read_filter="unread")
        NotificationsModel.create_table()
        with closing(NotificationsModel.get_connection()) as connection:
            connection.executemany(
                """INSERT INTO notification_user_state
                   (user_id, notification_id, is_read)
                   VALUES (?, ?, 1)
                   ON CONFLICT(user_id, notification_id) DO UPDATE SET
                   is_read = 1, updated_at = CURRENT_TIMESTAMP""",
                [(str(user_id), item["id"]) for item in notifications],
            )
            connection.commit()
        return len(notifications)
