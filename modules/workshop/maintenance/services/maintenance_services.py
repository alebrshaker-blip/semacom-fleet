import datetime
import os
import time
from pathlib import Path

from sqlalchemy import func, select, text

from core import storage
from core.database import get_session
from core.orm_utils import to_float
from modules.drivers.models.driver_orm import Driver
from modules.vehicles import repository as vehicles_repository
from modules.workshop.maintenance.models.maintenance_orm import MaintenanceOrder
from utils.generators import generate_work_order_no

VALID_TYPES = {'internal', 'external', 'emergency', 'exceptional'}

# Form fields copied as-is onto a new order.
_OPEN_FIELDS = (
    'maintenance_type', 'fault_description', 'fault_cause', 'severity',
    'technician_name', 'expected_completion_time',
    'workshop_name', 'workshop_phone', 'workshop_location', 'send_reason',
    'send_datetime', 'responsible_person', 'expected_time', 'notes',
    'driver_id', 'reporter_name', 'case_description', 'has_injuries',
    'is_drivable', 'official_notified', 'emergency_location',
    'incident_datetime', 'subject', 'description', 'causes', 'other_details',
)

_CLOSE_FIELDS = (
    'closure_reason', 'spare_parts', 'recommendation', 'closing_notes',
    'action_taken', 'is_towed', 'towing_party', 'intervention_team', 'treatment_details',
)


UPLOAD_FOLDER = 'maintenance'


