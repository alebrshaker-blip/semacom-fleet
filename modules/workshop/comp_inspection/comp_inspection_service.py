from datetime import datetime
import json

from sqlalchemy import delete, exists, func, select

from core.database import get_session
from modules.vehicles.models.vehicle_orm import Vehicle, VehicleArchive
from modules.workshop.comp_inspection.comp_inspection_orm import (
    ComprehensiveInspection, ComprehensiveInspectionItem,
)
from modules.workshop.oil_tracking.oil_orm import OilChangeRecord
from modules.workshop.team.team_orm import TeamMember
from utils.data_types import parse_non_negative_integer


class CompInspectionService:
    @staticmethod
    def _normalize_inspection_items(items_data):
        normalized = []
        for category, item_name, status, item_note in items_data or []:
            category = (category or '').strip()
            item_name = (item_name or '').strip()
            status = (status or '').strip()
            item_note = (item_note or '').strip()
            if category or item_name or status or item_note:
                normalized.append((category, item_name, status, item_note))
        return normalized

    @staticmethod
    def _with_inspector_names(record):
        inspection = dict(record)
        try:
            names = json.loads(inspection.get('inspector_names_json') or '[]')
        except (TypeError, json.JSONDecodeError):
            names = []
        if not isinstance(names, list) or not names:
            names = [inspection.get('inspector_name')] if inspection.get('inspector_name') else []
        inspection['inspector_names'] = '، '.join(str(name) for name in names)
        return inspection

    @staticmethod
    def get_all_inspections():
        with get_session() as session:
            rows = session.scalars(
                select(ComprehensiveInspection).order_by(ComprehensiveInspection.id.desc())
            )
            return [CompInspectionService._with_inspector_names(r.to_dict()) for r in rows]

    @staticmethod
    def get_all_vehicles():
        """جلب أرقام لوحات المركبات المسجلة في النظام"""
        try:
            with get_session() as session:
                archived = exists().where(VehicleArchive.vehicle_id == Vehicle.id)
                return list(session.scalars(
                    select(Vehicle.plate_number)
                    .where(~archived, func.coalesce(Vehicle.status, '') != 'خارج الخدمة')
                ))
        except Exception:
            return []

    @staticmethod
    def get_all_team_members():
        """جلب أعضاء فريق العمل من المصدر المستخدم لإدارة فريق الورشة."""
        with get_session() as session:
            rows = session.execute(
                select(TeamMember.id, TeamMember.full_name, TeamMember.job_title, TeamMember.specialization)
                .where(TeamMember.full_name.is_not(None), func.trim(TeamMember.full_name) != '')
                .order_by(func.lower(TeamMember.full_name))
            ).mappings()
            return [dict(row) for row in rows]

    @staticmethod
    def get_inspection_by_id(inspection_id):
        with get_session() as session:
            inspection = session.get(ComprehensiveInspection, inspection_id)
            items = session.scalars(
                select(ComprehensiveInspectionItem)
                .where(ComprehensiveInspectionItem.inspection_id == inspection_id)
                .order_by(ComprehensiveInspectionItem.id)
            )
            items = [item.to_dict() for item in items]
            return (
                CompInspectionService._with_inspector_names(inspection.to_dict()) if inspection else None,
                items,
            )

    @staticmethod
    def get_latest_oil_mileages():
        with get_session() as session:
            records = session.execute(
                select(OilChangeRecord.vehicle_plate, OilChangeRecord.current_mileage)
                .order_by(OilChangeRecord.service_date.desc(), OilChangeRecord.id.desc())
            )
            latest_mileages = {}
            for plate, mileage in records:
                plate = str(plate or '').strip()
                if plate and plate not in latest_mileages:
                    latest_mileages[plate] = mileage
            return latest_mileages

    @staticmethod
    def create_inspection(form_data, items_data, inspector_ids):
        vehicle_plate = str(form_data.get('vehicle_plate') or '').strip()
        if not vehicle_plate:
            raise ValueError("يرجى اختيار المركبة المراد إجراء الفحص عليها.")
        current_mileage = parse_non_negative_integer(
            form_data.get('current_mileage'),
            'قراءة العداد الحالية',
            required=True,
        )
        oil_change_mileage = parse_non_negative_integer(
            form_data.get('oil_change_mileage'),
            'قراءة العداد عند آخر تغيير زيت',
        )
        if oil_change_mileage is not None and oil_change_mileage > current_mileage:
            raise ValueError("لا يمكن أن تتجاوز قراءة آخر تغيير زيت قراءة العداد الحالية.")

        inspector_ids = list(dict.fromkeys(str(member_id).strip() for member_id in inspector_ids if str(member_id).strip()))
        if len(inspector_ids) < 2:
            raise ValueError("يرجى اختيار فنيين اثنين على الأقل لإجراء الفحص.")
        try:
            member_ids = [int(member_id) for member_id in inspector_ids]
        except ValueError:
            raise ValueError("تعذر العثور على أحد الفنيين المختارين ضمن فريق العمل الحالي.")

        items_data = CompInspectionService._normalize_inspection_items(items_data)
        if not items_data:
            raise ValueError("يرجى إضافة بند واحد على الأقل للفحص الشامل.")

        with get_session() as session:
            selected_members = session.execute(
                select(TeamMember.id, TeamMember.full_name)
                .where(
                    TeamMember.id.in_(member_ids),
                    TeamMember.full_name.is_not(None), func.trim(TeamMember.full_name) != '',
                )
                .order_by(func.lower(TeamMember.full_name))
            ).all()
            if len(selected_members) != len(member_ids):
                raise ValueError("تعذر العثور على أحد الفنيين المختارين ضمن فريق العمل الحالي.")
            inspector_names = [name for _, name in selected_members]
            normalized_inspector_ids = [member_id for member_id, _ in selected_members]

            inspection = ComprehensiveInspection(
                vehicle_plate=vehicle_plate,
                inspector_name='، '.join(inspector_names),
                inspector_names_json=json.dumps(inspector_names, ensure_ascii=False),
                inspector_ids_json=json.dumps(normalized_inspector_ids),
                inspection_date=form_data.get('inspection_date') or datetime.now().strftime('%Y-%m-%d'),
                current_mileage=current_mileage,
                oil_change_mileage=oil_change_mileage,
                overall_status=form_data.get('overall_status') or 'سليم',
                notes=form_data.get('notes'),
                document_number=f"REQ-CINS-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            )
            session.add(inspection)
            session.flush()
            session.add_all(
                ComprehensiveInspectionItem(
                    inspection_id=inspection.id, category=cat, item_name=name,
                    status=stat, item_notes=in_note,
                )
                for cat, name, stat, in_note in items_data
            )
        return True

    @staticmethod
    def delete_inspection(inspection_id):
        with get_session() as session:
            session.execute(
                delete(ComprehensiveInspectionItem)
                .where(ComprehensiveInspectionItem.inspection_id == inspection_id)
            )
            result = session.execute(
                delete(ComprehensiveInspection).where(ComprehensiveInspection.id == inspection_id)
            )
            return result.rowcount > 0
