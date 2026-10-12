import json
import os
import re
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime
from flask import Blueprint, current_app, render_template, request, jsonify, redirect, url_for, abort
from modules.reports.controllers.reports_controller import ReportsController
from .services.reports_service import (
    generate_reference_number,
    generate_document_qr,
    init_report_counter_db,
    DB_PATH,
    QR_DIR,
    REPORTS_DIR
)
from core.database import Database
from modules.workshop.maintenance.controller.maintenance_controller import MaintenanceController
from modules.workshop.maintenance.controller.maintenance_controller import TYPE_TITLES as MAINTENANCE_TYPE_TITLES
from modules.workshop.maintenance.services.maintenance_services import MaintenanceService
from modules.drivers.models.drivers_model import DB_PATH as DRIVER_DB_PATH
from utils.expiry_status import get_expiry_status

# إنشاء راوتر الموديول (Blueprint)
reports_bp = Blueprint(
    'reports',
    __name__,
    template_folder='views',
    url_prefix='/reports'
)


@reports_bp.app_context_processor
def inject_report_approval_token():
    return {'approval_token': uuid.uuid4().hex}

# استدعاء متحكم التقارير
controller = ReportsController()

DATA_REPORT_LABELS = {
    'employees': {
        'id': 'رقم الموظف', 'full_name': 'الاسم الكامل', 'national_id': 'رقم الهوية',
        'nationality': 'الجنسية', 'phone': 'رقم الهاتف', 'job_title': 'الصفة الوظيفية',
        'qualification': 'المؤهل', 'specialization': 'التخصص',
        'license_number': 'رقم الرخصة', 'license_type': 'نوع الرخصة',
        'license_issue_date': 'تاريخ إصدار الرخصة', 'license_expiry_date': 'تاريخ انتهاء الرخصة',
        'license_status': 'حالة الرخصة'
    },
    'insurance': {
        'id': 'رقم السجل', 'policy_number': 'رقم البوليصة', 'vehicle_plate': 'رقم اللوحة',
        'insurance_company': 'شركة التأمين', 'insurance_type': 'نوع التأمين',
        'start_date': 'تاريخ البدء', 'end_date': 'تاريخ الانتهاء',
        'policy_cost': 'التكلفة (ر.س)', 'description': 'الوصف',
        'policy_attachment': 'المرفق', 'status': 'الحالة بالنظام', 'status_type': 'حالة التأمين',
        'created_at': 'تاريخ التسجيل'
    },
    'inspections': {
        'id': 'رقم السجل', 'vehicle_plate': 'رقم اللوحة', 'inspection_center': 'مركز الفحص',
        'inspection_date': 'تاريخ الفحص', 'expiry_date': 'تاريخ الانتهاء',
        'result_status': 'نتيجة الفحص', 'inspection_cost': 'التكلفة (ر.س)',
        'attachment': 'المرفق', 'notes': 'ملاحظات', 'status': 'الحالة بالنظام',
        'status_type': 'حالة الفحص', 'created_at': 'تاريخ التسجيل'
    },
    'violations': {
        'id': 'رقم السجل', 'violation_number': 'رقم المخالفة', 'vehicle_plate': 'المركبة',
        'driver_name': 'السائق', 'violation_type': 'نوع المخالفة', 'issuer': 'جهة الإصدار',
        'location': 'الموقع', 'violation_datetime': 'تاريخ ووقت المخالفة',
        'fine_amount': 'قيمة الغرامة (ر.س)', 'description': 'الوصف',
        'violation_attachment': 'مرفق المخالفة', 'status': 'الحالة بالنظام',
        'status_type': 'حالة المخالفة', 'payment_date': 'تاريخ السداد',
        'payment_receipt': 'رقم إيصال السداد', 'payment_amount': 'مبلغ السداد',
        'payment_notes': 'ملاحظات السداد', 'payment_attachment': 'مرفق السداد',
        'closed_at': 'تاريخ الإقفال', 'closure_reason': 'سبب الإقفال',
        'closure_notes': 'ملاحظات الإقفال'
    }
}


def _data_report_columns(category, column_names):
    labels = DATA_REPORT_LABELS[category]
    return [{'key': name, 'label': labels.get(name, name.replace('_', ' '))} for name in column_names]


def _data_report_context(category, params):
    if category not in DATA_REPORT_LABELS:
        raise ValueError('نوع التقرير غير صالح')

    report_type = params.get('report_type', 'all')
    allowed_types = {
        'employees': {'all', 'single'},
        'insurance': {'all', 'active', 'expired', 'near_expiry', 'single'},
        'inspections': {'all', 'active', 'expired', 'near_expiry', 'single'},
        'violations': {'all', 'vehicle', 'driver', 'month', 'year', 'range', 'single'}
    }
    if report_type not in allowed_types[category]:
        raise ValueError('قيمة الفلتر غير صالحة')

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        if category == 'employees':
            table_columns = [row['name'] for row in conn.execute('PRAGMA table_info(team_members)')]
            custom_labels = {
                row['name']: row['label'] for row in conn.execute(
                    "SELECT name, label FROM team_fields"
                )
            } if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'team_fields'"
            ).fetchone() else {}
            rows = conn.execute(
                'SELECT * FROM team_members WHERE id = ?' if report_type == 'single'
                else 'SELECT * FROM team_members ORDER BY full_name',
                (params.get('member_id'),) if report_type == 'single' else ()
            ).fetchall()
            records = [_row_to_dict(row) for row in rows]
            if 'license_expiry_date' in table_columns:
                for record in records:
                    record['license_status'] = get_expiry_status(
                        record.get('license_expiry_date'), 'ساري', 'قارب على الانتهاء', 'منتهية'
                    )
            columns = [
                {'key': name, 'label': custom_labels.get(name) or DATA_REPORT_LABELS['employees'].get(name, name)}
                for name in table_columns
            ]
            title = (
                f"تقرير الموظف: {records[0].get('full_name') or ''}"
                if report_type == 'single' and records else 'تقرير جميع الموظفين وفريق العمل'
            )
        elif category == 'insurance':
            table_columns = [row['name'] for row in conn.execute('PRAGMA table_info(insurance_policies)')]
            records = [_row_to_dict(row) for row in conn.execute(
                'SELECT * FROM insurance_policies ORDER BY id DESC'
            ).fetchall()]
            for record in records:
                state = get_expiry_status(record.get('end_date'), 'ساري', 'قارب على الانتهاء', 'منتهية')
                if record.get('status') == 'expired' or state == 'منتهية':
                    state = 'منتهية'
                record['status_type'] = state
            if report_type == 'single':
                records = [record for record in records if str(record.get('id')) == str(params.get('policy_id'))]
            elif report_type == 'active':
                records = [record for record in records if record['status_type'] == 'ساري']
            elif report_type == 'expired':
                records = [record for record in records if record['status_type'] == 'منتهية']
            elif report_type == 'near_expiry':
                records = [record for record in records if record['status_type'] == 'قارب على الانتهاء']
            labels = {
                'all': 'جميع التأمينات', 'active': 'التأمينات السارية',
                'expired': 'التأمينات المنتهية', 'near_expiry': 'التأمينات المقاربة على الانتهاء'
            }
            title = (
                f"تقرير تأمين المركبة: {records[0].get('vehicle_plate') or ''}"
                if report_type == 'single' and records else labels.get(report_type, 'تقرير التأمينات')
            )
            if 'status_type' not in table_columns:
                table_columns.append('status_type')
            columns = _data_report_columns('insurance', table_columns)
        elif category == 'inspections':
            table_columns = [row['name'] for row in conn.execute('PRAGMA table_info(inspections)')]
            records = [_row_to_dict(row) for row in conn.execute(
                'SELECT * FROM inspections ORDER BY id DESC'
            ).fetchall()]
            for record in records:
                passed = record.get('result_status') in ('ناجح', 'Pass', 'pass')
                state = get_expiry_status(
                    record.get('expiry_date'), 'ساري', 'قارب على الانتهاء', 'منتهي'
                ) if passed else 'منتهي'
                record['status_type'] = state
            if report_type == 'single':
                records = [record for record in records if str(record.get('id')) == str(params.get('inspection_id'))]
            elif report_type in {'active', 'expired', 'near_expiry'}:
                wanted = {'active': 'ساري', 'expired': 'منتهي', 'near_expiry': 'قارب على الانتهاء'}[report_type]
                records = [record for record in records if record['status_type'] == wanted]
            labels = {
                'all': 'جميع سجلات الفحص الدوري', 'active': 'الفحوصات السارية',
                'expired': 'الفحوصات المنتهية', 'near_expiry': 'الفحوصات المقاربة على الانتهاء'
            }
            title = (
                f"تقرير الفحص الدوري للمركبة: {records[0].get('vehicle_plate') or ''}"
                if report_type == 'single' and records else labels.get(report_type, 'تقرير الفحص الدوري')
            )
            if 'status_type' not in table_columns:
                table_columns.append('status_type')
            columns = _data_report_columns('inspections', table_columns)
        else:
            allowed_types = {'all', 'vehicle', 'driver', 'month', 'year', 'range', 'single'}
            if report_type not in allowed_types:
                raise ValueError('نوع فلتر المخالفات غير صالح')
            query = 'SELECT * FROM violations'
            conditions = []
            values = []
            if report_type == 'vehicle':
                conditions.append('vehicle_plate = ?')
                values.append(params.get('vehicle_plate', ''))
            elif report_type == 'driver':
                conditions.append('driver_name = ?')
                values.append(params.get('driver_name', ''))
            elif report_type == 'month':
                conditions.append('violation_datetime LIKE ?')
                values.append(f"{params.get('month', '')}%")
            elif report_type == 'year':
                conditions.append('violation_datetime LIKE ?')
                values.append(f"{params.get('year', '')}%")
            elif report_type == 'range':
                if params.get('date_from'):
                    conditions.append('date(violation_datetime) >= date(?)')
                    values.append(params['date_from'])
                if params.get('date_to'):
                    conditions.append('date(violation_datetime) <= date(?)')
                    values.append(params['date_to'])
            elif report_type == 'single':
                conditions.append('id = ?')
                values.append(params.get('violation_id'))
            if conditions:
                query += ' WHERE ' + ' AND '.join(conditions)
            query += ' ORDER BY id DESC'
            records = [_row_to_dict(row) for row in conn.execute(query, values).fetchall()]
            table_columns = [row['name'] for row in conn.execute('PRAGMA table_info(violations)')]
            if report_type == 'single' and records:
                title = f"تقرير المخالفة رقم {records[0].get('violation_number') or records[0].get('id')}"
            else:
                title = {
                    'all': 'تقرير جميع المخالفات المرورية',
                    'vehicle': f"تقرير مخالفات المركبة {params.get('vehicle_plate', '')}",
                    'driver': f"تقرير مخالفات السائق {params.get('driver_name', '')}",
                    'month': f"تقرير المخالفات لشهر {params.get('month', '')}",
                    'year': f"تقرير المخالفات لعام {params.get('year', '')}",
                    'range': f"تقرير المخالفات من {params.get('date_from', '...')} إلى {params.get('date_to', '...')}"
                }.get(report_type, 'تقرير المخالفات المرورية')
            columns = _data_report_columns('violations', table_columns)
    finally:
        conn.close()

    return records, columns, title