class MaintenanceService:

    @classmethod
    def get_all_vehicles(cls):
        """جلب بيانات المركبات للنموذج"""
        try:
            vehicles = []
            for row in vehicles_repository.list_active():
                code = row.get('vehicle_code') or row.get('code') or ''
                plate = row.get('plate_number') or row.get('plate') or ''
                vehicles.append({
                    'id': row.get('id'),
                    'vehicle_code': str(code).strip(),
                    'plate_number': str(plate).strip(),
                })
            return vehicles
        except Exception as e:
            print(f"[ERROR - get_all_vehicles]: {e}")
            return []

    @classmethod
    def get_all_drivers(cls):
        """جلب قائمة السائقين"""
        try:
            with get_session() as session:
                drivers = session.scalars(select(Driver).order_by(Driver.id)).all()
                return [{'id': d.id, 'name': str(d.name or '').strip()} for d in drivers]
        except Exception as e:
            print(f"[ERROR - get_all_drivers]: {e}")
            return []

    @classmethod
    def get_all_team_members(cls):
        """جلب قائمة الفنيين وأعضاء الفريق"""
        members = []
        try:
            with get_session() as session:
                if session.execute(text("SELECT to_regclass('team_members')")).scalar():
                    rows = session.execute(text("SELECT * FROM team_members ORDER BY id")).mappings()
                    for rd in rows:
                        m_name = rd.get('full_name') or rd.get('name') or ''
                        if m_name:
                            members.append({
                                'id': rd.get('id'),
                                'name': str(m_name).strip(),
                                'job_title': rd.get('job_title') or '',
                            })
                if not members:
                    for d in session.scalars(select(Driver).order_by(Driver.id)):
                        if d.name:
                            members.append({
                                'id': d.id,
                                'name': str(d.name).strip(),
                                'job_title': d.job_title or 'فني',
                            })
        except Exception as e:
            print(f"[ERROR - get_all_team_members]: {e}")
        return members

    @classmethod
    def create_order(cls, data):
        """إنشاء أمر الصيانة وحفظ بيانات الفتح بحقولها المعتمدة"""
        try:
            m_type = data.get('type', 'internal')
            order_no = generate_work_order_no(m_type)

            vehicle = None
            vehicle_id = data.get('vehicle_id')
            if vehicle_id:
                vehicle = next(
                    (v for v in vehicles_repository.list_active() if str(v['id']) == str(vehicle_id)),
                    None,
                )
                if not vehicle:
                    raise ValueError("لا يمكن إنشاء أمر صيانة لمركبة مؤرشفة أو خارج الخدمة.")

            order = MaintenanceOrder(
                order_no=order_no,
                type=m_type,
                status='open',
                vehicle_id=int(vehicle_id) if vehicle_id else None,
                vehicle_code=vehicle['vehicle_code'] if vehicle else data.get('vehicle_code'),
                plate_number=vehicle['plate_number'] if vehicle else data.get('plate_number'),
                order_date=data.get('order_date') or datetime.date.today().strftime('%Y-%m-%d'),
                expected_cost=to_float(data.get('expected_cost'), 0.0),
                **{field: data.get(field) for field in _OPEN_FIELDS},
            )
            with get_session() as session:
                session.add(order)
            return order_no
        except Exception as e:
            print(f"[ERROR - create_order]: {e}")
            raise

    @classmethod
    def get_orders(cls, m_type, status='open'):
        """جلب أوامر الصيانة حسب النوع والحالة"""
        try:
            with get_session() as session:
                rows = session.scalars(
                    select(MaintenanceOrder)
                    .where(MaintenanceOrder.type == m_type, MaintenanceOrder.status == status)
                    .order_by(MaintenanceOrder.id.desc())
                ).all()
                return [r.to_dict() for r in rows]
        except Exception as e:
            print(f"[ERROR - get_orders]: {e}")
            return []

    @classmethod
    def get_all_orders(cls, m_type='all', status='all', date_from=None, date_to=None):
        """جلب جميع أوامر الصيانة مع فلاتر النوع والحالة والفترة الزمنية"""
        M = MaintenanceOrder
        stmt = select(M)
        if m_type in VALID_TYPES:
            stmt = stmt.where(M.type == m_type)
        if status in {'open', 'closed'}:
            stmt = stmt.where(M.status == status)

        order_date = func.coalesce(
            func.nullif(M.order_date, ''), func.nullif(M.send_datetime, ''),
            func.nullif(M.incident_datetime, ''), func.nullif(M.closure_date, ''),
            func.nullif(M.closure_datetime, ''), '',
        )
        if date_from:
            stmt = stmt.where(func.substr(order_date, 1, 10) >= date_from)
        if date_to:
            stmt = stmt.where(func.substr(order_date, 1, 10) <= date_to)
        stmt = stmt.order_by(text("CASE status WHEN 'open' THEN 0 ELSE 1 END"), M.id.desc())

        try:
            with get_session() as session:
                return [r.to_dict() for r in session.scalars(stmt).all()]
        except Exception as e:
            print(f"[ERROR - get_all_orders]: {e}")
            return []

    @classmethod
    def get_order_by_id(cls, order_id):
        """جلب أمر صيانة محدد برقم ID"""
        try:
            with get_session() as session:
                order = session.get(MaintenanceOrder, int(order_id))
                return order.to_dict() if order else None
        except Exception as e:
            print(f"[ERROR - get_order_by_id]: {e}")
            return None

    @classmethod
    def delete_order(cls, order_id):
        """حذف أمر الصيانة"""
        try:
            attachments = []
            with get_session() as session:
                order = session.get(MaintenanceOrder, int(order_id))
                if order:
                    attachments = [order.photo_before, order.photo_after, order.other_attachments]
                    session.delete(order)
            storage.delete_files(*attachments)
        except Exception as e:
            print(f"[ERROR - delete_order]: {e}")
            raise

    @classmethod
    def close_order(cls, order_id, close_data, files=None):
        """إقفال أمر الصيانة وحفظ بيانات الإقفال والملفات المرفقة"""
        uploaded = []
        try:
            file_paths = {}
            if files:
                for f_key in ('photo_before', 'photo_after', 'other_attachments'):
                    file_item = files.get(f_key)
                    url = storage.upload_file(file_item, UPLOAD_FOLDER)
                    if url:
                        uploaded.append(url)
                        file_paths[f_key] = url

            current_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
            with get_session() as session:
                order = session.get(MaintenanceOrder, int(order_id))
                if order is None:
                    return
                order.status = 'closed'
                order.closure_date = close_data.get('closure_date') or datetime.date.today().strftime('%Y-%m-%d')
                order.receipt_datetime = close_data.get('receipt_datetime') or current_time
                order.closure_datetime = close_data.get('closure_datetime') or current_time
                order.final_cost = to_float(close_data.get('final_cost'), 0.0)
                for field in _CLOSE_FIELDS:
                    setattr(order, field, close_data.get(field))
                # Keep existing attachments when no new file was uploaded (COALESCE semantics).
                for field, path in file_paths.items():
                    setattr(order, field, path)
        except Exception as e:
            storage.delete_files(*uploaded)
            print(f"[ERROR - close_order]: {e}")
            raise
