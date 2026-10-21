import logging
import re
import calendar
from datetime import date, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.database import get_session, now_text
from modules.accidents.models.accidents_orm import Accident
from modules.drivers.models.driver_orm import Driver
from modules.inspection.models.inspection_orm import Inspection
from modules.insurance.models.insurance_orm import InsurancePolicy
from modules.notifications.models.notifications_model import NotificationsModel
from modules.notifications.models.notifications_orm import NotificationUserState
from modules.settings.models.settings_orm import SystemSetting
from modules.vehicles.models.public_submission_orm import VehiclePublicSubmission
from modules.vehicles.models.vehicle_orm import Vehicle
from modules.violations.models.violation_orm import Violation
from modules.workshop.comp_inspection.comp_inspection_orm import (
    ComprehensiveInspection, ComprehensiveInspectionItem,
)
from modules.workshop.equ.models.asset_orm import WorkshopAssetRecord
from modules.workshop.maintenance.models.maintenance_orm import MaintenanceOrder
from modules.workshop.oil_tracking.oil_orm import OilChangeRecord
from modules.workshop.store.models.store_model import StoreItem
from modules.workshop.team.team_orm import TeamMember


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


def _expiry_alert(record_id, category, label, expiry_value, title, target, alert_days=30):
    expiry = _parse_date(expiry_value)
    if expiry is None:
        return None
    remaining = (expiry - date.today()).days
    if remaining > alert_days:
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
    _SETTING_KEYS = (
        'license_alert_enabled', 'license_alert_days',
        'inspection_alert_enabled', 'inspection_alert_days',
        'insurance_alert_enabled', 'insurance_alert_days',
        'oil_alert_enabled',
    )

    @staticmethod
    def _get_source_notifications(session):
        notifications = []
        settings = {
            key: value for key, value in session.execute(
                select(SystemSetting.key, SystemSetting.value)
                .where(SystemSetting.key.in_(NotificationsService._SETTING_KEYS))
            )
        }

        def alert_enabled(key):
            return settings.get(key, "1") == "1"

        def alert_days(key):
            try:
                return min(max(int(settings.get(key, "30")), 0), 365)
            except (TypeError, ValueError):
                logger.error("Invalid notification period setting %s", key)
                return 30

        def rows(statement):
            return [dict(row) for row in session.execute(statement).mappings()]

        # Fresh vehicle QR reports submitted for equipment-management review.
        for row in rows(
            select(
                VehiclePublicSubmission.id, VehiclePublicSubmission.submission_type,
                VehiclePublicSubmission.message, VehiclePublicSubmission.submitted_at,
                Vehicle.vehicle_code, Vehicle.plate_number,
            )
            .outerjoin(Vehicle, Vehicle.id == VehiclePublicSubmission.vehicle_id)
            .where(VehiclePublicSubmission.status == 'جديد')
            .order_by(VehiclePublicSubmission.id.desc())
        ):
            vehicle = row.get("plate_number") or row.get("vehicle_code") or "مركبة"
            notifications.append(_notification(
                f"vehicle_reports:{row['id']}", "vehicle_reports",
                f"بلاغ جديد للمركبة {vehicle}",
                f"{row.get('submission_type') or 'بلاغ'}: {row.get('message') or ''}",
                "/vehicles/public-submissions", "info", row.get("submitted_at")
            ))

        # Driver license expiry.
        for row in (rows(
            select(Driver.id, Driver.name, Driver.license_expiry_date)
            .where(Driver.license_expiry_date.is_not(None))
        ) if alert_enabled("license_alert_enabled") else []):
            alert = _expiry_alert(
                row["id"], "driver_licenses", "رخصة السائق",
                row.get("license_expiry_date"),
                f"رخصة السائق {row.get('name') or ''}", "/drivers/",
                alert_days("license_alert_days"),
            )
            if alert:
                notifications.append(alert)

        # Open maintenance jobs with a deadline that can be derived from their expected duration.
        for order in session.scalars(
            select(MaintenanceOrder).where(MaintenanceOrder.status == 'open')
            .order_by(MaintenanceOrder.id.desc())
        ):
            row = order.to_dict()
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
        for item in rows(
            select(
                ComprehensiveInspectionItem.id, ComprehensiveInspectionItem.inspection_id,
                ComprehensiveInspectionItem.item_name, ComprehensiveInspectionItem.status,
                ComprehensiveInspectionItem.item_notes,
                ComprehensiveInspection.vehicle_plate, ComprehensiveInspection.inspection_date,
            )
            .outerjoin(
                ComprehensiveInspection,
                ComprehensiveInspection.id == ComprehensiveInspectionItem.inspection_id,
            )
            .where(or_(
                func.lower(ComprehensiveInspectionItem.status).in_(('warning', 'fail')),
                ComprehensiveInspectionItem.status.in_(('تنبيه', 'تالف')),
            ))
            .order_by(ComprehensiveInspectionItem.id.desc())
        ):
            failed = str(item.get("status", "")).lower() in ("fail", "تالف")
            notifications.append(_notification(
                f"comprehensive_inspection:{item['id']}", "comprehensive_inspection",
                f"بند فحص يحتاج متابعة: {item.get('item_name') or ''}",
                f"المركبة {item.get('vehicle_plate') or '-'} — {item.get('item_notes') or item.get('status') or ''}",
                "/workshop/comp-inspection/",
                "danger" if failed else "warning", item.get("inspection_date")
            ))

        # Stock threshold.
        for row in rows(
            select(StoreItem.id, StoreItem.name, StoreItem.quantity, StoreItem.min_limit)
            .where(StoreItem.quantity <= StoreItem.min_limit)
        ):
            notifications.append(_notification(
                f"store:{row['id']}", "store",
                f"مخزون منخفض: {row.get('name') or ''}",
                f"الكمية الحالية {row.get('quantity', 0)}، وحد التنبيه {row.get('min_limit', 0)}",
                "/workshop/store/", "warning"
            ))

        # Workshop team license expiry.
        for row in (rows(
            select(TeamMember.id, TeamMember.full_name, TeamMember.license_expiry_date)
            .where(TeamMember.license_expiry_date.is_not(None))
        ) if alert_enabled("license_alert_enabled") else []):
            alert = _expiry_alert(
                row["id"], "team_licenses", "رخصة عضو فريق العمل",
                row.get("license_expiry_date"),
                f"رخصة {row.get('full_name') or 'عضو فريق العمل'}",
                "/workshop/team/", alert_days("license_alert_days")
            )
            if alert:
                notifications.append(alert)

        # Workshop assets explicitly marked for urgent maintenance.
        for row in rows(
            select(WorkshopAssetRecord.id, WorkshopAssetRecord.asset_code, WorkshopAssetRecord.name)
            .where(WorkshopAssetRecord.condition_status == "يحتاج صيانة عاجلة")
        ):
            notifications.append(_notification(
                f"workshop_assets:{row['id']}", "workshop_assets",
                f"أصل يحتاج صيانة عاجلة: {row.get('name') or ''}",
                f"كود الأصل {row.get('asset_code') or '-'}",
                "/workshop/equ/", "danger"
            ))

        # Reuse the oil module's own business rule for alert thresholds.
        if alert_enabled("oil_alert_enabled"):
            from modules.workshop.oil_tracking.oil_tracking_service import OilTrackingService
            for oil_record in session.scalars(
                select(OilChangeRecord).order_by(OilChangeRecord.id.desc())
            ):
                record = oil_record.to_dict()
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
        for row in rows(
            select(
                Violation.id, Violation.vehicle_plate, Violation.violation_number,
                Violation.violation_datetime, Violation.violation_type,
            )
            .where(or_(Violation.status == 'active', Violation.status.is_(None)))
            .order_by(Violation.id.desc())
        ):
            notifications.append(_notification(
                f"violations:{row['id']}", "violations",
                f"مخالفة مرورية غير مسددة {row.get('violation_number') or ''}",
                f"المركبة {row.get('vehicle_plate') or '-'} — {row.get('violation_type') or ''}",
                "/violations/", "warning", row.get("violation_datetime")
            ))

        # Periodic inspection expiry.
        for row in (rows(
            select(Inspection.id, Inspection.vehicle_plate, Inspection.expiry_date, Inspection.result_status)
            .where(Inspection.expiry_date.is_not(None))
        ) if alert_enabled("inspection_alert_enabled") else []):
            if row.get("result_status") not in ("ناجح", "Pass", "pass"):
                continue
            alert = _expiry_alert(
                row["id"], "inspections", "الفحص الدوري",
                row.get("expiry_date"),
                f"فحص المركبة {row.get('vehicle_plate') or ''}",
                "/inspection/", alert_days("inspection_alert_days")
            )
            if alert:
                notifications.append(alert)

        # Insurance expiry.
        for row in (rows(
            select(InsurancePolicy.id, InsurancePolicy.vehicle_plate, InsurancePolicy.end_date)
            .where(InsurancePolicy.end_date.is_not(None))
        ) if alert_enabled("insurance_alert_enabled") else []):
            alert = _expiry_alert(
                row["id"], "insurance", "وثيقة التأمين",
                row.get("end_date"),
                f"تأمين المركبة {row.get('vehicle_plate') or ''}",
                "/insurance/", alert_days("insurance_alert_days")
            )
            if alert:
                notifications.append(alert)

        # Accidents awaiting closure.
        for row in rows(
            select(
                Accident.id, Accident.accident_number, Accident.vehicle_plate, Accident.accident_datetime,
            )
            .where(or_(Accident.status == 'active', Accident.status.is_(None)))
            .order_by(Accident.id.desc())
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
        with get_session() as session:
            notifications = cls._get_source_notifications(session)
            states = {
                state.notification_id: state
                for state in session.scalars(
                    select(NotificationUserState).where(NotificationUserState.user_id == str(user_id))
                )
            }

        active = []
        for notification in notifications:
            state = states.get(notification["id"])
            if state is not None and state.is_deleted:
                continue
            notification["is_read"] = bool(state.is_read) if state is not None else False
            notification["is_pinned"] = bool(state.is_pinned) if state is not None else False
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
    def _upsert_states(user_id, notification_ids, values):
        if not notification_ids:
            return
        rows = [
            {"user_id": str(user_id), "notification_id": notification_id, "updated_at": now_text(), **values}
            for notification_id in notification_ids
        ]
        statement = pg_insert(NotificationUserState).values(rows)
        statement = statement.on_conflict_do_update(
            index_elements=["user_id", "notification_id"],
            set_={**{key: statement.excluded[key] for key in values}, "updated_at": now_text()},
        )
        with get_session() as session:
            session.execute(statement)

    @staticmethod
    def update_state(user_id, notification_id, **values):
        allowed = {"is_read", "is_pinned", "is_deleted"}
        updates = {key: int(value) for key, value in values.items() if key in allowed}
        if not updates:
            return
        NotificationsModel.create_table()
        NotificationsService._upsert_states(user_id, [notification_id], updates)

    @classmethod
    def mark_filtered_deleted(cls, user_id, category=None, read_filter="all"):
        notifications = cls.get_notifications(user_id, category, read_filter)
        NotificationsModel.create_table()
        cls._upsert_states(user_id, [item["id"] for item in notifications], {"is_deleted": 1})
        return len(notifications)

    @staticmethod
    def mark_all_read(user_id):
        notifications = NotificationsService.get_notifications(user_id, read_filter="unread")
        NotificationsModel.create_table()
        NotificationsService._upsert_states(user_id, [item["id"] for item in notifications], {"is_read": 1})
        return len(notifications)