def _fetch_accidents(params):
    sql = "SELECT * FROM accidents WHERE 1=1"
    query_params = []
    report_type = params.get('report_type', 'total')

    if report_type == 'single' and params.get('accident_id'):
        accident_id = params['accident_id'].strip()
        sql += " AND (id = ? OR accident_number = ?)"
        query_params.extend([accident_id, accident_id])
    elif report_type == 'total':
        filter_type = params.get('filter_type', 'all')
        if filter_type == 'daily' and params.get('daily_date'):
            sql += " AND accident_datetime LIKE ?"
            query_params.append(f"{params['daily_date']}%")
        elif filter_type == 'month' and params.get('month'):
            sql += " AND accident_datetime LIKE ?"
            query_params.append(f"{params['month']}%")
        elif filter_type == 'year' and params.get('year'):
            sql += " AND accident_datetime LIKE ?"
            query_params.append(f"{params['year']}%")
        elif filter_type == 'range':
            if params.get('date_from'):
                sql += " AND accident_datetime >= ?"
                query_params.append(params['date_from'])
            if params.get('date_to'):
                sql += " AND accident_datetime <= ?"
                query_params.append(f"{params['date_to']} 23:59:59")

    sql += " ORDER BY id DESC"
    db = Database()
    try:
        accidents = db.fetch_all(sql, tuple(query_params))
    finally:
        db.close()
    return [_row_to_dict(row) for row in (accidents or [])]


def _accident_report_title(params):
    if params.get('report_type') == 'single':
        return 'تقرير حادث سير'
    filter_type = params.get('filter_type', 'all')
    if filter_type == 'daily' and params.get('daily_date'):
        return f"تقرير حوادث يوم {params['daily_date']}"
    if filter_type == 'month' and params.get('month'):
        year, _, month = params['month'].partition('-')
        month_names = ['يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو',
                       'يوليو', 'أغسطس', 'سبتمبر', 'أكتوبر', 'نوفمبر', 'ديسمبر']
        month_label = month_names[int(month) - 1] if month.isdigit() and 1 <= int(month) <= 12 else month
        return f"تقرير حوادث شهر {month_label} {year}".strip()
    if filter_type == 'year' and params.get('year'):
        return f"تقرير حوادث سنة {params['year']}"
    if filter_type == 'range':
        return f"تقرير الحوادث من {params.get('date_from') or '...'} إلى {params.get('date_to') or '...'}"
    return 'تقرير الحوادث المرورية'


def _lookup_approved_report(item_id=None, doc_type='accidents_report', approval_token=None):
    if not approval_token:
        return None, None
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            'SELECT doc_number FROM approved_documents '
            'WHERE approval_token = ? AND doc_type = ? AND item_id = ?',
            (approval_token, doc_type, str(item_id))
        ).fetchone()
        if row:
            qr_filename = f"qr_{row[0].replace('.', '_').replace('-', '_')}.png"
            return row[0], f"/static/uploads/qrcodes/{qr_filename}"
    except sqlite3.Error:
        pass
    finally:
        if conn is not None:
            conn.close()
    return None, None


def _maintenance_filters(params):
    valid_types = {'all', *MAINTENANCE_TYPE_TITLES.keys()}
    valid_statuses = {'all', 'open', 'closed'}
    return {
        'type': params.get('type') if params.get('type') in valid_types else 'all',
        'status': params.get('status') if params.get('status') in valid_statuses else 'all',
        'date_from': params.get('date_from', '').strip(),
        'date_to': params.get('date_to', '').strip()
    }


def _maintenance_orders(filters=None, order_id=None):
    if order_id is not None:
        order = MaintenanceService.get_order_by_id(order_id)
        orders = [order] if order else []
    else:
        filters = filters or _maintenance_filters({})
        orders = MaintenanceService.get_all_orders(
            m_type=filters['type'], status=filters['status'],
            date_from=filters['date_from'], date_to=filters['date_to']
        )
    MaintenanceController._enrich_orders(orders)
    return orders


def _maintenance_report_title(orders, filters, order_id=None):
    if order_id is not None:
        order = orders[0] if orders else {}
        return f"تقرير أمر صيانة {order.get('order_no') or order.get('id') or order_id}"
    type_title = MAINTENANCE_TYPE_TITLES.get(filters['type'], 'جميع أنواع الصيانة')
    status_title = {'open': 'المفتوحة', 'closed': 'المغلقة المؤرشفة', 'all': 'المفتوحة والمغلقة'}[filters['status']]
    title = f"تقرير {type_title} {status_title}"
    if filters['date_from'] or filters['date_to']:
        title += f" من {filters['date_from'] or '...'} إلى {filters['date_to'] or '...'}"
    return title


def _maintenance_approval_identity(filters, order_id=None):
    if order_id is not None:
        return 'maintenance_order', str(order_id)
    return 'maintenance_report', json.dumps(filters, sort_keys=True, ensure_ascii=False)


DRIVER_FIELD_LABELS = {
    'id': 'رقم السائق', 'name': 'اسم السائق', 'national_id': 'رقم الهوية',
    'phone': 'رقم الجوال', 'nationality': 'الجنسية', 'job_title': 'الصفة الوظيفية',
    'department': 'القسم التابع له', 'license_number': 'رقم الرخصة',
    'license_type': 'نوع الرخصة', 'restrictions_count': 'عدد القيود',
    'license_issue_date': 'تاريخ إصدار الرخصة', 'license_expiry_date': 'تاريخ انتهاء الرخصة'
}
VEHICLE_FIELD_LABELS = {
    'id': 'رقم المركبة', 'plate_number': 'رقم اللوحة', 'vehicle_code': 'كود المركبة',
    'vehicle_type': 'نوع المركبة', 'model': 'الموديل', 'manufacturer': 'الشركة المصنعة',
    'color': 'اللون', 'fuel_type': 'نوع الوقود', 'engine_number': 'رقم المحرك',
    'chassis_number': 'رقم الهيكل', 'status': 'حالة العهدة', 'workshop_status': 'حالة المركبة في الورشة',
    'ownership': 'الملكية'
}

INSPECTION_REPORT_LABELS = DATA_REPORT_LABELS['inspections']


def _vehicle_report_filters(params):
    return {
        key: str(params.get(key, '') or '').strip()
        for key in ('manufacturer', 'model', 'vehicle_type', 'status', 'ownership', 'fuel_type')
    }


def _vehicle_report_options():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        columns = {row['name'] for row in conn.execute('PRAGMA table_info(vehicles)')}
        options = {}
        for field in ('manufacturer', 'model', 'vehicle_type', 'status', 'ownership', 'fuel_type'):
            if field not in columns:
                options[field] = []
                continue
            options[field] = [
                row[0] for row in conn.execute(
                    f'SELECT DISTINCT "{field}" FROM vehicles '
                    f'WHERE "{field}" IS NOT NULL AND "{field}" != \'\' ORDER BY "{field}"'
                ).fetchall()
            ]
        return options
    finally:
        conn.close()


def _vehicle_report_data(filters=None, vehicle_id=None):
    filters = filters or _vehicle_report_filters({})
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        vehicles = [dict(row) for row in conn.execute(
            'SELECT * FROM vehicles ORDER BY vehicle_code, plate_number'
        ).fetchall()]
        handover_table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'handovers'"
        ).fetchone() is not None
        active_handovers = [dict(row) for row in conn.execute(
            "SELECT * FROM handovers WHERE status = 'نشط' ORDER BY id DESC"
        ).fetchall()] if handover_table_exists else []
        policies = [dict(row) for row in conn.execute(
            'SELECT * FROM insurance_policies ORDER BY id DESC'
        ).fetchall()] if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'insurance_policies'"
        ).fetchone() else []
        inspections = [dict(row) for row in conn.execute(
            'SELECT * FROM inspections ORDER BY id DESC'
        ).fetchall()] if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'inspections'"
        ).fetchone() else []
        driver_columns = {
            row['name'] for row in conn.execute('PRAGMA table_info(drivers)')
        } if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'drivers'"
        ).fetchone() else set()
        drivers = [dict(row) for row in conn.execute(
            'SELECT * FROM drivers'
        ).fetchall()] if driver_columns else []
        vehicle_columns = [row['name'] for row in conn.execute('PRAGMA table_info(vehicles)')]
        inspection_columns = [
            row['name'] for row in conn.execute('PRAGMA table_info(inspections)')
        ] if inspections or conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'inspections'"
        ).fetchone() else []
        policy_columns = [
            row['name'] for row in conn.execute('PRAGMA table_info(insurance_policies)')
        ] if policies or conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'insurance_policies'"
        ).fetchone() else []
    finally:
        conn.close()

    def matches_handover(vehicle, handover):
        if handover.get('vehicle_id') is not None and str(handover['vehicle_id']) == str(vehicle.get('id')):
            return True
        info = str(handover.get('vehicle_info') or '').strip()
        return bool(info) and info in {
            str(vehicle.get('vehicle_code') or '').strip(),
            str(vehicle.get('plate_number') or '').strip(),
            f"{vehicle.get('vehicle_code') or ''} - {vehicle.get('plate_number') or ''}".strip(' -')
        }

    result = []
    for vehicle in vehicles:
        if vehicle_id is not None and str(vehicle.get('id')) != str(vehicle_id):
            continue
        if any(
            filters.get(key) and str(vehicle.get(key) or '') != filters[key]
            for key in filters if key != 'status'
        ):
            continue

        status = vehicle.get('status') or 'متاحة'
        active_handover = next(
            (handover for handover in active_handovers if matches_handover(vehicle, handover)),
            None
        )
        is_assigned = status == 'مسلمة' or active_handover is not None
        vehicle['status'] = 'مسلمة' if is_assigned else status
        if filters.get('status') and str(vehicle['status']) != filters['status']:
            continue
        driver = None
        if is_assigned and active_handover:
            driver_name = str(active_handover.get('driver_info') or '').strip()
            driver = next(
                (item for item in drivers if str(item.get('name') or '').strip() == driver_name),
                {'name': driver_name} if driver_name else None
            )
        vehicle['custody_status'] = 'مسلمة' if is_assigned else 'في الورشة'
        vehicle['workshop_status'] = vehicle.get('workshop_status') or 'متاحة'
        for policy in policies:
            if str(policy.get('vehicle_plate') or '').strip() == str(vehicle.get('plate_number') or '').strip():
                policy['status_type'] = get_expiry_status(
                    policy.get('end_date'), 'ساري', 'قارب على الانتهاء', 'منتهية'
                )
        related_policies = [
            policy for policy in policies
            if str(policy.get('vehicle_plate') or '').strip() == str(vehicle.get('plate_number') or '').strip()
        ]
        related_inspections = []
        for inspection in inspections:
            if str(inspection.get('vehicle_plate') or '').strip() != str(vehicle.get('plate_number') or '').strip():
                continue
            is_passed = inspection.get('result_status') in ('ناجح', 'Pass', 'pass')
            inspection['status_type'] = (
                get_expiry_status(inspection.get('expiry_date'), 'ساري', 'قارب على الانتهاء', 'منتهي')
                if is_passed else 'منتهي'
            )
            related_inspections.append(inspection)
        result.append({
            'vehicle': vehicle,
            'driver': driver,
            'is_assigned': is_assigned,
            'policies': related_policies,
            'inspections': related_inspections
        })

    vehicle_fields = [
        {'key': name, 'label': VEHICLE_FIELD_LABELS.get(name, name.replace('_', ' '))}
        for name in vehicle_columns
    ]
    inspection_fields = [
        {'key': name, 'label': INSPECTION_REPORT_LABELS.get(name, name.replace('_', ' '))}
        for name in inspection_columns
    ]
    if 'status_type' not in inspection_columns:
        inspection_fields.append({'key': 'status_type', 'label': 'حالة الفحص'})
    policy_fields = [
        {'key': name, 'label': DATA_REPORT_LABELS['insurance'].get(name, name.replace('_', ' '))}
        for name in policy_columns
    ]
    if 'status_type' not in policy_columns:
        policy_fields.append({'key': 'status_type', 'label': 'حالة التأمين'})
    driver_fields = [
        {'key': name, 'label': DRIVER_FIELD_LABELS.get(name, name.replace('_', ' '))}
        for name in driver_columns
    ]
    title = (
        f"بيانات المركبة {result[0]['vehicle'].get('vehicle_code') or ''} "
        f"— رقم اللوحة {result[0]['vehicle'].get('plate_number') or ''}"
        if vehicle_id is not None and result else 'تقرير المعدات والمركبات'
    )
    return result, vehicle_fields, inspection_fields, policy_fields, driver_fields, title


HANDOVER_REPORT_LABELS = {
    'id': 'رقم الحركة',
    'handover_type': 'نوع العملية',
    'vehicle_id': 'رقم المركبة',
    'vehicle_info': 'المركبة / المعدة',
    'driver_info': 'السائق',
    'handover_date': 'تاريخ ووقت الحركة',
    'purpose': 'الغرض',
    'department': 'القسم التابع له',
    'description': 'الوصف',
    'odometer': 'العداد',
    'fuel_level': 'الوقود',
    'body_condition': 'حالة الهيكل',
    'interior_condition': 'حالة الداخلية',
    'tires_condition': 'حالة الإطارات',
    'mechanical_condition': 'الحالة الميكانيكية',
    'electrical_condition': 'الحالة الكهربائية',
    'electrical_technician': 'فني الكهرباء',
    'mechanical_technician': 'فني الميكانيكا',
    'notes': 'ملاحظات',
    'status': 'حالة الحركة'
}


def _handover_report_context(params, document=False):
    report_type = params.get('report_type', 'all')
    if document:
        if not str(params.get('handover_id', '')).isdigit():
            raise ValueError('رقم حركة الاستلام والتسليم غير صالح')
        report_type = 'single'
    elif report_type not in {'all', 'delivery', 'return', 'active', 'single'}:
        raise ValueError('نوع تقرير الاستلام والتسليم غير صالح')

    period = params.get('period', 'all')
    if period not in {'all', 'today', 'month', 'year', 'range'}:
        raise ValueError('فترة التقرير غير صالحة')
    movement_type = params.get('movement_type', 'all')
    if movement_type not in {'all', 'تسليم عهدة', 'إرجاع عهدة'}:
        raise ValueError('نوع حركة الاستلام والتسليم غير صالح')
    handover_id = str(params.get('handover_id') or params.get('record_id') or '').strip()
    if report_type == 'single' and not handover_id.isdigit():
        raise ValueError('اختر حركة صحيحة للتقرير')
    date_from = str(params.get('date_from') or '').strip()
    date_to = str(params.get('date_to') or '').strip()
    if period == 'range':
        for value in (date_from, date_to):
            if value:
                datetime.strptime(value, '%Y-%m-%d')
        if not date_from and not date_to:
            raise ValueError('حدد تاريخ بداية أو نهاية للفترة')
        if date_from and date_to and date_from > date_to:
            raise ValueError('تاريخ بداية الفترة يجب أن يسبق تاريخ نهايتها')

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'handovers'"
        ).fetchone()
        if not table_exists:
            return [], [], 'تقرير حركات الاستلام والتسليم'
        rows = [dict(row) for row in conn.execute(
            'SELECT * FROM handovers ORDER BY handover_date DESC, id DESC'
        ).fetchall()]
        columns_in_table = [
            row['name'] for row in conn.execute('PRAGMA table_info(handovers)')
        ]
    finally:
        conn.close()

    today = datetime.now().strftime('%Y-%m-%d')
    filtered_rows = []
    for record in rows:
        record_date = str(record.get('handover_date') or '').replace('T', ' ').strip()[:10]
        if report_type == 'single' and str(record.get('id')) != handover_id:
            continue
        if report_type == 'delivery' and record.get('handover_type') != 'تسليم عهدة':
            continue
        if report_type == 'return' and record.get('handover_type') != 'إرجاع عهدة':
            continue
        if report_type == 'active' and record.get('status') != 'نشط':
            continue
        if movement_type != 'all' and record.get('handover_type') != movement_type:
            continue
        if period == 'today' and record_date != today:
            continue
        if period == 'month' and not record_date.startswith(today[:7]):
            continue
        if period == 'year' and not record_date.startswith(today[:4]):
            continue
        if period == 'range' and (
            (date_from and record_date < date_from)
            or (date_to and record_date > date_to)
        ):
            continue
        if document and record.get('handover_type') != 'تسليم عهدة':
            raise ValueError('وثيقة التوثيق متاحة لحركات تسليم العهدة فقط')
        filtered_rows.append(record)

    if report_type == 'single' or document:
        title = 'وثيقة تسليم مركبة / معدة' if document else 'تقرير حركة استلام وتسليم محددة'
    else:
        title_by_type = {
            'all': 'جميع حركات الاستلام والتسليم',
            'delivery': 'حركات تسليم العهدة',
            'return': 'حركات إرجاع العهدة',
            'active': 'حركات التسليم النشطة'
        }
        title = title_by_type[report_type]
    columns = [
        {'key': name, 'label': HANDOVER_REPORT_LABELS.get(name, name.replace('_', ' '))}
        for name in columns_in_table if name in HANDOVER_REPORT_LABELS
    ]
    return filtered_rows, columns, title


def _driver_report_fields():
    conn = sqlite3.connect(DRIVER_DB_PATH)
    try:
        driver_columns = [row[1] for row in conn.execute('PRAGMA table_info(drivers)')]
        vehicle_columns = [row[1] for row in conn.execute('PRAGMA table_info(vehicles)')]
    finally:
        conn.close()
    return (
        [{'key': f'driver:{column}', 'label': DRIVER_FIELD_LABELS.get(column, column)} for column in driver_columns],
        [{'key': f'vehicle:{column}', 'label': VEHICLE_FIELD_LABELS.get(column, column)} for column in vehicle_columns]
    )


def _driver_report_data(report_type, requested_fields=None, driver_id=None):
    driver_fields, vehicle_fields = _driver_report_fields()
    allowed_fields = {field['key']: field for field in driver_fields + vehicle_fields}
    selected = [allowed_fields[key] for key in (requested_fields or []) if key in allowed_fields]
    if not selected:
        selected = driver_fields + (vehicle_fields if report_type == 'assigned' else [])

    conn = sqlite3.connect(DRIVER_DB_PATH)
    try:
        conn.row_factory = sqlite3.Row
        has_handovers = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'handovers'"
        ).fetchone() is not None
        if report_type == 'single':
            driver = conn.execute('SELECT * FROM drivers WHERE id = ?', (driver_id,)).fetchone()
            if not driver:
                return [], selected
            records = [(dict(driver), None)]
        else:
            drivers = [dict(row) for row in conn.execute('SELECT * FROM drivers ORDER BY name').fetchall()]
            if report_type == 'all':
                records = [(driver, None) for driver in drivers]
            elif report_type == 'unassigned':
                handovers = conn.execute(
                    "SELECT driver_info FROM handovers WHERE status = 'نشط'"
                ).fetchall() if has_handovers else []
                assigned_names = {str(row['driver_info'] or '').strip() for row in handovers}
                records = [(driver, None) for driver in drivers if driver.get('name') not in assigned_names]
            elif report_type == 'assigned':
                vehicles = [dict(row) for row in conn.execute('SELECT * FROM vehicles').fetchall()]
                vehicles_by_id = {str(vehicle.get('id')): vehicle for vehicle in vehicles}
                handovers = conn.execute(
                    "SELECT * FROM handovers WHERE status = 'نشط' ORDER BY id DESC"
                ).fetchall() if has_handovers else []
                drivers_by_name = {str(driver.get('name') or '').strip(): driver for driver in drivers}
                records = []
                used_vehicle_ids = set()
                for handover in handovers:
                    driver = drivers_by_name.get(str(handover['driver_info'] or '').strip())
                    if not driver:
                        continue
                    vehicle = vehicles_by_id.get(str(handover['vehicle_id'])) if handover['vehicle_id'] is not None else None
                    info = str(handover['vehicle_info'] or '').strip()
                    if not vehicle:
                        vehicle = next(
                            (item for item in vehicles if info in {
                                str(item.get('plate_number') or '').strip(),
                                str(item.get('vehicle_code') or '').strip(),
                                f"{item.get('vehicle_code') or ''} - {item.get('plate_number') or ''}".strip(' -')
                            }),
                            None
                        )
                    if vehicle and str(vehicle.get('id')) not in used_vehicle_ids:
                        records.append((driver, vehicle))
                        used_vehicle_ids.add(str(vehicle.get('id')))
            else:
                return [], selected
    finally:
        conn.close()

    rows = []
    for driver, vehicle in records:
        row = {}
        for field in selected:
            prefix, column = field['key'].split(':', 1)
            source = driver if prefix == 'driver' else (vehicle or {})
            row[field['key']] = source.get(column, '—') or '—'
        rows.append(row)
    return rows, selected


@reports_bp.route('/', methods=['GET'])
def index():
    """شاشة مركز التقارير الرئيسية واستعراض النماذج المتاحة"""
    templates = controller.get_active_templates()
    return render_template('report_index.html', templates=templates)


@reports_bp.route('/preview/<template_key>', methods=['GET', 'POST'])
def preview(template_key):
    """شاشة معاينة وطباعة التقرير بناءً على البيانات والقالب المختار"""
    params = request.args.to_dict() if request.method == 'GET' else request.form.to_dict()
    report_data = controller.generate_report_context(template_key, params)
    
    # ضمان وجود متغير الاتجاه
    orientation = params.get('orientation', 'portrait')
    report_data['context'].setdefault('orientation', orientation)
    
    return render_template(
        f"templates_store/{report_data['template_path']}", 
        **report_data['context']
    )


@reports_bp.route('/api/generate', methods=['POST'])
def api_generate():
    """واجهة برمجة (API) لتوليد التقرير ورقم المستند والـ QR وحفظهما أوفلاين"""
    data = request.get_json() or {}
    result = controller.create_and_save_report(
        template_key=data.get('template_key'),
        params=data.get('params', {})
    )
    return jsonify(result)


@reports_bp.route('/drivers', methods=['GET'])
def drivers_reports():
    report_type = request.args.get('report_type', '').strip()
    valid_types = {'all', 'assigned', 'unassigned', 'single'}
    if report_type not in valid_types:
        return render_template('drivers_report_options.html')

    driver_fields, vehicle_fields = _driver_report_fields()
    if report_type == 'assigned' and request.args.get('view') != 'print':
        return render_template(
            'drivers_report_fields.html',
            driver_fields=driver_fields,
            vehicle_fields=vehicle_fields
        )

    driver_id = request.args.get('driver_id', type=int) if report_type == 'single' else None
    if report_type == 'single' and driver_id is None:
        return "<h3>رقم السائق غير صالح.</h3>", 400

    requested_fields = (
        request.args.getlist('field') or request.args.getlist('fields')
        if report_type == 'assigned' else None
    )
    rows, columns = _driver_report_data(report_type, requested_fields, driver_id)
    doc_type = 'driver_single_report' if report_type == 'single' else 'drivers_report'
    item_id = str(driver_id) if report_type == 'single' else json.dumps(
        {'report_type': report_type, 'fields': [column['key'] for column in columns]},
        sort_keys=True, ensure_ascii=False
    )
    document_number, qr_code_url = _lookup_approved_report(item_id, doc_type)
    titles = {
        'all': 'تقرير جميع السائقين',
        'assigned': 'تقرير السائقين المستلمين للمركبات',
        'unassigned': 'تقرير السائقين غير المستلمين للمركبات',
        'single': 'تقرير بيانات السائق'
    }
    title = titles[report_type]
    if report_type == 'single' and rows:
        title = f"تقرير السائق: {rows[0].get('driver:name', '')}"
    return render_template(
        'drivers_report_print.html',
        rows=rows,
        columns=columns,
        report_title_text=title,
        report_date_gregorian=datetime.now().strftime('%Y/%m/%d'),
        report_date_hijri='1448/04/24',
        document_number=document_number or 'No.000000',
        qr_code_url=qr_code_url,
        hide_approve=(not rows or bool(document_number)),
        approval_doc_type=doc_type,
        approval_item_id=item_id,
        orientation='landscape',
        allow_orientation=False,
        report_type=report_type
    )


@reports_bp.route('/vehicles', methods=['GET'])
def vehicle_reports():
    report_type = request.args.get('report_type', 'all').strip()
    if report_type not in {'all', 'single'}:
        abort(400, description='نوع تقرير المركبات غير صالح')
    filters = _vehicle_report_filters(request.args)

    if request.args.get('view') != 'print':
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            vehicles = [dict(row) for row in conn.execute(
                'SELECT id, vehicle_code, plate_number FROM vehicles ORDER BY vehicle_code, plate_number'
            ).fetchall()]
        finally:
            conn.close()
        return render_template(
            'vehicle_report_options.html',
            options=_vehicle_report_options(),
            vehicles=vehicles,
            filters=filters
        )

    vehicle_id = request.args.get('vehicle_id', '').strip() if report_type == 'single' else None
    if report_type == 'single' and not vehicle_id:
        abort(400, description='اختر مركبة للتقرير')
    report_data, vehicle_fields, inspection_fields, policy_fields, driver_fields, title = (
        _vehicle_report_data(filters, vehicle_id)
    )
    report_identity = {
        'report_type': report_type,
        'vehicle_id': vehicle_id,
        'filters': filters
    }
    item_id = json.dumps(report_identity, sort_keys=True, ensure_ascii=False)
    document_number, qr_code_url = _lookup_approved_report(item_id, 'vehicles_report')
    return render_template(
        'vehicle_report_print.html',
        report_data=report_data,
        vehicle_fields=vehicle_fields,
        inspection_fields=inspection_fields,
        policy_fields=policy_fields,
        driver_fields=driver_fields,
        report_title_text=title,
        report_date_gregorian=datetime.now().strftime('%Y/%m/%d'),
        report_date_hijri='1448/04/24',
        document_number=document_number or 'No.000000',
        qr_code_url=qr_code_url,
        hide_approve=(not report_data or bool(document_number)),
        approval_doc_type='vehicles_report',
        approval_item_id=item_id,
        orientation='landscape',
        allow_orientation=False,
        report_type=report_type,
        filters=filters
    )


@reports_bp.route('/vehicles/<int:vehicle_id>/status', methods=['POST'])
def update_vehicle_report_status(vehicle_id):
    requested_status = request.form.get('workshop_status', '').strip()
    if requested_status not in {'متاحة', 'تحت الصيانة'}:
        abort(400, description='حالة المركبة غير صالحة')

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('BEGIN IMMEDIATE')
        vehicle_row = conn.execute(
            'SELECT * FROM vehicles WHERE id = ?', (vehicle_id,)
        ).fetchone()
        if not vehicle_row:
            abort(404, description='المركبة غير موجودة')
        vehicle = dict(vehicle_row)
        tables = {
            row['name'] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        active_handovers = conn.execute(
            "SELECT vehicle_id, vehicle_info FROM handovers WHERE status = 'نشط'"
        ).fetchall() if 'handovers' in tables else []
        vehicle_info = f"{vehicle.get('vehicle_code') or ''} - {vehicle.get('plate_number') or ''}".strip(' -')
        assigned = vehicle.get('status') == 'مسلمة' or any(
            str(row['vehicle_id']) == str(vehicle_id)
            if row['vehicle_id'] is not None
            else str(row['vehicle_info'] or '').strip() in {
                str(vehicle.get('vehicle_code') or '').strip(),
                str(vehicle.get('plate_number') or '').strip(),
                vehicle_info
            }
            for row in active_handovers
        )
        if assigned:
            abort(409, description='لا يمكن تغيير حالة مركبة مسلّمة لسائق')
        conn.execute(
            'UPDATE vehicles SET workshop_status = ? WHERE id = ?',
            (requested_status, vehicle_id)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    report_type = request.form.get('report_type', 'all')
    redirect_params = {'view': 'print', 'report_type': report_type}
    if report_type == 'single':
        redirect_params['vehicle_id'] = vehicle_id
    redirect_params.update(_vehicle_report_filters(request.form))
    return redirect(url_for('reports.vehicle_reports', **redirect_params))


@reports_bp.route('/handovers', methods=['GET'])
def handover_reports():
    view = request.args.get('view', '').strip()
    params = {
        'report_type': request.args.get('report_type', 'all').strip(),
        'movement_type': request.args.get('movement_type', 'all').strip(),
        'period': request.args.get('period', 'all').strip(),
        'date_from': request.args.get('date_from', '').strip(),
        'date_to': request.args.get('date_to', '').strip(),
        'handover_id': request.args.get('handover_id', request.args.get('record_id', '')).strip()
    }
    if view not in {'print', 'document'}:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            options = [dict(row) for row in conn.execute(
                'SELECT id, handover_type, vehicle_info, driver_info, handover_date '
                'FROM handovers ORDER BY handover_date DESC, id DESC'
            ).fetchall()]
        finally:
            conn.close()
        return render_template('handover_report_options.html', options=options)

    is_document = view == 'document'
    try:
        records, columns, title = _handover_report_context(params, document=is_document)
    except (ValueError, sqlite3.Error) as error:
        abort(400, description=str(error))
    if not records:
        abort(404, description='لا توجد حركة استلام وتسليم مطابقة')

    doc_type = 'handover_document' if is_document else 'handover_report'
    item_id = params['handover_id'] if is_document else json.dumps(
        params, sort_keys=True, ensure_ascii=False
    )
    document_number, qr_code_url = _lookup_approved_report(item_id, doc_type)
    return render_template(
        'handover_report_print.html',
        records=records,
        columns=columns,
        report_title_text='وثيقة تسليم مركبة / معدة' if is_document else title,
        report_date_gregorian=datetime.now().strftime('%Y/%m/%d'),
        report_date_hijri='1448/04/24',
        document_number=document_number or 'No.000000',
        qr_code_url=qr_code_url,
        hide_approve=bool(document_number),
        approval_doc_type=doc_type,
        approval_item_id=item_id,
        orientation='portrait' if is_document else 'landscape',
        allow_orientation=False,
        is_document=is_document,
        report_params=params
    )


@reports_bp.route('/data/<report_key>', methods=['GET'])
def data_reports(report_key):
    if report_key not in DATA_REPORT_LABELS:
        return "<h3>نوع التقرير غير موجود.</h3>", 404

    if request.args.get('view') != 'print':
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            if report_key == 'employees':
                options = [dict(row) for row in conn.execute(
                    'SELECT id, full_name FROM team_members ORDER BY full_name'
                ).fetchall()]
            elif report_key == 'insurance':
                options = [dict(row) for row in conn.execute(
                    'SELECT id, vehicle_plate, policy_number FROM insurance_policies ORDER BY id DESC'
                ).fetchall()]
            elif report_key == 'inspections':
                options = [dict(row) for row in conn.execute(
                    'SELECT id, vehicle_plate, inspection_date FROM inspections ORDER BY id DESC'
                ).fetchall()]
            else:
                tables = {
                    row['name'] for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
                vehicle_source = 'vehicles' if 'vehicles' in tables else 'violations'
                vehicle_column = 'plate_number' if vehicle_source == 'vehicles' else 'vehicle_plate'
                vehicles = [row[0] for row in conn.execute(
                    f'SELECT DISTINCT "{vehicle_column}" FROM "{vehicle_source}" '
                    f'WHERE "{vehicle_column}" IS NOT NULL AND "{vehicle_column}" != \'\' ORDER BY "{vehicle_column}"'
                ).fetchall()]
                driver_source = 'drivers' if 'drivers' in tables else 'violations'
                driver_column = 'name' if driver_source == 'drivers' else 'driver_name'
                drivers = [row[0] for row in conn.execute(
                    f'SELECT DISTINCT "{driver_column}" FROM "{driver_source}" '
                    f'WHERE "{driver_column}" IS NOT NULL AND "{driver_column}" != \'\' ORDER BY "{driver_column}"'
                ).fetchall()]
                violation_options = [dict(row) for row in conn.execute(
                    'SELECT id, violation_number, vehicle_plate, violation_datetime FROM violations ORDER BY id DESC'
                ).fetchall()]
                options = {'vehicles': vehicles, 'drivers': drivers, 'violations': violation_options}
        finally:
            conn.close()
        return render_template(
            'data_report_options.html', report_key=report_key, options=options
        )

    params = request.args.to_dict()
    params.pop('view', None)
    try:
        report_type = params.get('report_type', 'all')
        allowed_types = {
            'employees': {'all', 'single'},
            'insurance': {'all', 'active', 'expired', 'near_expiry', 'single'},
            'inspections': {'all', 'active', 'expired', 'near_expiry', 'single'},
            'violations': {'all', 'vehicle', 'driver', 'month', 'year', 'range', 'single'}
        }[report_key]
        if report_type not in allowed_types:
            raise ValueError('قيمة الفلتر غير صالحة')
        required = {
            'employees': {'single': ('member_id',)},
            'insurance': {'single': ('policy_id',)},
            'inspections': {'single': ('inspection_id',)},
            'violations': {
                'vehicle': ('vehicle_plate',), 'driver': ('driver_name',),
                'month': ('month',), 'year': ('year',), 'single': ('violation_id',)
            }
        }[report_key].get(report_type, ())
        if any(not params.get(name, '').strip() for name in required):
            raise ValueError('أكمل قيمة الفلتر المطلوبة')
        if report_key == 'violations' and report_type == 'range' and not (
            params.get('date_from') or params.get('date_to')
        ):
            raise ValueError('أدخل تاريخ بداية أو نهاية للفترة')

        rows, columns, title = _data_report_context(report_key, params)
    except (ValueError, sqlite3.Error) as error:
        abort(400, description=str(error))

    item_id = json.dumps(
        {'category': report_key, 'params': params},
        sort_keys=True, ensure_ascii=False
    )
    document_number, qr_code_url = _lookup_approved_report(item_id, 'data_report')
    return render_template(
        'data_report_print.html',
        rows=rows,
        columns=columns,
        report_title_text=title,
        report_date_gregorian=datetime.now().strftime('%Y/%m/%d'),
        report_date_hijri='1448/04/24',
        document_number=document_number or 'No.000000',
        qr_code_url=qr_code_url,
        hide_approve=(not rows or bool(document_number)),
        approval_doc_type='data_report',
        approval_item_id=item_id,
        orientation='landscape',
        allow_orientation=False,
        report_key=report_key
    )


@reports_bp.route('/archive', methods=['GET'])
def archive():
    """استرجاع أرشيف التقارير والوثائق المصدورة سابقاً"""
    history = controller.get_report_archive()
    return jsonify({"status": "success", "data": history})


@reports_bp.route('/maintenance', methods=['GET'])
def maintenance_reports():
    order_id = request.args.get('order_id', type=int)
    if request.args.get('view') != 'print':
        return render_template(
            'maintenance_report_filter.html',
            type_titles=MAINTENANCE_TYPE_TITLES,
            filters=_maintenance_filters(request.args)
        )

    filters = _maintenance_filters(request.args)
    orders = _maintenance_orders(filters, order_id)
    doc_type, item_id = _maintenance_approval_identity(filters, order_id)
    document_number, qr_code_url = _lookup_approved_report(item_id, doc_type)
    return render_template(
        'maintenance_report_print.html',
        orders=orders,
        report_title_text=_maintenance_report_title(orders, filters, order_id),
        report_date_gregorian=datetime.now().strftime('%Y/%m/%d'),
        report_date_hijri='1448/04/24',
        document_number=document_number or 'No.000000',
        qr_code_url=qr_code_url,
        hide_approve=(not orders or bool(document_number)),
        approval_doc_type=doc_type,
        approval_item_id=item_id,
        allow_orientation=False,
        orientation='landscape',
        type_titles=MAINTENANCE_TYPE_TITLES
    )


@reports_bp.route('/approve', methods=['POST'])
def approve_document_api():
    """API اعتماد الوثيقة: توليد الرقم المرجعي المتسلسل No.000000 والـ QR Code وحفظهما"""
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({'success': False, 'message': 'صيغة طلب الاعتماد غير صالحة'}), 400
    doc_type = data.get('doc_type', 'accident_single')
    item_id = str(data.get('item_id', '1'))
    approval_token = data.get('approval_token', '')
    valid_doc_types = {
        'accidents_report', 'accident_single', 'drivers_report', 'driver_single_report',
        'data_report', 'vehicles_report', 'handover_report', 'handover_document',
        'maintenance_report', 'maintenance_order'
    }
    if not isinstance(doc_type, str) or doc_type not in valid_doc_types:
        return jsonify({'success': False, 'message': 'نوع التقرير غير صالح للاعتماد'}), 400
    if not isinstance(approval_token, str) or not re.fullmatch(r'[0-9a-f]{32}', approval_token):
        return jsonify({'success': False, 'message': 'انتهت صلاحية معاينة التقرير؛ أعد فتحه ثم حاول مرة أخرى'}), 400

    init_report_counter_db()
    try:
        with closing(sqlite3.connect(DB_PATH)) as connection:
            token_record = connection.execute(
                'SELECT doc_number, doc_type, item_id FROM approved_documents WHERE approval_token = ?',
                (approval_token,)
            ).fetchone()
    except sqlite3.Error:
        current_app.logger.exception('Unable to check the report approval token')
        return jsonify({'success': False, 'message': 'تعذر التحقق من حالة اعتماد التقرير'}), 500
    if token_record and (token_record[1] != doc_type or str(token_record[2]) != item_id):
        return jsonify({'success': False, 'message': 'معرّف الاعتماد مستخدم لمعاينة تقرير مختلفة'}), 409
    if token_record:
        existing_number = token_record[0]
        qr_filename = f"qr_{existing_number.replace('.', '_').replace('-', '_')}.png"
        return jsonify({
            'success': True,
            'doc_number': existing_number,
            'qr_code_url': f"/static/uploads/qrcodes/{qr_filename}",
            'public_url': url_for(
                'reports.public_view_document',
                doc_number=existing_number,
                _external=True
            )
        })

    report_params = None
    report_data = None
    report_title = None
    maintenance_filters = None
    maintenance_data = None
    maintenance_title = None
    maintenance_order_id = None
    driver_report_type = None
    driver_report_data = None
    driver_report_columns = None
    driver_report_params = None
    driver_report_title = None
    data_report_category = None
    data_report_params = None
    data_report_rows = None
    data_report_columns = None
    data_report_title = None
    vehicle_report_identity = None
    vehicle_report_data = None
    vehicle_report_fields = None
    vehicle_inspection_fields = None
    vehicle_policy_fields = None
    vehicle_driver_fields = None
    vehicle_report_title = None
    handover_records = None
    handover_columns = None
    handover_report_params = None
    handover_report_title = None
    handover_is_document = False
    if doc_type == 'accidents_report':
        try:
            report_params = json.loads(item_id)
        except (TypeError, json.JSONDecodeError):
            return jsonify({'success': False, 'message': 'بيانات فلاتر التقرير غير صالحة'}), 400
        report_params.update({'report_type': 'total', 'view': 'print'})
        existing_number, existing_qr = _lookup_approved_report(item_id, doc_type, approval_token)
        if existing_number:
            return jsonify({'success': True, 'doc_number': existing_number, 'qr_code_url': existing_qr})
        report_data = _fetch_accidents(report_params)
        report_title = _accident_report_title(report_params)

    if doc_type == 'accident_single':
        report_params = {
            'report_type': 'single',
            'accident_id': item_id,
            'view': 'print',
            'orientation': 'landscape',
            'report_format': 'illustrated'
        }
        report_data = _fetch_accidents(report_params)
        if not report_data:
            return jsonify({'success': False, 'message': 'الحادث المطلوب غير موجود'}), 404
        report_title = _accident_report_title(report_params)

    if doc_type in ['drivers_report', 'driver_single_report']:
        if doc_type == 'driver_single_report':
            try:
                driver_id = int(item_id)
            except ValueError:
                return jsonify({'success': False, 'message': 'رقم السائق غير صالح'}), 400
            driver_report_type = 'single'
            driver_report_data, driver_report_columns = _driver_report_data('single', driver_id=driver_id)
            driver_report_params = {'report_type': 'single', 'driver_id': driver_id}
        else:
            try:
                driver_report_params = json.loads(item_id)
                driver_report_type = driver_report_params.get('report_type')
                if driver_report_type not in {'all', 'assigned', 'unassigned'}:
                    raise ValueError
            except (TypeError, json.JSONDecodeError, ValueError):
                return jsonify({'success': False, 'message': 'بيانات تقرير السائقين غير صالحة'}), 400
            driver_report_data, driver_report_columns = _driver_report_data(
                driver_report_type, driver_report_params.get('fields')
            )

        if not driver_report_data:
            return jsonify({'success': False, 'message': 'لا توجد بيانات مطابقة لاعتماد التقرير'}), 404
        driver_report_title = (
            f"تقرير السائق: {driver_report_data[0].get('driver:name', '')}"
            if driver_report_type == 'single'
            else {
                'all': 'تقرير جميع السائقين',
                'assigned': 'تقرير السائقين المستلمين للمركبات',
                'unassigned': 'تقرير السائقين غير المستلمين للمركبات'
            }[driver_report_type]
        )
        existing_number, existing_qr = _lookup_approved_report(item_id, doc_type, approval_token)
        if existing_number:
            return jsonify({'success': True, 'doc_number': existing_number, 'qr_code_url': existing_qr})

    if doc_type == 'data_report':
        try:
            identity = json.loads(item_id)
            if not isinstance(identity, dict) or not isinstance(identity.get('params'), dict):
                raise ValueError
            data_report_category = identity['category']
            data_report_params = identity['params']
            data_report_rows, data_report_columns, data_report_title = _data_report_context(
                data_report_category, data_report_params
            )
        except (KeyError, TypeError, json.JSONDecodeError, ValueError, sqlite3.Error):
            return jsonify({'success': False, 'message': 'بيانات التقرير غير صالحة'}), 400
        if not data_report_rows:
            return jsonify({'success': False, 'message': 'لا توجد بيانات مطابقة لاعتماد التقرير'}), 404
        existing_number, existing_qr = _lookup_approved_report(item_id, doc_type, approval_token)
        if existing_number:
            return jsonify({'success': True, 'doc_number': existing_number, 'qr_code_url': existing_qr})

    if doc_type == 'vehicles_report':
        try:
            vehicle_report_identity = json.loads(item_id)
            if not isinstance(vehicle_report_identity, dict):
                raise ValueError
            report_type = vehicle_report_identity.get('report_type')
            if report_type not in {'all', 'single'}:
                raise ValueError
            vehicle_id = vehicle_report_identity.get('vehicle_id')
            identity_filters = vehicle_report_identity.get('filters') or {}
            if not isinstance(identity_filters, dict):
                raise ValueError
            vehicle_filters = _vehicle_report_filters(identity_filters)
            if report_type == 'single' and not vehicle_id:
                raise ValueError
            (
                vehicle_report_data, vehicle_report_fields, vehicle_inspection_fields,
                vehicle_policy_fields, vehicle_driver_fields, vehicle_report_title
            ) = _vehicle_report_data(
                vehicle_filters, vehicle_id if report_type == 'single' else None
            )
        except (TypeError, json.JSONDecodeError, ValueError, sqlite3.Error):
            return jsonify({'success': False, 'message': 'بيانات تقرير المركبة غير صالحة'}), 400
        if not vehicle_report_data:
            return jsonify({'success': False, 'message': 'لا توجد مركبات مطابقة لاعتماد التقرير'}), 404
        existing_number, existing_qr = _lookup_approved_report(item_id, doc_type, approval_token)
        if existing_number:
            return jsonify({'success': True, 'doc_number': existing_number, 'qr_code_url': existing_qr})

    if doc_type in {'handover_report', 'handover_document'}:
        handover_is_document = doc_type == 'handover_document'
        try:
            if handover_is_document:
                if not item_id.isdigit():
                    raise ValueError
                handover_report_params = {
                    'report_type': 'single',
                    'handover_id': item_id,
                    'movement_type': 'all',
                    'period': 'all',
                    'date_from': '',
                    'date_to': ''
                }
            else:
                handover_report_params = json.loads(item_id)
                if not isinstance(handover_report_params, dict):
                    raise ValueError
            handover_records, handover_columns, handover_report_title = _handover_report_context(
                handover_report_params, document=handover_is_document
            )
        except (TypeError, json.JSONDecodeError, ValueError, sqlite3.Error):
            return jsonify({'success': False, 'message': 'بيانات تقرير الاستلام والتسليم غير صالحة'}), 400
        if not handover_records:
            return jsonify({'success': False, 'message': 'لا توجد حركة مطابقة لاعتماد التقرير'}), 404
        existing_number, existing_qr = _lookup_approved_report(item_id, doc_type, approval_token)
        if existing_number:
            return jsonify({'success': True, 'doc_number': existing_number, 'qr_code_url': existing_qr})

    if doc_type in ['maintenance_report', 'maintenance_order']:
        if doc_type == 'maintenance_report':
            try:
                maintenance_filters = _maintenance_filters(json.loads(item_id))
            except (TypeError, json.JSONDecodeError):
                return jsonify({'success': False, 'message': 'بيانات فلاتر تقرير الصيانة غير صالحة'}), 400
            maintenance_data = _maintenance_orders(maintenance_filters)
        else:
            try:
                maintenance_order_id = int(item_id)
            except ValueError:
                return jsonify({'success': False, 'message': 'رقم أمر الصيانة غير صالح'}), 400
            maintenance_filters = _maintenance_filters({})
            maintenance_data = _maintenance_orders(maintenance_filters, maintenance_order_id)

        if not maintenance_data:
            return jsonify({'success': False, 'message': 'لا يوجد أمر صيانة مطابق للاعتماد'}), 404
        maintenance_title = _maintenance_report_title(
            maintenance_data, maintenance_filters, maintenance_order_id
        )
        existing_number, existing_qr = _lookup_approved_report(item_id, doc_type, approval_token)
        if existing_number:
            return jsonify({'success': True, 'doc_number': existing_number, 'qr_code_url': existing_qr})
    
    # 1. توليد الرقم المرجعي الموحد والمتسلسل (مثل No.000001)
    doc_number = generate_reference_number()
    
    # 2. توليد رمز الـ QR Code المخصص للوثيقة
    qr_url = generate_document_qr(doc_number, doc_type, item_id)

    archived_report_path = None
    if doc_type in {'accidents_report', 'accident_single'}:
        html = render_template(
            'accidents_print.html',
            accidents=report_data,
            accident=report_data[0] if doc_type == 'accident_single' else {},
            document_number=doc_number,
            qr_code_url=qr_url,
            hide_approve=True,
            approval_doc_type=doc_type,
            approval_item_id=item_id,
            report_title_text=report_title,
            report_date_gregorian=datetime.now().strftime('%Y/%m/%d'),
            report_date_hijri='1448/04/24',
            orientation=report_params.get('orientation', 'portrait'),
            report_format=report_params.get('report_format', 'illustrated'),
            filter_type=report_params.get('filter_type', 'all'),
            report_type='single' if doc_type == 'accident_single' else 'total'
        )
        archive_filename = f"report_{doc_number.replace('.', '_').replace('-', '_')}.html"
        archived_report_path = os.path.join(REPORTS_DIR, archive_filename)
        with open(archived_report_path, 'w', encoding='utf-8') as archive_file:
            archive_file.write(html)
    elif doc_type in ['maintenance_report', 'maintenance_order']:
        html = render_template(
            'maintenance_report_print.html',
            orders=maintenance_data,
            report_title_text=maintenance_title,
            report_date_gregorian=datetime.now().strftime('%Y/%m/%d'),
            report_date_hijri='1448/04/24',
            document_number=doc_number,
            qr_code_url=qr_url,
            hide_approve=True,
            approval_doc_type=doc_type,
            approval_item_id=item_id,
            allow_orientation=False,
            orientation='landscape',
            type_titles=MAINTENANCE_TYPE_TITLES
        )
        archive_filename = f"report_{doc_number.replace('.', '_').replace('-', '_')}.html"
        archived_report_path = os.path.join(REPORTS_DIR, archive_filename)
        with open(archived_report_path, 'w', encoding='utf-8') as archive_file:
            archive_file.write(html)
    elif doc_type in ['drivers_report', 'driver_single_report']:
        html = render_template(
            'drivers_report_print.html',
            rows=driver_report_data,
            columns=driver_report_columns,
            report_title_text=driver_report_title,
            report_date_gregorian=datetime.now().strftime('%Y/%m/%d'),
            report_date_hijri='1448/04/24',
            document_number=doc_number,
            qr_code_url=qr_url,
            hide_approve=True,
            approval_doc_type=doc_type,
            approval_item_id=item_id,
            orientation='landscape',
            allow_orientation=False,
            report_type=driver_report_type
        )
        archive_filename = f"report_{doc_number.replace('.', '_').replace('-', '_')}.html"
        archived_report_path = os.path.join(REPORTS_DIR, archive_filename)
        with open(archived_report_path, 'w', encoding='utf-8') as archive_file:
            archive_file.write(html)
    elif doc_type == 'data_report':
        html = render_template(
            'data_report_print.html',
            rows=data_report_rows,
            columns=data_report_columns,
            report_title_text=data_report_title,
            report_date_gregorian=datetime.now().strftime('%Y/%m/%d'),
            report_date_hijri='1448/04/24',
            document_number=doc_number,
            qr_code_url=qr_url,
            hide_approve=True,
            approval_doc_type=doc_type,
            approval_item_id=item_id,
            orientation='landscape',
            allow_orientation=False,
            report_key=data_report_category
        )
        archive_filename = f"report_{doc_number.replace('.', '_').replace('-', '_')}.html"
        archived_report_path = os.path.join(REPORTS_DIR, archive_filename)
        with open(archived_report_path, 'w', encoding='utf-8') as archive_file:
            archive_file.write(html)
    elif doc_type == 'vehicles_report':
        html = render_template(
            'vehicle_report_print.html',
            report_data=vehicle_report_data,
            vehicle_fields=vehicle_report_fields,
            inspection_fields=vehicle_inspection_fields,
            policy_fields=vehicle_policy_fields,
            driver_fields=vehicle_driver_fields,
            report_title_text=vehicle_report_title,
            report_date_gregorian=datetime.now().strftime('%Y/%m/%d'),
            report_date_hijri='1448/04/24',
            document_number=doc_number,
            qr_code_url=qr_url,
            hide_approve=True,
            approval_doc_type=doc_type,
            approval_item_id=item_id,
            orientation='landscape',
            allow_orientation=False,
            report_type=vehicle_report_identity['report_type'],
            filters=vehicle_report_identity.get('filters') or {}
        )
        archive_filename = f"report_{doc_number.replace('.', '_').replace('-', '_')}.html"
        archived_report_path = os.path.join(REPORTS_DIR, archive_filename)
        with open(archived_report_path, 'w', encoding='utf-8') as archive_file:
            archive_file.write(html)
    elif doc_type in {'handover_report', 'handover_document'}:
        html = render_template(
            'handover_report_print.html',
            records=handover_records,
            columns=handover_columns,
            report_title_text='وثيقة تسليم مركبة / معدة' if handover_is_document else handover_report_title,
            report_date_gregorian=datetime.now().strftime('%Y/%m/%d'),
            report_date_hijri='1448/04/24',
            document_number=doc_number,
            qr_code_url=qr_url,
            hide_approve=True,
            approval_doc_type=doc_type,
            approval_item_id=item_id,
            orientation='portrait' if handover_is_document else 'landscape',
            allow_orientation=False,
            is_document=handover_is_document,
            report_params=handover_report_params
        )
        archive_filename = f"report_{doc_number.replace('.', '_').replace('-', '_')}.html"
        archived_report_path = os.path.join(REPORTS_DIR, archive_filename)
        with open(archived_report_path, 'w', encoding='utf-8') as archive_file:
            archive_file.write(html)
    
    # 3. تسجيل المستند المعتمد في قاعدة البيانات
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO approved_documents
                (doc_number, doc_type, item_id, file_path, approval_token)
            VALUES (?, ?, ?, ?, ?)
        ''', (doc_number, doc_type, item_id, archived_report_path or qr_url, approval_token))

        if doc_type in {'accidents_report', 'accident_single'}:
            cursor.execute('''
                INSERT INTO generated_reports
                    (doc_uuid, doc_number, module_name, report_type, title, template_key,
                     parameters_json, local_report_path, local_qr_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                str(uuid.uuid4()), doc_number, 'accidents', report_params.get('report_format', 'illustrated'),
                report_title, 'accidents', json.dumps(report_params, ensure_ascii=False),
                archived_report_path, os.path.join(QR_DIR, os.path.basename(qr_url))
            ))
        elif doc_type in ['maintenance_report', 'maintenance_order']:
            cursor.execute('''
                INSERT INTO generated_reports
                    (doc_uuid, doc_number, module_name, report_type, title, template_key,
                     parameters_json, local_report_path, local_qr_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                str(uuid.uuid4()), doc_number, 'maintenance', doc_type,
                maintenance_title, 'maintenance',
                json.dumps(maintenance_filters if doc_type == 'maintenance_report' else {'order_id': maintenance_order_id}, ensure_ascii=False),
                archived_report_path, os.path.join(QR_DIR, os.path.basename(qr_url))
            ))
        elif doc_type in ['drivers_report', 'driver_single_report']:
            cursor.execute('''
                INSERT INTO generated_reports
                    (doc_uuid, doc_number, module_name, report_type, title, template_key,
                     parameters_json, local_report_path, local_qr_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                str(uuid.uuid4()), doc_number, 'drivers', doc_type,
                driver_report_title, 'drivers',
                json.dumps(driver_report_params, ensure_ascii=False),
                archived_report_path, os.path.join(QR_DIR, os.path.basename(qr_url))
            ))
        elif doc_type == 'data_report':
            cursor.execute('''
                INSERT INTO generated_reports
                    (doc_uuid, doc_number, module_name, report_type, title, template_key,
                     parameters_json, local_report_path, local_qr_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                str(uuid.uuid4()), doc_number, data_report_category,
                data_report_params.get('report_type', 'all'),
                data_report_title, 'data_report',
                json.dumps(data_report_params, ensure_ascii=False),
                archived_report_path, os.path.join(QR_DIR, os.path.basename(qr_url))
            ))
        elif doc_type == 'vehicles_report':
            cursor.execute('''
                INSERT INTO generated_reports
                    (doc_uuid, doc_number, module_name, report_type, title, template_key,
                     parameters_json, local_report_path, local_qr_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                str(uuid.uuid4()), doc_number, 'vehicles',
                vehicle_report_identity['report_type'], vehicle_report_title,
                'vehicles_report', json.dumps(vehicle_report_identity, ensure_ascii=False),
                archived_report_path, os.path.join(QR_DIR, os.path.basename(qr_url))
            ))
        elif doc_type in {'handover_report', 'handover_document'}:
            cursor.execute('''
                INSERT INTO generated_reports
                    (doc_uuid, doc_number, module_name, report_type, title, template_key,
                     parameters_json, local_report_path, local_qr_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                str(uuid.uuid4()), doc_number, 'handover',
                'documentation' if handover_is_document else handover_report_params['report_type'],
                'وثيقة تسليم مركبة / معدة' if handover_is_document else handover_report_title,
                'handover_report',
                json.dumps(handover_report_params, ensure_ascii=False),
                archived_report_path, os.path.join(QR_DIR, os.path.basename(qr_url))
            ))
        
        # ربط الرقم المرجعي بسجل الحوادث إذا كان نوع التقرير حادث سير
        if doc_type in ['accident_single', 'accidents']:
            try:
                cursor.execute('UPDATE accidents SET document_number = ? WHERE id = ? OR accident_number = ?', (doc_number, item_id, item_id))
            except Exception:
                pass
            
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error during document approval: {e}")
        for generated_path in (archived_report_path, os.path.join(QR_DIR, os.path.basename(qr_url))):
            if generated_path and os.path.exists(generated_path):
                os.remove(generated_path)
        return jsonify({'success': False, 'message': 'تعذر حفظ التقرير المعتمد'}), 500
    finally:
        conn.close()
    
    return jsonify({
        'success': True,
        'doc_number': doc_number,
        'qr_code_url': qr_url,
        'report_url': url_for(
            'static',
            filename=f"uploads/reports/report_{doc_number.replace('.', '_').replace('-', '_')}.html"
        ),
        'public_url': url_for(
            'reports.public_view_document', doc_number=doc_number, _external=True
        ),
        'message': 'تم اعتماد الوثيقة وتوليد الرقم المرجعي والـ QR Code بنجاح'
    })


@reports_bp.route('/public/view/<doc_number>')
def public_view_document(doc_number):
    """المسار العام المفتوح للوصول للوثيقة عند مسح رمز الـ QR Code من الجوال"""
    try:
        with closing(sqlite3.connect(DB_PATH)) as conn:
            result = conn.execute(
                'SELECT doc_type, item_id, file_path FROM approved_documents WHERE doc_number = ?',
                (doc_number,)
            ).fetchone()
    except sqlite3.Error:
        current_app.logger.exception('Unable to load an approved public report')
        return '<h3>تعذر تحميل التقرير المعتمد حالياً.</h3>', 500
    
    if result:
        doc_type, item_id, file_path = result
        if file_path and os.path.isfile(file_path):
            try:
                report_root = os.path.realpath(REPORTS_DIR)
                saved_path = os.path.realpath(file_path)
                if os.path.commonpath((report_root, saved_path)) == report_root:
                    return redirect(url_for(
                        'static',
                        filename=f'uploads/reports/{os.path.basename(saved_path)}'
                    ))
            except ValueError:
                pass
        if doc_type == 'accidents_report':
            try:
                params = json.loads(item_id)
                params.update({'report_type': 'total', 'view': 'print'})
                return redirect(url_for('reports.accidents_reports', **params))
            except (TypeError, json.JSONDecodeError):
                return "<h3>تعذر استعادة فلاتر التقرير المعتمد.</h3>", 400
        if doc_type == 'maintenance_report':
            try:
                filters = _maintenance_filters(json.loads(item_id))
                return redirect(url_for('reports.maintenance_reports', view='print', **filters))
            except (TypeError, json.JSONDecodeError):
                return "<h3>تعذر استعادة فلاتر تقرير الصيانة المعتمد.</h3>", 400
        if doc_type == 'maintenance_order':
            return redirect(url_for('reports.maintenance_reports', view='print', order_id=item_id))
        if doc_type == 'driver_single_report':
            return redirect(url_for('reports.drivers_reports', report_type='single', driver_id=item_id))
        if doc_type == 'drivers_report':
            try:
                params = json.loads(item_id)
                return redirect(url_for('reports.drivers_reports', **params, view='print'))
            except (TypeError, json.JSONDecodeError):
                return "<h3>تعذر استعادة خيارات تقرير السائقين المعتمد.</h3>", 400
        if doc_type == 'data_report':
            try:
                identity = json.loads(item_id)
                return redirect(url_for(
                    'reports.data_reports', report_key=identity['category'],
                    **identity['params'], view='print'
                ))
            except (KeyError, TypeError, json.JSONDecodeError):
                return "<h3>تعذر استعادة خيارات التقرير المعتمد.</h3>", 400
        if doc_type == 'vehicles_report':
            try:
                identity = json.loads(item_id)
                if not isinstance(identity, dict):
                    raise ValueError
                identity_filters = identity.get('filters') or {}
                if not isinstance(identity_filters, dict):
                    raise ValueError
                params = {
                    'report_type': identity.get('report_type', 'all'),
                    'view': 'print'
                }
                if identity.get('vehicle_id') is not None:
                    params['vehicle_id'] = identity['vehicle_id']
                params.update(_vehicle_report_filters(identity_filters))
                return redirect(url_for(
                    'reports.vehicle_reports', **params
                ))
            except (TypeError, ValueError, json.JSONDecodeError):
                return "<h3>تعذر استعادة خيارات تقرير المركبات المعتمد.</h3>", 400
        if doc_type == 'handover_document':
            if str(item_id).isdigit():
                return redirect(url_for(
                    'reports.handover_reports', view='document', handover_id=item_id
                ))
            return "<h3>تعذر استعادة وثيقة توثيق حركة الاستلام والتسليم.</h3>", 400
        if doc_type == 'handover_report':
            try:
                params = json.loads(item_id)
                if not isinstance(params, dict):
                    raise ValueError
                params['view'] = 'print'
                return redirect(url_for('reports.handover_reports', **params))
            except (TypeError, ValueError, json.JSONDecodeError):
                return "<h3>تعذر استعادة خيارات تقرير الاستلام والتسليم المعتمد.</h3>", 400
        if doc_type in ['accident_single', 'accidents']:
            return redirect(url_for('reports.accidents_reports', report_type='single', accident_id=item_id, orientation='landscape'))
        return redirect(url_for('reports.preview', template_key=doc_type, id=item_id))
    
    return "<h3>عذراً، هذه الوثيقة غير مسجلة أو لم يتم اعتمادها بعد.</h3>", 404


def _row_to_dict(row):
    if not row:
        return {}
    if isinstance(row, dict):
        return row
    try:
        return dict(row)
    except Exception:
        return {}


def _lookup_qr(doc_num):
    if not doc_num:
        return None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT file_path FROM approved_documents WHERE doc_number = ?', (doc_num,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return row[0]
    except Exception:
        pass
    return None


@reports_bp.route('/accidents', methods=['GET'])
def accidents_reports():
    """عرض وتصفية تقارير الحوادث من قاعدة البيانات مع دعم التقرير الفردي والكلي"""
    report_type = request.args.get('report_type', 'total')  # 'total' أو 'single'
    filter_type = request.args.get('filter_type', 'all')
    report_format = request.args.get('report_format', 'illustrated')
    view_mode = request.args.get('view', '').strip()

    selected_month = request.args.get('month')
    selected_year = request.args.get('year')
    daily_date = request.args.get('daily_date')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    accident_id = request.args.get('accident_id', '').strip()

    default_orientation = 'portrait'
    orientation = request.args.get('orientation', default_orientation)

    accidents_data = _fetch_accidents(request.args.to_dict())

    print_ctx = {
        'report_date_gregorian': datetime.now().strftime('%Y/%m/%d'),
        'report_date_hijri': '1448/04/24',
        'orientation': orientation,
        'report_format': report_format,
        'filter_type': filter_type,
    }

    if report_type == 'single' or view_mode == 'print':
        single_accident = accidents_data[0] if accidents_data else {}
        is_filtered_report = report_type != 'single'
        report_item_id = json.dumps(request.args.to_dict(), sort_keys=True, ensure_ascii=False)
        if is_filtered_report:
            doc_num, qr_url = _lookup_approved_report(report_item_id)
        else:
            doc_num = None
            qr_url = None

        return render_template(
            'accidents_print.html',
            accidents=accidents_data,
            accident=single_accident,
            document_number=doc_num or 'No.000000',
            qr_code_url=qr_url,
            hide_approve=(not accidents_data or bool(doc_num)),
            approval_doc_type='accidents_report' if is_filtered_report else 'accident_single',
            approval_item_id=report_item_id if is_filtered_report else str(single_accident.get('id') or single_accident.get('accident_number') or '1'),
            report_title_text=_accident_report_title(request.args),
            **print_ctx
        )

    return render_template(
        'accidents_reports.html',
        accidents=accidents_data,
        accident={},
        report_type=report_type,
        selected_month=selected_month,
        selected_year=selected_year,
        date_from=date_from,
        date_to=date_to,
        current_year=datetime.now().year,
        hide_approve=True,
        **print_ctx
    )

@reports_bp.route('/workshop-request', methods=['GET', 'POST'])
def workshop_request_form():
    return ReportsController.workshop_request_form()