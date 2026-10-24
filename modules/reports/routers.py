import io
import json
import os
import re
from html import escape
from html.parser import HTMLParser
from core import database as dbapi
from core import storage
import smtplib
import uuid
from contextlib import closing
from datetime import datetime
from flask import Blueprint, Response, current_app, render_template, request, jsonify, redirect, url_for, abort, session, send_file, flash
from PIL import Image, ImageOps, UnidentifiedImageError
from modules.reports.controllers.reports_controller import ReportsController
from modules.reports.models.reports_model import ReportsModel
from modules.reports.typography import get_report_typography
from .services.reports_service import (
    generate_reference_number,
    generate_document_qr,
    init_report_counter_db,
    render_report_pdf,
    QR_DIR,
    REPORTS_DIR
)
from core.database import Database, SessionLocal, get_session
from modules.workshop.maintenance.models.maintenance_orm import MaintenanceOrder
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from modules.reports import repository as reports_repository
from modules.workshop.maintenance.controller.maintenance_controller import MaintenanceController
from modules.workshop.maintenance.controller.maintenance_controller import TYPE_TITLES as MAINTENANCE_TYPE_TITLES
from modules.workshop.maintenance.services.maintenance_services import MaintenanceService
from modules.handover.services.handover_service import get_db_connection
from modules.settings.services.email_service import (
    EmailConfigurationError,
    get_email_setting,
    get_public_base_url,
    send_email,
)
from utils.expiry_status import get_expiry_status

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
ACCIDENT_UPLOADS_DIR = os.path.join(
    PROJECT_ROOT, 'app', 'static', 'uploads', 'accidents'
)
LEGACY_REPORTS_DIR = os.path.join(PROJECT_ROOT, 'app', 'static', 'uploads', 'reports')
LEGACY_QR_DIR = os.path.join(PROJECT_ROOT, 'app', 'static', 'uploads', 'qrcodes')

# إنشاء راوتر الموديول (Blueprint)
reports_bp = Blueprint(
    'reports',
    __name__,
    template_folder='views',
    url_prefix='/reports'
)


def _discard_files(*paths):
    for path in paths:
        if not path:
            continue
        if storage.is_url(path):
            if not storage.delete_file(path):
                current_app.logger.warning('Unable to remove cloud report artifact %s', path)
        elif os.path.isfile(path):
            os.remove(path)


def _upload_report_artifact(local_path, folder, content_type):
    with open(local_path, 'rb') as artifact:
        return storage.upload_bytes(
            artifact.read(),
            folder,
            os.path.basename(local_path),
            content_type=content_type,
        )


def _read_report_artifact(stored_path):
    if not stored_path:
        raise FileNotFoundError('ملف التقرير المعتمد غير متاح')
    if storage.is_url(stored_path):
        return storage.download_file(stored_path)

    normalized_path = str(stored_path)
    for prefix in ('/static/uploads/reports/', 'static/uploads/reports/', 'uploads/reports/'):
        if normalized_path.startswith(prefix):
            normalized_path = os.path.join(LEGACY_REPORTS_DIR, os.path.basename(normalized_path))
            break
    candidate = os.path.realpath(normalized_path)
    allowed_roots = (os.path.realpath(REPORTS_DIR), os.path.realpath(LEGACY_REPORTS_DIR))
    for root in allowed_roots:
        try:
            if os.path.commonpath((root, candidate)) == root and os.path.isfile(candidate):
                with open(candidate, 'rb') as artifact:
                    return artifact.read()
        except ValueError:
            continue

    legacy_candidate = os.path.join(LEGACY_REPORTS_DIR, os.path.basename(normalized_path))
    if os.path.isfile(legacy_candidate):
        with open(legacy_candidate, 'rb') as artifact:
            return artifact.read()
    raise FileNotFoundError('ملف التقرير المعتمد غير متاح')


def _remove_memo_artifacts(paths):
    for path in set(paths):
        if storage.is_url(path):
            if not storage.delete_file(path):
                current_app.logger.warning('Unable to remove cloud report artifact %s', path)
        elif path and os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                current_app.logger.exception('Unable to remove archived report artifact %s', path)


GENERAL_MEMO_FIELD_TITLES = {
    'recipient': 'التوجيه',
    'subject': 'الموضوع',
    'salutation': 'التقديم',
    'body': 'المتن',
    'recommendations': 'التوصيات',
    'requests': 'الطلبات',
    'conclusion': 'الخاتمة',
    'signature': 'التوقيع',
}

_VOID_HTML_TAGS = {
    'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
    'meta', 'param', 'source', 'track', 'wbr',
}


class _EditableTextHTMLParser(HTMLParser):
    def __init__(self, editable_values):
        super().__init__(convert_charrefs=False)
        self.editable_values = editable_values
        self.editable_count = 0
        self.output = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if self.skip_depth:
            if tag not in _VOID_HTML_TAGS:
                self.skip_depth += 1
            return

        raw_tag = self.get_starttag_text()
        attributes = {name.lower(): value for name, value in attrs}
        if attributes.get('contenteditable', '').lower() == 'true':
            if self.editable_count >= len(self.editable_values):
                raise ValueError('عدد الحقول القابلة للتحرير لا يطابق معاينة التقرير')
            value = self.editable_values[self.editable_count]
            self.editable_count += 1
            self.output.append(raw_tag)
            self.output.append(
                '<br>'.join(escape(line, quote=False) for line in value.splitlines())
            )
            if tag not in _VOID_HTML_TAGS:
                self.skip_depth = 1
            return
        self.output.append(raw_tag)

    def handle_startendtag(self, tag, attrs):
        if not self.skip_depth:
            self.output.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        if self.skip_depth:
            self.skip_depth -= 1
            if self.skip_depth == 0:
                self.output.append(f'</{tag}>')
            return
        self.output.append(f'</{tag}>')

    def handle_data(self, data):
        if not self.skip_depth:
            self.output.append(data)

    def handle_entityref(self, name):
        if not self.skip_depth:
            self.output.append(f'&{name};')

    def handle_charref(self, name):
        if not self.skip_depth:
            self.output.append(f'&#{name};')

    def handle_comment(self, data):
        if not self.skip_depth:
            self.output.append(f'<!--{data}-->')

    def handle_decl(self, decl):
        if not self.skip_depth:
            self.output.append(f'<!{decl}>')

    def handle_pi(self, data):
        if not self.skip_depth:
            self.output.append(f'<?{data}>')


def _apply_editable_values(html, editable_values):
    if editable_values is None:
        return html

    parser = _EditableTextHTMLParser(editable_values)
    parser.feed(html)
    parser.close()
    if parser.editable_count != len(editable_values):
        raise ValueError('عدد الحقول القابلة للتحرير لا يطابق معاينة التقرير')
    return ''.join(parser.output)


@reports_bp.app_context_processor
def inject_report_approval_token():
    return {'approval_token': uuid.uuid4().hex}


@reports_bp.context_processor
def inject_report_typography_settings():
    return get_report_typography()

# استدعاء متحكم التقارير
controller = ReportsController()
reports_model = ReportsModel()

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
    hidden_columns = {
        'id', 'record_id', 'serial_number', 'status', 'system_status'
    }
    hide_attachments = category in {'insurance', 'inspections', 'violations'}
    return [
        {'key': name, 'label': labels.get(name, name.replace('_', ' '))}
        for name in column_names
        if name not in hidden_columns
        and not (hide_attachments and 'attachment' in name.lower())
    ]


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

    conn = dbapi.connect()
    conn.row_factory = dbapi.Row
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


def _accident_report_phase(accident):
    status = str(accident.get('status') or '').strip().lower()
    return 'closed' if status == 'closed' or accident.get('closed_at') else 'open'


def _accident_single_report_title(accident):
    phase_title = (
        'بعد الإقفال والتسوية'
        if _accident_report_phase(accident) == 'closed'
        else 'قبل الإقفال والتسوية'
    )
    return f'تقرير حادث سير - {phase_title}'


def _accident_report_identity(accident):
    return json.dumps({
        'accident_id': str(accident.get('id') or accident.get('accident_number') or ''),
        'phase': _accident_report_phase(accident)
    }, sort_keys=True)


def _parse_accident_report_identity(item_id):
    try:
        identity = json.loads(item_id)
    except (TypeError, json.JSONDecodeError):
        return str(item_id), None
    if isinstance(identity, int) and not isinstance(identity, bool):
        return str(identity), None
    if (
        not isinstance(identity, dict)
        or not str(identity.get('accident_id', '')).strip()
        or identity.get('phase') not in {'open', 'closed'}
    ):
        raise ValueError('هوية تقرير الحادث غير صالحة')
    return str(identity['accident_id']), identity['phase']


def _lookup_approved_report(item_id=None, doc_type='accidents_report', approval_token=None):
    try:
        init_report_counter_db()
        doc_number, qr_path = reports_repository.lookup_approved_report(
            item_id, doc_type, approval_token
        )
    except SQLAlchemyError:
        current_app.logger.exception('Unable to look up a finalized report')
        abort(500, description='تعذر التحقق من اعتماد التقرير')
    if doc_number:
        if not qr_path:
            qr_filename = f"qr_{doc_number.replace('.', '_').replace('-', '_')}.png"
            qr_path = f"/static/uploads/qrcodes/{qr_filename}"
        return doc_number, qr_path
    return None, None

def _redirect_to_finalized_report(item_id, doc_type):
    doc_number, _ = _lookup_approved_report(item_id, doc_type)
    if doc_number:
        return redirect(url_for('reports.final_report', doc_number=doc_number))
    return None


def _finalized_document(doc_number):
    init_report_counter_db()
    try:
        return reports_model.get_finalized_report_by_number(doc_number)
    except SQLAlchemyError:
        current_app.logger.exception('Unable to load finalized report %s', doc_number)
        abort(500, description='تعذر تحميل بيانات التقرير النهائي')


def _stored_accident_image(filename):
    """Stored accident attachment as something an <img> can load, or None."""
    if not filename:
        return None
    if storage.is_url(filename):
        return filename
    basename = os.path.basename(str(filename))
    resolved = os.path.realpath(os.path.join(ACCIDENT_UPLOADS_DIR, basename))
    try:
        if os.path.commonpath((os.path.realpath(ACCIDENT_UPLOADS_DIR), resolved)) != os.path.realpath(ACCIDENT_UPLOADS_DIR):
            return None
    except ValueError:
        return None
    if not os.path.isfile(resolved):
        return None
    return url_for('static', filename=f"uploads/accidents/{basename}")


def _discard_uploaded(urls):
    storage.delete_files(*urls)


def _save_accident_report_images(accident, uploaded_files, reference_number):
    image_sources = {}
    saved_paths = []
    for field_name, database_key in (
        ('accident_attachment', 'accident_attachment'),
        ('accident_attachment_2', 'accident_attachment_2')
    ):
        uploaded = uploaded_files.get(field_name)
        if not uploaded or not uploaded.filename:
            saved_image = _stored_accident_image(accident.get(database_key))
            if saved_image:
                image_sources[field_name] = saved_image
            continue

        payload = uploaded.stream.read(12 * 1024 * 1024 + 1)
        if len(payload) > 12 * 1024 * 1024:
            _discard_uploaded(saved_paths)
            raise ValueError('يجب ألا يتجاوز حجم كل صورة 12 ميغابايت')
        try:
            with Image.open(io.BytesIO(payload)) as image:
                if image.width * image.height > 40_000_000:
                    raise ValueError('حجم أبعاد الصورة يتجاوز الحد المسموح')
                image.verify()
            with Image.open(io.BytesIO(payload)) as image:
                normalized_image = ImageOps.exif_transpose(image).convert('RGB')
        except (
            UnidentifiedImageError, OSError, ValueError,
            Image.DecompressionBombError, Image.DecompressionBombWarning
        ):
            _discard_uploaded(saved_paths)
            raise ValueError('الملف المختار ليس صورة صالحة أو يتجاوز الأبعاد المسموحة')

        buffer = io.BytesIO()
        try:
            normalized_image.save(buffer, format='JPEG', quality=92, optimize=True)
            image_url = storage.upload_bytes(
                buffer.getvalue(),
                'report_images',
                f"report_image_{reference_number.replace('.', '_').replace('-', '_')}.jpg",
                content_type='image/jpeg',
            )
        except (OSError, storage.StorageError):
            _discard_uploaded(saved_paths)
            current_app.logger.exception('Unable to save accident report image')
            raise
        finally:
            normalized_image.close()

        saved_paths.append(image_url)
        image_sources[field_name] = image_url

    return image_sources, saved_paths


def _save_maintenance_report_photos(orders, uploaded_files):
    allowed_formats = {
        'JPEG': 'jpg',
        'PNG': 'png',
        'GIF': 'gif',
        'WEBP': 'webp',
        'BMP': 'bmp'
    }
    expected_uploads = {
        f'maintenance_photo_{photo_slot}_{order["id"]}': (order, f'photo_{photo_slot}')
        for order in orders
        for photo_slot in ('before', 'after')
    }
    unexpected_uploads = [
        field_name for field_name in uploaded_files
        if field_name not in expected_uploads
        and any(upload.filename for upload in uploaded_files.getlist(field_name))
    ]
    if unexpected_uploads:
        raise ValueError('حقول صور تقرير الصيانة غير صالحة')

    photo_updates = {}
    saved_paths = []
    try:
        for upload_name, (order, field_name) in expected_uploads.items():
            uploads = uploaded_files.getlist(upload_name)
            if len(uploads) > 1:
                raise ValueError('يمكن اختيار صورة واحدة لكل خانة')
            if not uploads or not uploads[0].filename:
                continue

            upload = uploads[0]
            payload = upload.stream.read(12 * 1024 * 1024 + 1)
            if len(payload) > 12 * 1024 * 1024:
                raise ValueError('يجب ألا يتجاوز حجم كل صورة 12 ميغابايت')
            try:
                with Image.open(io.BytesIO(payload)) as image:
                    image_format = image.format
                    image.verify()
            except (
                UnidentifiedImageError, OSError, ValueError,
                Image.DecompressionBombError
            ):
                raise ValueError('الملف المختار ليس صورة صالحة')

            extension = allowed_formats.get(image_format)
            if not extension:
                raise ValueError('صيغة الصورة غير مدعومة')

            image_url = storage.upload_bytes(
                payload, 'maintenance', extension=f'.{extension}',
                content_type=f'image/{"jpeg" if extension == "jpg" else extension}',
            )
            saved_paths.append(image_url)
            photo_updates.setdefault(order['id'], {})[field_name] = image_url
    except Exception:
        _discard_uploaded(saved_paths)
        raise

    return photo_updates, saved_paths


def _saved_handover_document_response(handover, handover_id):
    if handover['report_data']:
        return Response(
            re.sub(
                r'\scontenteditable\s*=\s*(["\'])true\1',
                ' contenteditable="false"',
                handover['report_data'],
                flags=re.IGNORECASE
            ),
            mimetype='text/html'
        )

    report_paths = [handover['report_file_path']]
    try:
        approved_path = reports_repository.latest_document_path('handover_document', handover_id)
        if approved_path:
            report_paths.append(approved_path)
        if handover['document_number']:
            generated_path = reports_repository.generated_report_path(
                handover['document_number'], 'handover'
            )
            if generated_path:
                report_paths.append(generated_path)
    except SQLAlchemyError:
        current_app.logger.exception(
            'Unable to find the approved file for handover %s', handover_id
        )
        abort(500, description='تعذر استرجاع ملف التوثيق المعتمد')

    report_root = os.path.realpath(REPORTS_DIR)
    for report_path in report_paths:
        if not report_path:
            continue
        if storage.is_url(report_path):
            try:
                report_html = storage.download_file(report_path).decode('utf-8')
            except (storage.StorageError, UnicodeError):
                current_app.logger.exception(
                    'Unable to read the approved report for handover %s', handover_id
                )
                continue
            report_html = re.sub(
                r'\scontenteditable\s*=\s*(["\'])true\1',
                ' contenteditable="false"',
                report_html,
                flags=re.IGNORECASE
            )
            return Response(report_html, mimetype='text/html')
        candidates = [os.path.realpath(report_path)]
        candidates.append(
            os.path.realpath(os.path.join(report_root, os.path.basename(report_path)))
        )
        for resolved_path in candidates:
            try:
                is_saved_report = os.path.commonpath((report_root, resolved_path)) == report_root
            except ValueError:
                is_saved_report = False
            if not is_saved_report or not os.path.isfile(resolved_path):
                continue
            try:
                with open(resolved_path, encoding='utf-8') as report_file:
                    report_html = report_file.read()
            except (OSError, UnicodeError):
                current_app.logger.exception(
                    'Unable to read the approved report for handover %s', handover_id
                )
                continue
            report_html = re.sub(
                r'\scontenteditable\s*=\s*(["\'])true\1',
                ' contenteditable="false"',
                report_html,
                flags=re.IGNORECASE
            )
            return Response(report_html, mimetype='text/html')
    return None


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
        title = f"تقرير أمر صيانة {order.get('order_no') or order.get('id') or order_id}"
        if order.get('status') == 'open':
            return f"{title} (قبل التقفيل)"
        if order.get('status') == 'closed':
            return f"{title} (بعد التقفيل)"
        return title
    type_title = MAINTENANCE_TYPE_TITLES.get(filters['type'], 'جميع أنواع الصيانة')
    status_title = {'open': 'المفتوحة', 'closed': 'المغلقة المؤرشفة', 'all': 'المفتوحة والمغلقة'}[filters['status']]
    title = f"تقرير {type_title} {status_title}"
    if filters['date_from'] or filters['date_to']:
        title += f" من {filters['date_from'] or '...'} إلى {filters['date_to'] or '...'}"
    return title


def _maintenance_approval_identity(filters, order_id=None, orders=None):
    if order_id is not None:
        order = orders[0] if orders else {}
        return 'maintenance_order', json.dumps({
            'order_id': order_id,
            'status': order.get('status')
        }, sort_keys=True, ensure_ascii=False)
    return 'maintenance_report', json.dumps(filters, sort_keys=True, ensure_ascii=False)


def _is_repeatable_aggregate_report(doc_type, item_id):
    if doc_type in {'accidents_report', 'maintenance_report'}:
        return True
    report_type = None
    try:
        identity = json.loads(item_id)
    except (TypeError, json.JSONDecodeError):
        return False
    if not isinstance(identity, dict):
        return False
    if doc_type == 'drivers_report':
        report_type = identity.get('report_type')
    elif doc_type == 'vehicles_report':
        report_type = identity.get('report_type')
    elif doc_type == 'data_report':
        params = identity.get('params')
        report_type = params.get('report_type', 'all') if isinstance(params, dict) else None
    elif doc_type == 'handover_report':
        report_type = identity.get('report_type')
    return report_type is not None and report_type != 'single'


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
    conn = dbapi.connect()
    conn.row_factory = dbapi.Row
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
    conn = dbapi.connect()
    conn.row_factory = dbapi.Row
    try:
        vehicles = [dict(row) for row in conn.execute(
            'SELECT * FROM vehicles ORDER BY vehicle_code, plate_number'
        ).fetchall()]
        archive_table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'vehicle_archive'"
        ).fetchone() is not None
        archived_vehicles = {
            str(row['vehicle_id']): dict(row)
            for row in conn.execute(
                'SELECT * FROM vehicle_archive'
            ).fetchall()
        } if archive_table_exists else {}
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
        custom_vehicle_labels = {
            row['name']: row['label']
            for row in conn.execute('SELECT name, label FROM vehicle_fields').fetchall()
        }
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
        archive = archived_vehicles.get(str(vehicle.get('id')))
        if archive:
            vehicle['status'] = 'خارج الخدمة'
            vehicle['workshop_status'] = 'خارج الخدمة'
            if filters.get('status') and filters['status'] != vehicle['status']:
                continue
            result.append({
                'vehicle': vehicle,
                'driver': None,
                'is_assigned': False,
                'is_archived': True,
                'archive': archive,
                'policies': [],
                'inspections': [],
            })
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
            'is_archived': False,
            'archive': None,
            'policies': related_policies,
            'inspections': related_inspections
        })

    vehicle_fields = [
        {
            'key': name,
            'label': custom_vehicle_labels.get(
                name, VEHICLE_FIELD_LABELS.get(name, name.replace('_', ' '))
            ),
            'is_custom': name in custom_vehicle_labels,
        }
        for name in vehicle_columns
        if name not in {'id', 'vehicle_id', 'chassis_number', 'vin'}
    ]
    inspection_fields = [
        {'key': name, 'label': INSPECTION_REPORT_LABELS.get(name, name.replace('_', ' '))}
        for name in inspection_columns
        if name not in {'id', 'record_id', 'serial_number', 'status', 'system_status'}
        and 'attachment' not in name.lower()
    ]
    if 'status_type' not in inspection_columns and not any(
        field['key'] == 'status_type' for field in inspection_fields
    ):
        inspection_fields.append({'key': 'status_type', 'label': 'حالة الفحص'})
    policy_fields = [
        {'key': name, 'label': DATA_REPORT_LABELS['insurance'].get(name, name.replace('_', ' '))}
        for name in policy_columns
        if name not in {'id', 'record_id', 'serial_number', 'status', 'system_status'}
        and 'attachment' not in name.lower()
    ]
    if 'status_type' not in policy_columns and not any(
        field['key'] == 'status_type' for field in policy_fields
    ):
        policy_fields.append({'key': 'status_type', 'label': 'حالة التأمين'})
    driver_fields = [
        {'key': name, 'label': DRIVER_FIELD_LABELS.get(name, name.replace('_', ' '))}
        for name in driver_columns
    ]
    title = 'تقرير المعدات والمركبات'
    if vehicle_id is not None and result:
        title = (
            f"تقرير مركبة مؤرشفة — رقم اللوحة {result[0]['vehicle'].get('plate_number') or ''}"
            if result[0].get('is_archived')
            else f"بيانات المركبة — رقم اللوحة {result[0]['vehicle'].get('plate_number') or ''}"
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

    conn = dbapi.connect()
    conn.row_factory = dbapi.Row
    try:
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'handovers'"
        ).fetchone()
        if not table_exists:
            return [], [], 'تقرير حركات الاستلام والتسليم'
        rows = [dict(row) for row in conn.execute(
            'SELECT * FROM handovers ORDER BY handover_date DESC, id DESC'
        ).fetchall()]
        vehicle_plates = {}
        vehicles_table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'vehicles'"
        ).fetchone()
        if vehicles_table_exists:
            vehicle_rows = conn.execute(
                'SELECT id, vehicle_code, plate_number FROM vehicles'
            ).fetchall()
            vehicle_plates = {
                str(row['id']): row['plate_number'] for row in vehicle_rows
            }
            vehicle_plates_by_info = {}
            for row in vehicle_rows:
                vehicle_info = f"{row['vehicle_code'] or ''} - {row['plate_number'] or ''}".strip(' -')
                for identifier in (vehicle_info, row['vehicle_code'], row['plate_number']):
                    if identifier:
                        vehicle_plates_by_info[str(identifier).strip()] = row['plate_number']
        else:
            vehicle_plates_by_info = {}
        columns_in_table = [
            row['name'] for row in conn.execute('PRAGMA table_info(handovers)')
        ]
    finally:
        conn.close()

    today = datetime.now().strftime('%Y-%m-%d')
    filtered_rows = []
    for record in rows:
        record['vehicle_plate'] = (
            vehicle_plates.get(str(record.get('vehicle_id') or ''))
            or vehicle_plates_by_info.get(str(record.get('vehicle_info') or '').strip())
            or '—'
        )
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
        filtered_rows.append(record)

    if report_type == 'single' or document:
        document_action = 'تسليم' if filtered_rows and filtered_rows[0].get('handover_type') == 'تسليم عهدة' else 'إرجاع'
        title = f'وثيقة {document_action} مركبة / معدة' if document else 'تقرير حركة استلام وتسليم محددة'
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
    conn = dbapi.connect()
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

    conn = dbapi.connect()
    try:
        conn.row_factory = dbapi.Row
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
    candidate_id = params.get('id') or params.get('accident_id')
    if candidate_id:
        final_redirect = _redirect_to_finalized_report(candidate_id, template_key)
        if final_redirect:
            return final_redirect
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
    if _is_repeatable_aggregate_report(doc_type, item_id):
        document_number, qr_code_url = None, None
    else:
        document_number, qr_code_url = _lookup_approved_report(item_id, doc_type)
    if document_number:
        return redirect(url_for('reports.final_report', doc_number=document_number))
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
        conn = dbapi.connect()
        conn.row_factory = dbapi.Row
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
    if _is_repeatable_aggregate_report('vehicles_report', item_id):
        document_number, qr_code_url = None, None
    else:
        document_number, qr_code_url = _lookup_approved_report(item_id, 'vehicles_report')
    if document_number:
        return redirect(url_for('reports.final_report', doc_number=document_number))
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

    conn = dbapi.connect()
    conn.row_factory = dbapi.Row
    try:
        conn.execute('BEGIN IMMEDIATE')
        vehicle_row = conn.execute(
            """SELECT * FROM vehicles WHERE id = ?
               AND NOT EXISTS (
                   SELECT 1 FROM vehicle_archive
                   WHERE vehicle_archive.vehicle_id = vehicles.id
               )
               AND COALESCE(status, '') != 'خارج الخدمة'""",
            (vehicle_id,)
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
    is_document = view == 'document'
    handover_id = params['handover_id']
    if is_document or params['report_type'] == 'single':
        if handover_id.isdigit():
            init_report_counter_db()
            conn = get_db_connection()
            try:
                handover = conn.execute(
                    """SELECT id, status, report_data, report_file_path, document_number,
                              CASE WHEN is_certified = 1 OR EXISTS (
                                  SELECT 1 FROM approved_documents
                                  WHERE doc_type = 'handover_document'
                                    AND item_id = CAST(handovers.id AS TEXT)
                              ) THEN 1 ELSE 0 END AS is_certified
                       FROM handovers WHERE id = ?""",
                    (handover_id,)
                ).fetchone()
            finally:
                conn.close()
            if not handover:
                abort(404, description='حركة الاستلام والتسليم المطلوبة غير موجودة')
            if handover['status'] == 'مؤرشف' and not handover['is_certified']:
                abort(403, description='لا يمكن إنشاء تقرير جديد لحركة مؤرشفة غير موثقة')
            if handover['is_certified']:
                finalized_number, _ = _lookup_approved_report(
                    handover_id, 'handover_document'
                )
                if finalized_number:
                    return redirect(url_for(
                        'reports.final_report', doc_number=finalized_number
                    ))
                saved_document = _saved_handover_document_response(handover, handover_id)
                if saved_document:
                    return saved_document
                abort(410, description='رقم الحركة معتمد، لكن ملف التوثيق غير متاح')
            if is_document and handover['status'] not in {'نشط', 'بانتظار التوثيق'}:
                abort(403, description='لا يمكن توثيق حركة غير نشطة')

    if view not in {'print', 'document'}:
        conn = dbapi.connect()
        conn.row_factory = dbapi.Row
        try:
            options = [dict(row) for row in conn.execute(
                'SELECT id, handover_type, vehicle_info, driver_info, handover_date '
                'FROM handovers ORDER BY handover_date DESC, id DESC'
            ).fetchall()]
        finally:
            conn.close()
        return render_template('handover_report_options.html', options=options)

    try:
        records, columns, title = _handover_report_context(params, document=is_document)
    except (ValueError, dbapi.Error) as error:
        abort(400, description=str(error))
    if not records:
        abort(404, description='لا توجد حركة استلام وتسليم مطابقة')

    doc_type = 'handover_document' if is_document else 'handover_report'
    item_id = params['handover_id'] if is_document else json.dumps(
        params, sort_keys=True, ensure_ascii=False
    )
    if _is_repeatable_aggregate_report(doc_type, item_id):
        document_number, qr_code_url = None, None
    else:
        document_number, qr_code_url = _lookup_approved_report(item_id, doc_type)
    return render_template(
        'handover_report_print.html',
        records=records,
        columns=columns,
        report_title_text=title,
        report_date_gregorian=datetime.now().strftime('%Y/%m/%d'),
        report_date_hijri='1448/04/24',
        document_number=document_number or 'No.000000',
        qr_code_url=qr_code_url,
        hide_approve=bool(document_number),
        is_certified=bool(document_number),
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
        conn = dbapi.connect()
        conn.row_factory = dbapi.Row
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
    except (ValueError, dbapi.Error) as error:
        abort(400, description=str(error))

    item_id = json.dumps(
        {'category': report_key, 'params': params},
        sort_keys=True, ensure_ascii=False
    )
    if _is_repeatable_aggregate_report('data_report', item_id):
        document_number, qr_code_url = None, None
    else:
        document_number, qr_code_url = _lookup_approved_report(item_id, 'data_report')
    if document_number:
        return redirect(url_for('reports.final_report', doc_number=document_number))
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
    doc_type, item_id = _maintenance_approval_identity(filters, order_id, orders)
    if _is_repeatable_aggregate_report(doc_type, item_id):
        document_number, qr_code_url = None, None
    else:
        document_number, qr_code_url = _lookup_approved_report(item_id, doc_type)
    if document_number:
        return redirect(url_for('reports.final_report', doc_number=document_number))
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
    data = (
        request.form.to_dict()
        if request.mimetype == 'multipart/form-data'
        else request.get_json(silent=True) or {}
    )
    if not isinstance(data, dict):
        return jsonify({'success': False, 'message': 'صيغة طلب الاعتماد غير صالحة'}), 400
    doc_type = data.get('doc_type', 'accident_single')
    item_id = str(data.get('item_id', '1'))
    approval_token = data.get('approval_token', '')
    action = data.get('action', 'approve')
    if action != 'approve':
        return jsonify({'success': False, 'message': 'إجراء اعتماد التقرير غير صالح'}), 400
    valid_doc_types = {
        'accidents_report', 'accident_single', 'drivers_report', 'driver_single_report',
        'data_report', 'vehicles_report', 'handover_report', 'handover_document',
        'maintenance_report', 'maintenance_order', 'workshop_memo', 'custody_clearance',
        'general_memo'
    }
    if not isinstance(doc_type, str) or doc_type not in valid_doc_types:
        return jsonify({'success': False, 'message': 'نوع التقرير غير صالح للاعتماد'}), 400
    if not isinstance(approval_token, str) or not re.fullmatch(r'[0-9a-f]{32}', approval_token):
        return jsonify({'success': False, 'message': 'انتهت صلاحية معاينة التقرير؛ أعد فتحه ثم حاول مرة أخرى'}), 400
    editable_values = None
    if 'editable_values' in data:
        try:
            editable_values = json.loads(data['editable_values'])
        except (TypeError, json.JSONDecodeError):
            return jsonify({'success': False, 'message': 'بيانات الحقول المعدلة غير صالحة'}), 400
        if (
            not isinstance(editable_values, list)
            or len(editable_values) > 200
            or any(not isinstance(value, str) for value in editable_values)
            or sum(len(value.encode('utf-8')) for value in editable_values) > 128 * 1024
        ):
            return jsonify({'success': False, 'message': 'تجاوزت بيانات التعديل الحد المسموح'}), 400

    init_report_counter_db()
    if doc_type == 'handover_document':
        if not item_id.isdigit():
            return jsonify({'success': False, 'message': 'رقم حركة الاستلام والتسليم غير صالح'}), 400
        try:
            handover_conn = get_db_connection()
            try:
                handover = handover_conn.execute(
                    """SELECT status, is_certified, document_number
                       FROM handovers WHERE id = ?""",
                    (item_id,)
                ).fetchone()
            finally:
                handover_conn.close()
        except dbapi.Error:
            current_app.logger.exception('Unable to check handover certification')
            return jsonify({'success': False, 'message': 'تعذر التحقق من حالة توثيق الحركة'}), 500
        if not handover:
            return jsonify({'success': False, 'message': 'حركة الاستلام والتسليم المطلوبة غير موجودة'}), 404
        if handover['is_certified']:
            existing_number = handover['document_number']
            if not existing_number:
                current_app.logger.error(
                    'Certified handover %s is missing its document number', item_id
                )
                return jsonify({'success': False, 'message': 'بيانات التوثيق المعتمد غير مكتملة'}), 500
            return jsonify({
                'success': False,
                'already_finalized': True,
                'doc_number': existing_number,
                'final_url': url_for(
                    'reports.final_report', doc_number=existing_number, _external=True
                ),
                'message': 'تم اعتماد التقرير مسبقاً ولا يمكن تعديله.'
            }), 409
        if handover['status'] not in {'نشط', 'بانتظار التوثيق'}:
            return jsonify({
                'success': False,
                'message': 'لا يمكن توثيق حركة مؤرشفة؛ يمكن عرض التوثيق السابق فقط'
            }), 409

    try:
        token_record = reports_repository.get_by_token(approval_token)
    except SQLAlchemyError:
        current_app.logger.exception('Unable to check the report approval token')
        return jsonify({'success': False, 'message': 'تعذر التحقق من حالة اعتماد التقرير'}), 500
    if token_record and (token_record['doc_type'] != doc_type or str(token_record['item_id']) != item_id):
        return jsonify({'success': False, 'message': 'معرّف الاعتماد مستخدم لمعاينة تقرير مختلفة'}), 409
    if token_record:
        existing_number = token_record['doc_number']
        qr_filename = f"qr_{existing_number.replace('.', '_').replace('-', '_')}.png"
        return jsonify({
            'success': True,
            'doc_number': existing_number,
            'qr_code_url': f"/static/uploads/qrcodes/{qr_filename}",
            'public_url': url_for(
                'reports.public_view_document',
                doc_number=existing_number,
                token=approval_token,
                _external=True
            )
        })

    report_params = None
    report_data = None
    report_title = None
    accident_record_id = None
    accident_report_phase = None
    maintenance_filters = None
    maintenance_data = None
    maintenance_title = None
    maintenance_order_id = None
    maintenance_order_status = None
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
    handover_snapshot = None
    workshop_memo = None
    workshop_memo_items = None
    workshop_memo_id = None
    workshop_memo_approver = None
    custody_clearance = None
    custody_clearance_id = None
    custody_clearance_approver = None
    general_memo = None
    general_memo_id = None
    general_memo_approver = None
    if doc_type == 'accidents_report':
        try:
            report_params = json.loads(item_id)
        except (TypeError, json.JSONDecodeError):
            return jsonify({'success': False, 'message': 'بيانات فلاتر التقرير غير صالحة'}), 400
        if not isinstance(report_params, dict):
            return jsonify({'success': False, 'message': 'بيانات فلاتر التقرير غير صالحة'}), 400
        report_format = report_params.get('report_format', 'illustrated')
        if report_format not in {'normal', 'illustrated'}:
            return jsonify({'success': False, 'message': 'تنسيق تقرير الحوادث غير صالح'}), 400
        requested_orientation = report_params.get('orientation', 'portrait')
        if requested_orientation not in {'portrait', 'landscape'}:
            requested_orientation = 'portrait'
        report_params.update({'report_type': 'total', 'view': 'print'})
        report_params['orientation'] = (
            'landscape' if report_format == 'illustrated' else requested_orientation
        )
        report_data = _fetch_accidents(report_params)
        report_title = _accident_report_title(report_params)

    if doc_type == 'accident_single':
        try:
            accident_record_id, accident_report_phase = _parse_accident_report_identity(item_id)
        except ValueError as error:
            return jsonify({'success': False, 'message': str(error)}), 400
        report_params = {
            'report_type': 'single',
            'accident_id': accident_record_id,
            'view': 'print',
            'orientation': 'landscape',
            'report_format': 'illustrated'
        }
        report_data = _fetch_accidents(report_params)
        if not report_data:
            return jsonify({'success': False, 'message': 'الحادث المطلوب غير موجود'}), 404
        current_phase = _accident_report_phase(report_data[0])
        if accident_report_phase and accident_report_phase != current_phase:
            return jsonify({
                'success': False,
                'message': 'تغيرت حالة الحادث منذ فتح المعاينة؛ أعد فتح التقرير قبل اعتماده'
            }), 409
        accident_report_phase = current_phase
        item_id = _accident_report_identity(report_data[0])
        report_title = _accident_single_report_title(report_data[0])

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
        except (KeyError, TypeError, json.JSONDecodeError, ValueError, dbapi.Error):
            return jsonify({'success': False, 'message': 'بيانات التقرير غير صالحة'}), 400
        if not data_report_rows:
            return jsonify({'success': False, 'message': 'لا توجد بيانات مطابقة لاعتماد التقرير'}), 404
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
        except (TypeError, json.JSONDecodeError, ValueError, dbapi.Error):
            return jsonify({'success': False, 'message': 'بيانات تقرير المركبة غير صالحة'}), 400
        if not vehicle_report_data:
            return jsonify({'success': False, 'message': 'لا توجد مركبات مطابقة لاعتماد التقرير'}), 404
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
        except (TypeError, json.JSONDecodeError, ValueError, dbapi.Error):
            return jsonify({'success': False, 'message': 'بيانات تقرير الاستلام والتسليم غير صالحة'}), 400
        if not handover_records:
            return jsonify({'success': False, 'message': 'لا توجد حركة مطابقة لاعتماد التقرير'}), 404
    if doc_type in ['maintenance_report', 'maintenance_order']:
        if doc_type == 'maintenance_report':
            try:
                maintenance_filters = _maintenance_filters(json.loads(item_id))
            except (TypeError, json.JSONDecodeError):
                return jsonify({'success': False, 'message': 'بيانات فلاتر تقرير الصيانة غير صالحة'}), 400
            maintenance_data = _maintenance_orders(maintenance_filters)
        else:
            try:
                maintenance_identity = json.loads(item_id)
                if not isinstance(maintenance_identity, dict):
                    raise ValueError
                maintenance_order_id = int(maintenance_identity.get('order_id'))
                maintenance_order_status = maintenance_identity.get('status')
                if maintenance_order_status not in {'open', 'closed'}:
                    raise ValueError
            except (TypeError, ValueError, json.JSONDecodeError):
                return jsonify({'success': False, 'message': 'رقم أمر الصيانة غير صالح'}), 400
            maintenance_filters = _maintenance_filters({})
            maintenance_data = _maintenance_orders(maintenance_filters, maintenance_order_id)
            if maintenance_data and maintenance_data[0].get('status') != maintenance_order_status:
                return jsonify({
                    'success': False,
                    'message': 'تغيرت حالة أمر الصيانة منذ فتح المعاينة؛ أعد فتح التقرير قبل اعتماده'
                }), 409

        if not maintenance_data:
            return jsonify({'success': False, 'message': 'لا يوجد أمر صيانة مطابق للاعتماد'}), 404
        maintenance_title = _maintenance_report_title(
            maintenance_data, maintenance_filters, maintenance_order_id
        )
    if doc_type == 'workshop_memo':
        if not item_id.isdigit():
            return jsonify({'success': False, 'message': 'رقم مذكرة الورشة غير صالح'}), 400
        workshop_memo_id = int(item_id)
        try:
            with closing(dbapi.connect()) as connection:
                connection.row_factory = dbapi.Row
                memo_row = connection.execute(
                    """SELECT m.*, u.full_name AS approver_name
                       FROM workshop_memos m
                       LEFT JOIN users u ON u.id = ?
                       WHERE m.id = ?""",
                    (session.get('user_id'), workshop_memo_id)
                ).fetchone()
            if not memo_row:
                return jsonify({'success': False, 'message': 'مذكرة الورشة غير موجودة'}), 404
            if memo_row['status'] != 'مسودة':
                return jsonify({'success': False, 'message': 'المذكرة لم تعد مسودة قابلة للاعتماد'}), 409
            workshop_memo = dict(memo_row)
            workshop_memo_items = json.loads(workshop_memo.get('items_json') or '[]')
            if not isinstance(workshop_memo_items, list) or not workshop_memo_items:
                return jsonify({'success': False, 'message': 'لا تحتوي المذكرة على مواد صالحة للاعتماد'}), 400
            workshop_memo_approver = (
                workshop_memo.get('approver_name') or session.get('username') or 'غير محدد'
            )
            report_title = workshop_memo.get('subject') or 'مذكرة طلب مواد لزوم صيانة المعدات والمركبات'
        except (dbapi.Error, TypeError, json.JSONDecodeError):
            current_app.logger.exception('Unable to load workshop memo for approval')
            return jsonify({'success': False, 'message': 'تعذر تحميل مذكرة الورشة للاعتماد'}), 500

    if doc_type == 'custody_clearance':
        if not item_id.isdigit():
            return jsonify({'success': False, 'message': 'رقم نموذج إخلاء العهدة غير صالح'}), 400
        custody_clearance_id = int(item_id)
        try:
            with closing(dbapi.connect()) as connection:
                connection.row_factory = dbapi.Row
                row = connection.execute(
                    """SELECT c.*, u.full_name AS approver_name
                       FROM custody_clearances c
                       LEFT JOIN users u ON u.id = ?
                       WHERE c.id = ?""",
                    (session.get('user_id'), custody_clearance_id)
                ).fetchone()
            if not row:
                return jsonify({'success': False, 'message': 'نموذج إخلاء العهدة غير موجود'}), 404
            if row['status'] != 'مسودة':
                return jsonify({'success': False, 'message': 'نموذج إخلاء العهدة لم يعد مسودة قابلة للاعتماد'}), 409
            custody_clearance = dict(row)
            custody_clearance['data'] = json.loads(custody_clearance.get('data_json') or '{}')
            if not isinstance(custody_clearance['data'], dict):
                return jsonify({'success': False, 'message': 'بيانات نموذج إخلاء العهدة غير صالحة'}), 400
            required_fields = ('person_name', 'job_title', 'national_id', 'department', 'clearance_date')
            if any(not custody_clearance['data'].get(field) for field in required_fields):
                return jsonify({'success': False, 'message': 'أكمل بيانات الشخص الأساسية قبل اعتماد النموذج'}), 400
            custody_clearance_approver = (
                custody_clearance.get('approver_name') or session.get('username') or 'غير محدد'
            )
            report_title = 'نموذج إخلاء طرف عهدة المركبات والمعدات'
        except (dbapi.Error, TypeError, json.JSONDecodeError):
            current_app.logger.exception('Unable to load custody clearance for approval')
            return jsonify({'success': False, 'message': 'تعذر تحميل نموذج إخلاء العهدة للاعتماد'}), 500

    if doc_type == 'general_memo':
        if not item_id.isdigit():
            return jsonify({'success': False, 'message': 'رقم المذكرة غير صالح'}), 400
        general_memo_id = int(item_id)
        try:
            with closing(dbapi.connect()) as connection:
                connection.row_factory = dbapi.Row
                row = connection.execute(
                    """SELECT m.*, u.full_name AS approver_name
                       FROM general_memos m
                       LEFT JOIN users u ON u.id = ?
                       WHERE m.id = ?""",
                    (session.get('user_id'), general_memo_id)
                ).fetchone()
            if not row:
                return jsonify({'success': False, 'message': 'المذكرة غير موجودة'}), 404
            if row['status'] != 'مسودة':
                return jsonify({'success': False, 'message': 'المذكرة لم تعد مسودة قابلة للاعتماد'}), 409
            general_memo = dict(row)
            general_memo['data'] = json.loads(general_memo.get('data_json') or '{}')
            if not isinstance(general_memo['data'], dict):
                return jsonify({'success': False, 'message': 'بيانات المذكرة غير صالحة'}), 400
            memo_options = general_memo['data'].get('field_options', {})
            required_fields = ('recipient', 'subject', 'body')
            if any(
                memo_options.get(field, {}).get('included', True)
                and not general_memo['data'].get(field)
                for field in required_fields
            ):
                return jsonify({'success': False, 'message': 'أكمل التوجيه والموضوع والمتن قبل اعتماد المذكرة'}), 400
            general_memo_approver = (
                general_memo.get('approver_name') or session.get('username') or 'غير محدد'
            )
            report_title = (
                general_memo['data'].get('document_title') or 'مذكرة رسمية'
            ) or 'مذكرة رسمية'
        except (dbapi.Error, TypeError, json.JSONDecodeError):
            current_app.logger.exception('Unable to load general memo for approval')
            return jsonify({'success': False, 'message': 'تعذر تحميل المذكرة للاعتماد'}), 500

    uploaded_files = request.files if request.mimetype == 'multipart/form-data' else {}
    if uploaded_files and doc_type not in {
        'accident_single', 'maintenance_report', 'maintenance_order'
    }:
        return jsonify({
            'success': False,
            'message': 'رفع الملفات غير متاح لنوع التقرير المحدد'
        }), 400

    maintenance_photo_updates = {}
    maintenance_photo_paths = []
    try:
        if doc_type == 'accident_single':
            legacy_item_id = accident_record_id if accident_report_phase == 'open' else None
            existing_document = reports_repository.find_finalized(
                doc_type, [item_id, legacy_item_id]
            )
        elif _is_repeatable_aggregate_report(doc_type, item_id):
            existing_document = None
        else:
            existing_document = reports_repository.find_finalized(doc_type, [item_id])
    except SQLAlchemyError:
        current_app.logger.exception('Unable to check for an existing finalized report')
        return jsonify({
            'success': False,
            'message': 'تعذر التحقق من وجود تقرير معتمد سابق'
        }), 500

    if existing_document:
        existing_number = existing_document['doc_number']
        return jsonify({
            'success': False,
            'already_finalized': True,
            'doc_number': existing_number,
            'final_url': url_for(
                'reports.final_report', doc_number=existing_number, _external=True
            ),
            'message': 'تم اعتماد التقرير مسبقاً ولا يمكن تعديله.'
        }), 409

    if uploaded_files and doc_type in {'maintenance_report', 'maintenance_order'}:
        try:
            maintenance_photo_updates, maintenance_photo_paths = (
                _save_maintenance_report_photos(maintenance_data, uploaded_files)
            )
        except ValueError as error:
            return jsonify({'success': False, 'message': str(error)}), 400
        except OSError:
            current_app.logger.exception('Unable to save maintenance report photos')
            return jsonify({
                'success': False,
                'message': 'تعذر حفظ صور تقرير الصيانة'
            }), 500
        for order in maintenance_data:
            order.update(maintenance_photo_updates.get(order['id'], {}))

    # 1. توليد الرقم المرجعي الموحد والمتسلسل (مثل No.000001)
    doc_number = generate_reference_number()
    
    archived_report_path = None
    archived_report_url = None
    final_pdf_path = None
    final_pdf_url = None
    accident_image_paths = []
    accident_image_sources = {}
    archive_suffix = uuid.uuid4().hex
    if doc_type == 'accident_single':
        try:
            accident_image_sources, accident_image_paths = _save_accident_report_images(
                report_data[0], uploaded_files, doc_number
            )
        except ValueError as error:
            return jsonify({'success': False, 'message': str(error)}), 400
    # QR always resolves to the immutable final-report page, never to preview.
    try:
        qr_url = generate_document_qr(
            doc_number, doc_type, item_id, access_token=approval_token
        )
    except storage.StorageError:
        current_app.logger.exception('Unable to store report QR code')
        _discard_files(*accident_image_paths, *maintenance_photo_paths)
        return jsonify({
            'success': False,
            'message': 'تعذر حفظ رمز QR في التخزين السحابي'
        }), 503

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
            orientation=(
                'landscape'
                if report_params.get('report_format', 'illustrated') == 'illustrated'
                else report_params.get('orientation', 'portrait')
            ),
            report_format=report_params.get('report_format', 'illustrated'),
            allow_orientation=report_params.get('report_format', 'illustrated') != 'illustrated',
            filter_type=report_params.get('filter_type', 'all'),
            report_type='single' if doc_type == 'accident_single' else 'total',
            accident_image_sources=accident_image_sources,
            is_finalized=True
        )
        archive_filename = f"report_{doc_number.replace('.', '_').replace('-', '_')}_{archive_suffix}.html"
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
            is_certified=False,
            is_finalized=True,
            type_titles=MAINTENANCE_TYPE_TITLES
        )
        archive_filename = f"report_{doc_number.replace('.', '_').replace('-', '_')}_{archive_suffix}.html"
        archived_report_path = os.path.join(REPORTS_DIR, archive_filename)
        with open(archived_report_path, 'w', encoding='utf-8') as archive_file:
            archive_file.write(html)
        if handover_is_document:
            handover_snapshot = html
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
        archive_filename = f"report_{doc_number.replace('.', '_').replace('-', '_')}_{archive_suffix}.html"
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
        archive_filename = f"report_{doc_number.replace('.', '_').replace('-', '_')}_{archive_suffix}.html"
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
        archive_filename = f"report_{doc_number.replace('.', '_').replace('-', '_')}_{archive_suffix}.html"
        archived_report_path = os.path.join(REPORTS_DIR, archive_filename)
        with open(archived_report_path, 'w', encoding='utf-8') as archive_file:
            archive_file.write(html)
    elif doc_type in {'handover_report', 'handover_document'}:
        html = render_template(
            'handover_report_print.html',
            records=handover_records,
            columns=handover_columns,
            report_title_text=handover_report_title,
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
            is_certified=False,
            report_params=handover_report_params
        )
        archive_filename = f"report_{doc_number.replace('.', '_').replace('-', '_')}_{archive_suffix}.html"
        archived_report_path = os.path.join(REPORTS_DIR, archive_filename)
        with open(archived_report_path, 'w', encoding='utf-8') as archive_file:
            archive_file.write(html)
    elif doc_type == 'workshop_memo':
        workshop_memo.update({
            'status': 'معتمدة',
            'reference_number': doc_number,
            'approved_by_name': workshop_memo_approver,
            'approved_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'items': workshop_memo_items,
        })
        html = render_template(
            'workshop_request_form.html',
            memo=workshop_memo,
            items=workshop_memo_items,
            is_finalized=True,
            document_number=doc_number,
            qr_code_url=qr_url,
            report_title_text=report_title,
            report_date_gregorian=datetime.now().strftime('%Y/%m/%d'),
            report_date_hijri='',
            hide_approve=True,
            approval_doc_type=doc_type,
            approval_item_id=item_id,
            orientation='portrait',
            allow_orientation=False,
        )
        archive_filename = (
            f"report_{doc_number.replace('.', '_').replace('-', '_')}_{archive_suffix}.html"
        )
        archived_report_path = os.path.join(REPORTS_DIR, archive_filename)
        with open(archived_report_path, 'w', encoding='utf-8') as archive_file:
            archive_file.write(html)
    elif doc_type == 'custody_clearance':
        html = render_template(
            'custody_clearance_form.html',
            clearance_data=custody_clearance['data'],
            clearance_id=custody_clearance_id,
            is_finalized=True,
            document_number=doc_number,
            qr_code_url=qr_url,
            report_date_gregorian=datetime.now().strftime('%Y/%m/%d'),
            report_date_hijri='',
            show_hijri_date=False,
            hide_approve=True,
            approval_doc_type=doc_type,
            approval_item_id=item_id,
            orientation='portrait',
            allow_orientation=False,
        )
        archive_filename = (
            f"report_{doc_number.replace('.', '_').replace('-', '_')}_{archive_suffix}.html"
        )
        archived_report_path = os.path.join(REPORTS_DIR, archive_filename)
        with open(archived_report_path, 'w', encoding='utf-8') as archive_file:
            archive_file.write(html)
    elif doc_type == 'general_memo':
        html = render_template(
            'general_memo_form.html',
            memo_data=general_memo['data'],
            memo_id=general_memo_id,
            is_finalized=True,
            document_number=doc_number,
            qr_code_url=qr_url,
            suppress_reference_number=True,
            report_date_gregorian=datetime.now().strftime('%Y/%m/%d'),
            report_date_hijri='',
            show_hijri_date=False,
            hide_approve=True,
            approval_doc_type=doc_type,
            approval_item_id=item_id,
            orientation='portrait',
            allow_orientation=False,
        )
        archive_filename = (
            f"report_{doc_number.replace('.', '_').replace('-', '_')}_{archive_suffix}.html"
        )
        archived_report_path = os.path.join(REPORTS_DIR, archive_filename)
        with open(archived_report_path, 'w', encoding='utf-8') as archive_file:
            archive_file.write(html)
    
    try:
        html = _apply_editable_values(html, editable_values)
    except ValueError as error:
        db_session.rollback()
        _discard_files(
            archived_report_path, qr_url,
            *accident_image_paths, *maintenance_photo_paths
        )
        current_app.logger.warning(
            'Rejected report approval with mismatched editable fields for %s/%s',
            doc_type, item_id
        )
        return jsonify({'success': False, 'message': str(error)}), 409

    html = re.sub(
        r'\scontenteditable\s*=\s*(["\'])true\1',
        ' contenteditable="false"',
        html,
        flags=re.IGNORECASE
    )
    if archived_report_path:
        with open(archived_report_path, 'w', encoding='utf-8') as archive_file:
            archive_file.write(html)
    if handover_snapshot is not None:
        handover_snapshot = html

    final_pdf_path = os.path.join(
        REPORTS_DIR,
        f"report_{doc_number.replace('.', '_').replace('-', '_')}_{archive_suffix}.pdf"
    )
    try:
        render_report_pdf(html, final_pdf_path, request.url_root)
    except RuntimeError as error:
        current_app.logger.exception('WeasyPrint runtime is not ready')
        for generated_path in (
            archived_report_path, final_pdf_path, *accident_image_paths,
            qr_url,
            *maintenance_photo_paths
        ):
            if generated_path and storage.is_url(generated_path):
                storage.delete_file(generated_path)
            elif generated_path and os.path.isfile(generated_path):
                os.remove(generated_path)
        return jsonify({
            'success': False,
            'message': f'تعذر إنشاء PDF: {error}'
        }), 503
    except Exception:
        current_app.logger.exception('Unable to render finalized report PDF')
        for generated_path in (
            archived_report_path, final_pdf_path, *accident_image_paths,
            qr_url,
            *maintenance_photo_paths
        ):
            if generated_path and storage.is_url(generated_path):
                storage.delete_file(generated_path)
            elif generated_path and os.path.isfile(generated_path):
                os.remove(generated_path)
        return jsonify({
            'success': False,
            'message': 'تعذر إنشاء PDF للتقرير النهائي. تحقق من إعداد WeasyPrint والخطوط.'
        }), 500

    try:
        final_pdf_url = _upload_report_artifact(
            final_pdf_path, 'reports/pdf', 'application/pdf'
        )
        archived_report_url = _upload_report_artifact(
            archived_report_path, 'reports/html', 'text/html; charset=utf-8'
        )
    except (OSError, storage.StorageError):
        current_app.logger.exception('Unable to persist finalized report artifacts')
        _discard_files(
            archived_report_path, final_pdf_path, archived_report_url, final_pdf_url,
            qr_url, *accident_image_paths, *maintenance_photo_paths
        )
        return jsonify({
            'success': False,
            'message': 'تعذر حفظ ملفات التقرير في التخزين السحابي'
        }), 503

    # 3. تسجيل المستند المعتمد في قاعدة البيانات

    now_text = "to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')"
    db_session = SessionLocal()
    try:
        # serialises concurrent approvals of the same item (replaces BEGIN IMMEDIATE)
        db_session.execute(
            text('SELECT pg_advisory_xact_lock(hashtext(:key))'),
            {'key': f'{doc_type}:{item_id}'}
        )
        if doc_type == 'accident_single':
            current_accident = db_session.execute(
                text('SELECT status, closed_at FROM accidents WHERE CAST(id AS TEXT) = :id'),
                {'id': str(accident_record_id)}
            ).first()
            current_phase = (
                'closed'
                if current_accident and (
                    str(current_accident[0] or '').strip().lower() == 'closed'
                    or current_accident[1]
                )
                else 'open'
            )
            if not current_accident or current_phase != accident_report_phase:
                db_session.rollback()
                _discard_files(
                    archived_report_path, final_pdf_path, *accident_image_paths,
                    archived_report_url, final_pdf_url, qr_url, *maintenance_photo_paths
                )
                return jsonify({
                    'success': False,
                    'message': 'تغيرت حالة الحادث أثناء تجهيز التقرير؛ أعد فتح التقرير قبل اعتماده'
                }), 409

        if doc_type in {'maintenance_report', 'maintenance_order'}:
            for order in maintenance_data:
                current_order = db_session.get(MaintenanceOrder, order['id'])
                if not current_order or current_order.status != order.get('status'):
                    db_session.rollback()
                    _discard_files(
                        archived_report_path, final_pdf_path, *accident_image_paths,
                        archived_report_url, final_pdf_url, qr_url, *maintenance_photo_paths
                    )
                    return jsonify({
                        'success': False,
                        'message': 'تغيرت حالة أمر الصيانة أثناء تجهيز التقرير؛ أعد فتح التقرير قبل اعتماده'
                    }), 409

        for maintenance_id, photos in maintenance_photo_updates.items():
            order_row = db_session.get(MaintenanceOrder, maintenance_id)
            if order_row is None:
                raise RuntimeError(f'تعذر حفظ صور تقرير أمر الصيانة {maintenance_id}')
            for field_name, value in photos.items():
                if field_name not in {'photo_before', 'photo_after', 'other_attachments'}:
                    raise RuntimeError(f'حقل صور غير مدعوم: {field_name}')
                setattr(order_row, field_name, value)
        db_session.flush()

        if doc_type == 'accident_single':
            legacy_item_id = accident_record_id if accident_report_phase == 'open' else None
            current_finalized = reports_repository.find_finalized(
                doc_type, [item_id, legacy_item_id], db_session
            )
        elif _is_repeatable_aggregate_report(doc_type, item_id):
            current_finalized = None
        else:
            current_finalized = reports_repository.find_finalized(doc_type, [item_id], db_session)
        current_number = current_finalized['doc_number'] if current_finalized else None
        if current_number is not None:
            db_session.rollback()
            _discard_files(
                archived_report_path, final_pdf_path, *accident_image_paths,
                archived_report_url, final_pdf_url, qr_url, *maintenance_photo_paths
            )
            if current_number:
                return jsonify({
                    'success': False,
                    'already_finalized': True,
                    'doc_number': current_number,
                    'final_url': url_for(
                        'reports.final_report', doc_number=current_number, _external=True
                    ),
                    'message': 'تم اعتماد التقرير مسبقاً ولا يمكن تعديله.'
                }), 409
            return jsonify({
                'success': False,
                'message': 'تغيرت حالة اعتماد التقرير؛ أعد فتح المعاينة وحاول مرة أخرى'
            }), 409

        if doc_type == 'handover_document':
            handover = db_session.execute(
                text("""SELECT status, is_certified, document_number
                        FROM handovers WHERE CAST(id AS TEXT) = :id"""),
                {'id': str(item_id)}
            ).first()
            if not handover:
                db_session.rollback()
                _discard_files(
                    archived_report_path, final_pdf_path, archived_report_url,
                    final_pdf_url, qr_url, *maintenance_photo_paths
                )
                return jsonify({'success': False, 'message': 'حركة الاستلام والتسليم المطلوبة غير موجودة'}), 404
            if handover[1]:
                db_session.rollback()
                _discard_files(
                    archived_report_path, final_pdf_path, archived_report_url,
                    final_pdf_url, qr_url, *maintenance_photo_paths
                )
                existing_number = handover[2]
                if not existing_number:
                    return jsonify({
                        'success': False,
                        'message': 'الحركة معتمدة لكن رقم المستند غير متاح؛ يرجى مراجعة الدعم الفني'
                    }), 500
                _, existing_qr_url = reports_repository.lookup_approved_report(
                    str(item_id), 'handover_document'
                )
                return jsonify({
                    'success': True,
                    'doc_number': existing_number,
                    'qr_code_url': existing_qr_url,
                    'public_url': url_for(
                        'reports.public_view_document', doc_number=existing_number, _external=True
                    )
                })
            if handover[0] not in {'نشط', 'بانتظار التوثيق'}:
                db_session.rollback()
                _discard_files(
                    archived_report_path, final_pdf_path, archived_report_url,
                    final_pdf_url, qr_url, *maintenance_photo_paths
                )
                return jsonify({
                    'success': False,
                    'message': 'لا يمكن توثيق حركة مؤرشفة؛ يمكن عرض التوثيق السابق فقط'
                }), 409

        memo_approvals = {
            'workshop_memo': (
                'workshop_memos', workshop_memo_id if doc_type == 'workshop_memo' else None,
                workshop_memo_approver if doc_type == 'workshop_memo' else None,
                'تعذر تثبيت اعتماد مذكرة الورشة'
            ),
            'custody_clearance': (
                'custody_clearances', custody_clearance_id if doc_type == 'custody_clearance' else None,
                custody_clearance_approver if doc_type == 'custody_clearance' else None,
                'تعذر تثبيت اعتماد إخلاء العهدة'
            ),
            'general_memo': (
                'general_memos', general_memo_id if doc_type == 'general_memo' else None,
                general_memo_approver if doc_type == 'general_memo' else None,
                'تعذر تثبيت اعتماد المذكرة'
            ),
        }
        if doc_type in memo_approvals:
            memo_table, memo_id, approver_name, failure_message = memo_approvals[doc_type]
            # memo_table is one of the three literals above, never user input
            result = db_session.execute(
                text(f"""UPDATE {memo_table}
                         SET status = 'معتمدة', reference_number = :ref,
                             approved_by = :user_id, approved_by_name = :approver,
                             approved_at = {now_text}, updated_at = {now_text}
                         WHERE id = :id AND status = 'مسودة'"""),
                {
                    'ref': doc_number, 'user_id': session.get('user_id'),
                    'approver': approver_name, 'id': memo_id,
                }
            )
            if result.rowcount != 1:
                raise RuntimeError(failure_message)

        reports_repository.add_approved_document(
            db_session, doc_number=doc_number, doc_type=doc_type, item_id=item_id,
            file_path=archived_report_url or qr_url, approval_token=approval_token,
            final_pdf_path=final_pdf_url, qr_code_path=qr_url
        )

        def _add_generated(module_name, report_type, title, template_key, parameters):
            reports_repository.add_generated_report(
                db_session, doc_number=doc_number, module_name=module_name,
                report_type=report_type, title=title, template_key=template_key,
                parameters=parameters, report_path=archived_report_url, qr_path=qr_url
            )

        if doc_type in {'accidents_report', 'accident_single'}:
            _add_generated(
                'accidents', report_params.get('report_format', 'illustrated'),
                report_title, 'accidents', report_params
            )
        elif doc_type in ['maintenance_report', 'maintenance_order']:
            _add_generated(
                'maintenance', doc_type, maintenance_title, 'maintenance',
                maintenance_filters if doc_type == 'maintenance_report' else {
                    'order_id': maintenance_order_id,
                    'status': maintenance_order_status
                }
            )
        elif doc_type in ['drivers_report', 'driver_single_report']:
            _add_generated('drivers', doc_type, driver_report_title, 'drivers', driver_report_params)
        elif doc_type == 'data_report':
            _add_generated(
                data_report_category, data_report_params.get('report_type', 'all'),
                data_report_title, 'data_report', data_report_params
            )
        elif doc_type == 'vehicles_report':
            _add_generated(
                'vehicles', vehicle_report_identity['report_type'], vehicle_report_title,
                'vehicles_report', vehicle_report_identity
            )
        elif doc_type in {'handover_report', 'handover_document'}:
            _add_generated(
                'handover',
                'documentation' if handover_is_document else handover_report_params['report_type'],
                handover_report_title, 'handover_report', handover_report_params
            )
            if handover_is_document:
                result = db_session.execute(
                    text("""UPDATE handovers
                            SET status = CASE WHEN status = 'بانتظار التوثيق' THEN 'مؤرشف' ELSE status END,
                                is_certified = 1, certified_at = :certified_at, certified_by = :certified_by,
                                document_number = :doc_number, report_data = :report_data,
                                report_file_path = :report_path
                            WHERE CAST(id AS TEXT) = :id AND status IN ('نشط', 'بانتظار التوثيق')
                              AND is_certified = 0"""),
                    {
                        'certified_at': datetime.now().isoformat(timespec='seconds'),
                        'certified_by': session.get('full_name') or session.get('username') or 'غير محدد',
                        'doc_number': doc_number, 'report_data': handover_snapshot,
                        'report_path': archived_report_url, 'id': str(item_id),
                    }
                )
                if result.rowcount != 1:
                    raise RuntimeError('تعذر تثبيت توثيق الحركة')
        elif doc_type == 'workshop_memo':
            _add_generated(
                'workshop', 'workshop_memo', report_title, 'workshop_request_form',
                {'memo_id': workshop_memo_id}
            )
        elif doc_type == 'custody_clearance':
            _add_generated(
                'custody', 'custody_clearance', report_title, 'custody_clearance_form',
                {'clearance_id': custody_clearance_id, 'data': custody_clearance['data']}
            )
        elif doc_type == 'general_memo':
            _add_generated(
                'reports', 'general_memo', report_title, 'general_memo_form',
                {'memo_id': general_memo_id, 'data': general_memo['data']}
            )

        reports_repository.finalize_generated_report(
            db_session, doc_number, final_pdf_url, qr_url
        )

        # ربط الرقم المرجعي بسجل الحوادث إذا كان نوع التقرير حادث سير
        if doc_type in ['accident_single', 'accidents']:
            accident_item_id = str(accident_record_id if doc_type == 'accident_single' else item_id)
            try:
                with db_session.begin_nested():
                    db_session.execute(
                        text("""UPDATE accidents SET document_number = :doc_number
                                WHERE CAST(id AS TEXT) = :ref OR accident_number = :ref"""),
                        {'doc_number': doc_number, 'ref': accident_item_id}
                    )
            except SQLAlchemyError:
                current_app.logger.warning('Unable to link report %s to accident %s', doc_number, accident_item_id)

        db_session.commit()
    except Exception:
        db_session.rollback()
        current_app.logger.exception('Unable to persist finalized report')
        _discard_files(
            archived_report_path, final_pdf_path, *accident_image_paths,
            archived_report_url, final_pdf_url, qr_url, *maintenance_photo_paths
        )
        return jsonify({'success': False, 'message': 'تعذر حفظ التقرير المعتمد'}), 500
    finally:
        db_session.close()

    _discard_files(archived_report_path, final_pdf_path)
    return jsonify({
        'success': True,
        'doc_number': doc_number,
        'qr_code_url': qr_url,
        'report_url': url_for(
            'reports.public_view_document', doc_number=doc_number,
            token=approval_token, _external=True
        ),
        'public_url': url_for(
            'reports.public_view_document', doc_number=doc_number,
            token=approval_token, _external=True
        ),
        'pdf_url': url_for(
            'reports.public_view_pdf', doc_number=doc_number, token=approval_token
        ),
        'message': 'تم اعتماد الوثيقة وتوليد الرقم المرجعي والـ QR Code بنجاح'
    })


def _ensure_final_pdf(document):
    pdf_path = document.get('final_pdf_path')
    if pdf_path:
        try:
            pdf_data = _read_report_artifact(pdf_path)
            if not pdf_data.startswith(b'%PDF-'):
                raise ValueError('Stored report artifact is not a valid PDF')
            return io.BytesIO(pdf_data)
        except (FileNotFoundError, storage.StorageError, ValueError):
            current_app.logger.warning(
                'Stored PDF unavailable for report %s; regenerating from archived HTML',
                document.get('doc_number'),
                exc_info=True,
            )

    html_path = document.get('file_path')
    if not html_path:
        abort(404, description='ملف التقرير المعتمد غير متاح')

    generated_pdf = os.path.join(
        REPORTS_DIR,
        f"legacy_final_{document['doc_number'].replace('.', '_')}_{uuid.uuid4().hex}.pdf"
    )
    pdf_url = None
    try:
        html = _read_report_artifact(html_path).decode('utf-8')
        render_report_pdf(html, generated_pdf, request.url_root)
        with open(generated_pdf, 'rb') as pdf_file:
            pdf_bytes = pdf_file.read()
        pdf_url = _upload_report_artifact(
            generated_pdf, 'reports/pdf', 'application/pdf'
        )
        reports_repository.set_final_pdf(document['doc_number'], pdf_url)
        return io.BytesIO(pdf_bytes)
    except RuntimeError as error:
        current_app.logger.exception(
            'WeasyPrint runtime is unavailable for legacy report %s',
            document['doc_number']
        )
        abort(503, description=str(error))
    except Exception:
        current_app.logger.exception(
            'Unable to create a PDF for legacy finalized report %s',
            document['doc_number']
        )
        if pdf_url:
            _discard_files(pdf_url)
        abort(500, description='تعذر تجهيز PDF للتقرير المعتمد')
    finally:
        if os.path.isfile(generated_pdf):
            os.remove(generated_pdf)


@reports_bp.route('/final/<doc_number>')
def final_report(doc_number):
    document = _finalized_document(doc_number)
    if not document:
        abort(404, description='التقرير النهائي غير موجود أو غير معتمد')
    try:
        pdf_path = _ensure_final_pdf(document)
    except Exception:
        current_app.logger.exception('Final PDF fallback activated for %s', doc_number)
        return render_template(
            'final_report.html',
            document=document,
            pdf_url=url_for('reports.final_report_pdf', doc_number=doc_number),
            pdf_download_url=url_for(
                'reports.final_report_pdf', doc_number=doc_number, download=1
            ),
            pdf_filename=f"{document.get('reference_number') or doc_number}.pdf",
            email_reports_enabled=(
                get_email_setting('email_reports_enabled', '1') == '1'
                and get_email_setting('smtp_enabled', '0') == '1'
            ),
            fallback_mode=True,
            fallback_message='تعذر توليد ملف PDF المباشر، تم توجيهك لصفحة التقرير القابلة للطباعة عبر المتصفح.',
            auto_print=True
        )
    return render_template(
        'final_report.html',
        document=document,
        pdf_url=url_for('reports.final_report_pdf', doc_number=doc_number),
        pdf_download_url=url_for(
            'reports.final_report_pdf', doc_number=doc_number, download=1
        ),
        pdf_filename=f"{document.get('reference_number') or doc_number}.pdf",
        email_reports_enabled=(
            get_email_setting('email_reports_enabled', '1') == '1'
            and get_email_setting('smtp_enabled', '0') == '1'
        ),
    )


@reports_bp.route('/final/<doc_number>/email', methods=['POST'])
def email_final_report(doc_number):
    if session.get('role') != 'admin':
        return jsonify({'status': 'error', 'message': 'يجب تسجيل الدخول بصلاحية مدير لإرسال التقرير'}), 401
    if (
        get_email_setting('email_reports_enabled', '1') != '1'
        or get_email_setting('smtp_enabled', '0') != '1'
    ):
        return jsonify({'status': 'error', 'message': 'إرسال التقارير متوقف من إعدادات البريد'}), 403

    recipient = request.get_json(silent=True)
    recipient = str(recipient.get('recipient', '')).strip() if isinstance(recipient, dict) else ''
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', recipient):
        return jsonify({'status': 'error', 'message': 'أدخل عنوان بريد مستلماً صالحاً'}), 400

    document = _finalized_document(doc_number)
    if not document:
        abort(404, description='التقرير النهائي غير موجود أو غير معتمد')
    approval_token = document.get('approval_token')
    if not approval_token:
        return jsonify({'status': 'error', 'message': 'لا يتوفر رابط مشاركة آمن لهذا التقرير'}), 409

    try:
        report_url = get_public_base_url() + url_for(
            'reports.public_view_document',
            doc_number=doc_number,
            token=approval_token,
        )
        reference_number = document.get('reference_number') or doc_number
        send_email(
            f'تقرير SEMACOM المعتمد - {reference_number}',
            f'تمت مشاركة التقرير المعتمد رقم {reference_number} معك.\n\n'
            f'عرض التقرير وتنزيل نسخة PDF:\n{report_url}',
            recipient,
        )
    except EmailConfigurationError as error:
        return jsonify({'status': 'error', 'message': str(error)}), 400
    except smtplib.SMTPAuthenticationError:
        current_app.logger.exception('SMTP authentication failed while emailing report %s', doc_number)
        return jsonify({'status': 'error', 'message': 'فشل تسجيل الدخول إلى خادم البريد'}), 502
    except (smtplib.SMTPException, TimeoutError, OSError, dbapi.Error):
        current_app.logger.exception('Unable to email finalized report %s', doc_number)
        return jsonify({'status': 'error', 'message': 'تعذر إرسال التقرير؛ تحقق من إعدادات البريد وحاول مجددًا'}), 502

    return jsonify({'status': 'success', 'message': f'تم إرسال رابط التقرير إلى {recipient}'}), 200


@reports_bp.route('/final/<doc_number>/pdf')
def final_report_pdf(doc_number):
    document = _finalized_document(doc_number)
    if not document:
        abort(404, description='التقرير النهائي غير موجود أو غير معتمد')

    pdf_path = _ensure_final_pdf(document)
    reference_number = document.get('reference_number') or doc_number
    return send_file(
        pdf_path,
        mimetype='application/pdf',
        as_attachment=request.args.get('download') == '1',
        download_name=f'{reference_number}.pdf'
    )


def _valid_public_report_token(doc_number, access_token):
    if not isinstance(access_token, str) or not re.fullmatch(r'[0-9a-f]{32}', access_token):
        return False
    try:
        return reports_repository.token_is_valid(doc_number, access_token)
    except SQLAlchemyError:
        current_app.logger.exception('Unable to validate public report access')
        abort(500, description='تعذر التحقق من رابط التقرير')


@reports_bp.route('/public/view/<doc_number>/pdf')
def public_view_pdf(doc_number):
    document = _finalized_document(doc_number)
    access_token = request.args.get('token', '')
    if not document or not _valid_public_report_token(doc_number, access_token):
        abort(404, description='التقرير النهائي غير موجود أو رابط المشاركة غير صالح')

    pdf_path = _ensure_final_pdf(document)
    reference_number = document.get('reference_number') or doc_number
    return send_file(
        pdf_path,
        mimetype='application/pdf',
        as_attachment=request.args.get('download') == '1',
        download_name=f'{reference_number}.pdf'
    )


@reports_bp.route('/public/view/<doc_number>')
def public_view_document(doc_number):
    """Serve token-authorized QR links and preserve legacy report redirects."""
    document = _finalized_document(doc_number)
    if document:
        access_token = request.args.get('token', '')
        if access_token:
            if not _valid_public_report_token(doc_number, access_token):
                abort(404, description='التقرير النهائي غير موجود أو رابط المشاركة غير صالح')
            pdf_url = url_for(
                'reports.public_view_pdf', doc_number=doc_number, token=access_token
            )
            return render_template(
                'final_report.html',
                document=document,
                pdf_url=pdf_url,
                pdf_download_url=url_for(
                    'reports.public_view_pdf', doc_number=doc_number,
                    token=access_token, download=1
                ),
                pdf_filename=f"{document.get('reference_number') or doc_number}.pdf",
                email_reports_enabled=(
                    get_email_setting('email_reports_enabled', '1') == '1'
                    and get_email_setting('smtp_enabled', '0') == '1'
                ),
                final_page_url=url_for(
                    'reports.public_view_document', doc_number=doc_number,
                    token=access_token, _external=True
                )
            )
        return redirect(url_for('reports.final_report', doc_number=doc_number))

    if request.args.get('token'):
        abort(404, description='التقرير النهائي غير موجود أو رابط المشاركة غير صالح')

    try:
        legacy_document = reports_repository.get_document(doc_number)
        result = (
            (legacy_document['doc_type'], legacy_document['item_id'], legacy_document['file_path'])
            if legacy_document else None
        )
    except SQLAlchemyError:
        current_app.logger.exception('Unable to load an approved public report')
        return '<h3>تعذر تحميل التقرير المعتمد حالياً.</h3>', 500
    
    if result:
        doc_type, item_id, file_path = result
        if doc_type == 'workshop_memo':
            return redirect(url_for('reports.final_report', doc_number=doc_number))
        if doc_type == 'handover_document' and str(item_id).isdigit():
            return redirect(url_for(
                'reports.handover_reports', view='document', handover_id=item_id
            ))
        if storage.is_url(file_path) and storage.object_path_from_url(file_path):
            return redirect(file_path)
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
            try:
                identity = json.loads(item_id)
                if isinstance(identity, dict):
                    order_id = identity['order_id']
                elif isinstance(identity, int):
                    order_id = identity
                else:
                    raise ValueError
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                return "<h3>تعذر استعادة أمر الصيانة من التقرير المعتمد.</h3>", 400
            return redirect(url_for('reports.maintenance_reports', view='print', order_id=order_id))
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
            try:
                accident_id, _ = _parse_accident_report_identity(item_id)
            except ValueError:
                accident_id = item_id
            return redirect(url_for(
                'reports.accidents_reports',
                report_type='single',
                accident_id=accident_id,
                orientation='landscape'
            ))
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
        return reports_repository.file_path_for_number(doc_num)
    except Exception:
        return None


@reports_bp.route('/accidents', methods=['GET'])
def accidents_reports():
    """عرض وتصفية تقارير الحوادث من قاعدة البيانات مع دعم التقرير الفردي والكلي"""
    report_type = request.args.get('report_type', 'total')  # 'total' أو 'single'
    filter_type = request.args.get('filter_type', 'all')
    report_format = request.args.get('report_format', 'illustrated')
    if report_format not in {'normal', 'illustrated'}:
        report_format = 'illustrated'
    view_mode = request.args.get('view', '').strip()

    selected_month = request.args.get('month')
    selected_year = request.args.get('year')
    daily_date = request.args.get('daily_date')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    accident_id = request.args.get('accident_id', '').strip()

    default_orientation = 'portrait'
    orientation = request.args.get('orientation', default_orientation)
    if orientation not in {'portrait', 'landscape'}:
        orientation = default_orientation
    if report_format == 'illustrated':
        orientation = 'landscape'

    accidents_data = _fetch_accidents(request.args.to_dict())

    print_ctx = {
        'report_date_gregorian': datetime.now().strftime('%Y/%m/%d'),
        'report_date_hijri': '1448/04/24',
        'orientation': orientation,
        'report_format': report_format,
        'allow_orientation': report_format != 'illustrated',
        'filter_type': filter_type,
    }

    if report_type == 'single' or view_mode == 'print':
        single_accident = accidents_data[0] if accidents_data else {}
        is_filtered_report = report_type != 'single'
        report_item_id = json.dumps(request.args.to_dict(), sort_keys=True, ensure_ascii=False)
        approval_doc_type = 'accidents_report' if is_filtered_report else 'accident_single'
        approval_item_id = (
            report_item_id if is_filtered_report
            else _accident_report_identity(single_accident) if single_accident else ''
        )
        if _is_repeatable_aggregate_report(approval_doc_type, approval_item_id):
            doc_num, qr_url = None, None
        else:
            doc_num, qr_url = _lookup_approved_report(approval_item_id, approval_doc_type)
        if (
            not doc_num and not is_filtered_report and single_accident
            and _accident_report_phase(single_accident) == 'open'
        ):
            doc_num, qr_url = _lookup_approved_report(
                str(single_accident.get('id') or single_accident.get('accident_number') or ''),
                approval_doc_type
            )
        if doc_num:
            return redirect(url_for('reports.final_report', doc_number=doc_num))

        return render_template(
            'accidents_print.html',
            accidents=accidents_data,
            accident=single_accident,
            document_number=doc_num or 'No.000000',
            qr_code_url=qr_url,
            hide_approve=(not accidents_data or bool(doc_num)),
            approval_doc_type=approval_doc_type,
            approval_item_id=approval_item_id,
            report_title_text=(
                _accident_report_title(request.args)
                if is_filtered_report
                else _accident_single_report_title(single_accident)
            ),
            report_type='single' if report_type == 'single' else 'total',
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

@reports_bp.route('/general-memo', methods=['GET', 'POST'])
def general_memo_form():
    connection = None
    try:
        init_report_counter_db()
        connection = dbapi.connect()
        connection.row_factory = dbapi.Row
        connection.execute(
            """CREATE TABLE IF NOT EXISTS general_memos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reference_number TEXT UNIQUE,
                submission_key TEXT,
                status TEXT NOT NULL DEFAULT 'مسودة',
                data_json TEXT NOT NULL DEFAULT '{}',
                created_by INTEGER NOT NULL,
                created_by_name TEXT NOT NULL,
                approved_by INTEGER,
                approved_by_name TEXT,
                approved_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        memo_columns = {
            row['name'] for row in connection.execute('PRAGMA table_info(general_memos)')
        }
        if 'submission_key' not in memo_columns:
            connection.execute('ALTER TABLE general_memos ADD COLUMN submission_key TEXT')
        connection.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_general_memos_submission_key
               ON general_memos(submission_key) WHERE submission_key IS NOT NULL"""
        )
        connection.commit()

        def decode_memo(row):
            entry = dict(row)
            try:
                entry['data'] = json.loads(entry.pop('data_json') or '{}')
            except (TypeError, json.JSONDecodeError):
                current_app.logger.exception('Invalid general memo data for %s', entry.get('id'))
                abort(500, description='تعذر تحميل بيانات المذكرة')
            return entry

        memo_id = request.args.get('id', type=int)
        memo = None
        if memo_id is not None:
            row = connection.execute(
                'SELECT * FROM general_memos WHERE id = ?', (memo_id,)
            ).fetchone()
            if row is None:
                abort(404, description='المذكرة غير موجودة')
            memo = decode_memo(row)
            if memo['status'] == 'معتمدة':
                finalized = reports_repository.find_finalized('general_memo', [memo_id])
                if finalized:
                    return redirect(url_for('reports.final_report', doc_number=finalized['doc_number']))

        if request.method == 'POST':
            submitted_id = request.form.get('memo_id', '').strip()
            submission_key = request.form.get('submission_key', '').strip()
            if not re.fullmatch(r'[0-9a-f]{32}', submission_key):
                submission_key = uuid.uuid4().hex
            memo_data = {
                key: request.form.get(key, '').strip()
                for key in (
                    'document_title', 'recipient', 'subject', 'salutation', 'body', 'recommendations',
                    'requests', 'conclusion', 'signer_name', 'signer_title',
                    'signature', 'signature_date',
                )
            }
            memo_data['document_title'] = memo_data['document_title'] or 'مذكرة رسمية'
            memo_data['field_options'] = {
                key: {
                    'included': request.form.get(f'include_{key}') == '1',
                    'show_title': request.form.get(f'show_title_{key}') == '1',
                    'title': request.form.get(f'title_{key}', title).strip()[:80] or title,
                }
                for key, title in GENERAL_MEMO_FIELD_TITLES.items()
            }
            user_id = session.get('user_id')
            user = connection.execute(
                'SELECT full_name, username FROM users WHERE id = ? AND is_active = 1',
                (user_id,)
            ).fetchone()
            if not user:
                abort(401)
            if any(
                memo_data['field_options'][field]['included'] and not memo_data[field]
                for field in ('recipient', 'subject', 'body')
            ):
                flash('يرجى استكمال التوجيه والموضوع والمتن قبل حفظ المذكرة.', 'danger')
                memo = {
                    'id': int(submitted_id) if submitted_id.isdigit() else None,
                    'status': 'مسودة' if submitted_id else None,
                    'submission_key': submission_key,
                    'data': memo_data,
                }
            else:
                connection.execute('BEGIN IMMEDIATE')
                if submitted_id:
                    if not submitted_id.isdigit():
                        abort(400, description='رقم المذكرة غير صالح')
                    existing = connection.execute(
                        'SELECT status FROM general_memos WHERE id = ?',
                        (int(submitted_id),)
                    ).fetchone()
                    if existing is None:
                        abort(404, description='المذكرة المطلوب تحديثها غير موجودة')
                    if existing['status'] != 'مسودة':
                        abort(409, description='المذكرة معتمدة ولا يمكن تعديلها')
                    memo_id = int(submitted_id)
                    connection.execute(
                        """UPDATE general_memos
                           SET data_json = ?, updated_at = CURRENT_TIMESTAMP
                           WHERE id = ? AND status = 'مسودة'""",
                        (json.dumps(memo_data, ensure_ascii=False), memo_id)
                    )
                else:
                    duplicate = connection.execute(
                        'SELECT id FROM general_memos WHERE submission_key = ?',
                        (submission_key,)
                    ).fetchone()
                    if duplicate:
                        memo_id = duplicate['id']
                        connection.commit()
                        flash('تم حفظ هذه المذكرة بالفعل.', 'info')
                        return redirect(url_for('reports.general_memo_form', id=memo_id))
                    cursor = connection.execute(
                        """INSERT INTO general_memos
                           (submission_key, data_json, created_by, created_by_name)
                           VALUES (?, ?, ?, ?)""",
                        (
                            submission_key, json.dumps(memo_data, ensure_ascii=False), user_id,
                            user['full_name'] or user['username'],
                        )
                    )
                    memo_id = cursor.lastrowid
                connection.commit()
                flash('تم حفظ المذكرة كمسودة.', 'success')
                return redirect(url_for('reports.general_memo_form', id=memo_id))

        if memo_id is None and request.args.get('new') != '1':
            rows = connection.execute(
                'SELECT * FROM general_memos ORDER BY id DESC LIMIT 100'
            ).fetchall()
            entries = [decode_memo(row) for row in rows]
            return render_template(
                'general_memos.html',
                drafts=[entry for entry in entries if entry['status'] == 'مسودة'],
                archived=[entry for entry in entries if entry['status'] == 'معتمدة'],
                active_tab='reports',
            )

        memo_data = memo.get('data', {}) if memo else {}
        is_finalized = bool(memo and memo.get('status') == 'معتمدة')
        memo_token = (memo.get('submission_key') if memo else None) or uuid.uuid4().hex
        return render_template(
            'general_memo_form.html',
            memo_data=memo_data,
            memo_field_titles=GENERAL_MEMO_FIELD_TITLES,
            memo_token=memo_token,
            memo_id=memo.get('id') if memo else None,
            is_finalized=is_finalized,
            current_date=datetime.now().strftime('%Y-%m-%d'),
            document_number=(memo.get('reference_number') if is_finalized else 'No.000000'),
            qr_code_url=None,
            suppress_reference_number=True,
            report_date_gregorian=datetime.now().strftime('%Y/%m/%d'),
            report_date_hijri='',
            show_hijri_date=False,
            hide_approve=not bool(memo and memo.get('status') == 'مسودة'),
            approval_doc_type='general_memo',
            approval_item_id=memo.get('id') if memo else '',
            orientation='portrait',
            allow_orientation=False,
        )
    except dbapi.Error:
        if connection:
            connection.rollback()
        current_app.logger.exception('Unable to load or save general memo')
        abort(500, description='تعذر حفظ المذكرة أو تحميلها')
    finally:
        if connection:
            connection.close()


def _delete_memo_and_documents(table, doc_type, memo_id, missing_message):
    """Delete a memo row and its approved/generated documents atomically.

    `table` is always a literal from the callers below. Returns the archived
    files (inside the report/QR folders) the caller should remove afterwards.
    """
    init_report_counter_db()
    with get_session() as db_session:
        found = db_session.execute(
            text(f'SELECT id FROM {table} WHERE id = :id FOR UPDATE'), {'id': memo_id}
        ).first()
        if found is None:
            abort(404, description=missing_message)
        stored = reports_repository.pop_documents(db_session, doc_type, memo_id)
        db_session.execute(text(f'DELETE FROM {table} WHERE id = :id'), {'id': memo_id})

    files = []
    for stored_path, kind in stored:
        if not stored_path:
            continue
        if storage.is_url(stored_path):
            if storage.object_path_from_url(stored_path):
                files.append(stored_path)
            continue

        legacy_root = LEGACY_QR_DIR if kind == 'qr' else LEGACY_REPORTS_DIR
        allowed_roots = (QR_DIR, legacy_root) if kind == 'qr' else (REPORTS_DIR, legacy_root)
        legacy_prefix = (
            '/static/uploads/qrcodes/' if kind == 'qr'
            else '/static/uploads/reports/'
        )
        if str(stored_path).startswith(legacy_prefix):
            stored_path = os.path.join(legacy_root, os.path.basename(stored_path))
        resolved = os.path.realpath(stored_path)
        try:
            if any(
                os.path.commonpath((os.path.realpath(root), resolved)) == os.path.realpath(root)
                for root in allowed_roots
            ) and os.path.isfile(resolved):
                files.append(resolved)
        except ValueError:
            current_app.logger.warning('Skipping out-of-root file while deleting %s %s', table, memo_id)
    return files


@reports_bp.route('/general-memo/<int:memo_id>/delete', methods=['POST'])
def delete_general_memo(memo_id):
    try:
        files_to_remove = _delete_memo_and_documents(
            'general_memos', 'general_memo', memo_id, 'المذكرة غير موجودة'
        )
    except SQLAlchemyError:
        current_app.logger.exception('Unable to delete general memo %s', memo_id)
        abort(500, description='تعذر حذف المذكرة')

    _remove_memo_artifacts(files_to_remove)
    flash('تم حذف المذكرة وملفاتها المؤرشفة.', 'success')
    return redirect(url_for('reports.general_memo_form'))


@reports_bp.route('/custody-clearance', methods=['GET', 'POST'])
def custody_clearance_form():
    connection = None
    try:
        init_report_counter_db()
        connection = dbapi.connect()
        connection.row_factory = dbapi.Row
        connection.execute(
            """CREATE TABLE IF NOT EXISTS custody_clearances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reference_number TEXT UNIQUE,
                status TEXT NOT NULL DEFAULT 'مسودة',
                data_json TEXT NOT NULL DEFAULT '{}',
                created_by INTEGER NOT NULL,
                created_by_name TEXT NOT NULL,
                approved_by INTEGER,
                approved_by_name TEXT,
                approved_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        connection.commit()

        def decode_clearance(row):
            entry = dict(row)
            try:
                entry['data'] = json.loads(entry.pop('data_json') or '{}')
            except (TypeError, json.JSONDecodeError):
                current_app.logger.exception('Invalid custody clearance data for %s', entry.get('id'))
                abort(500, description='تعذر تحميل بيانات إخلاء العهدة')
            return entry

        clearance_id = request.args.get('id', type=int)
        clearance = None
        if clearance_id is not None:
            row = connection.execute(
                'SELECT * FROM custody_clearances WHERE id = ?', (clearance_id,)
            ).fetchone()
            if row is None:
                abort(404, description='نموذج إخلاء العهدة غير موجود')
            clearance = decode_clearance(row)
            if clearance['status'] == 'معتمدة':
                finalized = reports_repository.find_finalized('custody_clearance', [clearance_id])
                if finalized:
                    return redirect(url_for('reports.final_report', doc_number=finalized['doc_number']))

        if request.method == 'POST':
            submitted_id = request.form.get('clearance_id', '').strip()
            form_data = {
                key: request.form.get(key, '').strip()
                for key in (
                    'person_name', 'job_title', 'national_id', 'department', 'clearance_date',
                    'fines_count', 'fines_amount', 'accidents_count', 'fault_percentage',
                    'repair_amount', 'financial_obligations', 'administrative_notes',
                    'other_obligations', 'recipient_name', 'employee_signature',
                    'employee_date', 'manager_name', 'manager_job', 'manager_signature',
                    'manager_date',
                )
            }
            form_data['vehicles'] = []
            form_data['supplies'] = []
            for target, fields in (
                ('vehicles', ('type', 'code', 'condition', 'notes')),
                ('supplies', ('name', 'quantity', 'condition', 'notes')),
            ):
                values = {field: request.form.getlist(f'{target[:-1] if target == "vehicles" else "supply"}_{field}[]') for field in fields}
                for index in range(max((len(items) for items in values.values()), default=0)):
                    row_data = {field: items[index].strip() if index < len(items) else '' for field, items in values.items()}
                    if any(row_data.values()):
                        form_data[target].append(row_data)

            user_id = session.get('user_id')
            user = connection.execute(
                'SELECT full_name, username FROM users WHERE id = ? AND is_active = 1',
                (user_id,)
            ).fetchone()
            if not user:
                abort(401)
            if not form_data['person_name']:
                flash('يرجى إدخال اسم الشخص قبل حفظ النموذج.', 'danger')
                clearance = {
                    'id': int(submitted_id) if submitted_id.isdigit() else None,
                    'status': 'مسودة' if submitted_id else None,
                    'data': form_data,
                }
            else:
                connection.execute('BEGIN IMMEDIATE')
                if submitted_id:
                    if not submitted_id.isdigit():
                        abort(400, description='رقم نموذج إخلاء العهدة غير صالح')
                    existing = connection.execute(
                        'SELECT status FROM custody_clearances WHERE id = ?',
                        (int(submitted_id),)
                    ).fetchone()
                    if existing is None:
                        abort(404, description='نموذج إخلاء العهدة المطلوب تحديثه غير موجود')
                    if existing['status'] != 'مسودة':
                        abort(409, description='النموذج معتمد ولا يمكن تعديله')
                    clearance_id = int(submitted_id)
                    connection.execute(
                        """UPDATE custody_clearances
                           SET data_json = ?, updated_at = CURRENT_TIMESTAMP
                           WHERE id = ? AND status = 'مسودة'""",
                        (json.dumps(form_data, ensure_ascii=False), clearance_id)
                    )
                else:
                    cursor = connection.execute(
                        """INSERT INTO custody_clearances
                           (data_json, created_by, created_by_name)
                           VALUES (?, ?, ?)""",
                        (
                            json.dumps(form_data, ensure_ascii=False), user_id,
                            user['full_name'] or user['username'],
                        )
                    )
                    clearance_id = cursor.lastrowid
                connection.commit()
                flash('تم حفظ نموذج إخلاء العهدة كمسودة.', 'success')
                return redirect(url_for('reports.custody_clearance_form', id=clearance_id))

        if clearance_id is None and request.args.get('new') != '1':
            rows = connection.execute(
                'SELECT * FROM custody_clearances ORDER BY id DESC LIMIT 100'
            ).fetchall()
            entries = [decode_clearance(row) for row in rows]
            return render_template(
                'custody_clearances.html',
                drafts=[entry for entry in entries if entry['status'] == 'مسودة'],
                archived=[entry for entry in entries if entry['status'] == 'معتمدة'],
                active_tab='reports',
            )

        clearance_data = clearance.get('data', {}) if clearance else {}
        is_finalized = bool(clearance and clearance.get('status') == 'معتمدة')
        return render_template(
            'custody_clearance_form.html',
            clearance_data=clearance_data,
            clearance_id=clearance.get('id') if clearance else None,
            is_finalized=is_finalized,
            current_date=datetime.now().strftime('%Y-%m-%d'),
            document_number=(clearance.get('reference_number') if is_finalized else 'No.000000'),
            qr_code_url=None,
            report_date_gregorian=datetime.now().strftime('%Y/%m/%d'),
            report_date_hijri='',
            show_hijri_date=False,
            hide_approve=not bool(clearance and clearance.get('status') == 'مسودة'),
            approval_doc_type='custody_clearance',
            approval_item_id=clearance.get('id') if clearance else '',
            allow_orientation=False,
            orientation='portrait',
        )
    except dbapi.Error:
        if connection:
            connection.rollback()
        current_app.logger.exception('Unable to load or save custody clearance')
        abort(500, description='تعذر حفظ نموذج إخلاء العهدة أو تحميله')
    finally:
        if connection:
            connection.close()


@reports_bp.route('/custody-clearance/<int:clearance_id>/delete', methods=['POST'])
def delete_custody_clearance(clearance_id):
    try:
        files_to_remove = _delete_memo_and_documents(
            'custody_clearances', 'custody_clearance', clearance_id,
            'نموذج إخلاء العهدة غير موجود'
        )
    except SQLAlchemyError:
        current_app.logger.exception('Unable to delete custody clearance %s', clearance_id)
        abort(500, description='تعذر حذف نموذج إخلاء العهدة')

    _remove_memo_artifacts(files_to_remove)
    flash('تم حذف نموذج إخلاء العهدة وملفاته المؤرشفة.', 'success')
    return redirect(url_for('reports.custody_clearance_form'))


@reports_bp.route('/workshop-request', methods=['GET', 'POST'])
def workshop_request_form():
    connection = None
    try:
        init_report_counter_db()
        connection = dbapi.connect()
        connection.row_factory = dbapi.Row
        connection.execute(
            """CREATE TABLE IF NOT EXISTS workshop_memos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memo_number TEXT UNIQUE,
                reference_number TEXT UNIQUE,
                recipient TEXT NOT NULL,
                department TEXT NOT NULL,
                subject TEXT NOT NULL,
                priority TEXT NOT NULL DEFAULT 'عادي',
                vehicle_id INTEGER,
                vehicle_label TEXT,
                background TEXT NOT NULL,
                requested_action TEXT NOT NULL,
                justification TEXT,
                status TEXT NOT NULL DEFAULT 'مسودة',
                created_by INTEGER NOT NULL,
                created_by_name TEXT NOT NULL,
                approved_by INTEGER,
                approved_by_name TEXT,
                manager_name TEXT,
                receiver_authorization TEXT,
                receiver_job TEXT,
                approved_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        memo_columns = {
            row['name'] for row in connection.execute(
                "PRAGMA table_info(workshop_memos)"
            ).fetchall()
        }
        for column, column_type in (
            ('purpose', 'TEXT'),
            ('items_json', "TEXT NOT NULL DEFAULT '[]'"),
            ('manager_name', 'TEXT'),
            ('receiver_authorization', 'TEXT'),
            ('receiver_job', 'TEXT'),
        ):
            if column not in memo_columns:
                connection.execute(
                    f'ALTER TABLE workshop_memos ADD COLUMN "{column}" {column_type}'
                )
        connection.commit()

        vehicles = connection.execute(
            "SELECT id, plate_number, vehicle_code, vehicle_type, model FROM vehicles ORDER BY plate_number"
        ).fetchall()
        memos = connection.execute(
            """SELECT id, memo_number, reference_number, subject, recipient, purpose,
                      background, status, created_by_name, created_at, updated_at
               FROM workshop_memos ORDER BY id DESC LIMIT 100"""
        ).fetchall()

        memo_id = request.args.get('id', type=int)
        memo = None
        if memo_id is not None:
            memo = connection.execute(
                "SELECT * FROM workshop_memos WHERE id = ?", (memo_id,)
            ).fetchone()
            if memo is None:
                abort(404, description='المذكرة المطلوبة غير موجودة')
            memo = dict(memo)
            if memo.get('status') == 'معتمدة':
                finalized = reports_repository.find_finalized('workshop_memo', [memo_id])
                if finalized:
                    return redirect(url_for('reports.final_report', doc_number=finalized['doc_number']))
            try:
                memo['items'] = json.loads(memo.get('items_json') or '[]')
            except (TypeError, json.JSONDecodeError):
                current_app.logger.exception('Invalid workshop memo items for memo %s', memo_id)
                abort(500, description='تعذر تحميل مواد المذكرة')
        memos = [dict(row) for row in memos]

        if memo_id is None and request.args.get('new') != '1':
            return render_template(
                'workshop_memos.html',
                memos=memos,
                active_tab='reports',
            )

        if request.method == 'POST':
            action = request.form.get('action', 'save').strip()
            department = request.form.get('department', '').strip()
            subject = request.form.get('subject', '').strip()
            purpose = request.form.get('purpose', '').strip()
            manager_name = request.form.get('manager_name', '').strip()
            receiver_authorization = request.form.get('receiver_authorization', '').strip()
            receiver_job = request.form.get('receiver_job', '').strip()
            descriptions = request.form.getlist('item_description[]')
            quantities = request.form.getlist('item_quantity[]')
            units = request.form.getlist('item_unit[]')
            item_notes = request.form.getlist('item_notes[]')
            submitted_id = request.form.get('memo_id', '').strip()
            items = []
            submitted_items = []
            invalid_items = False
            for index, description in enumerate(descriptions):
                description = description.strip()
                quantity = quantities[index].strip() if index < len(quantities) else ''
                unit = units[index].strip() if index < len(units) else ''
                notes = item_notes[index].strip() if index < len(item_notes) else ''
                if not description and not quantity and not unit and not notes:
                    continue
                submitted_item = {
                    'description': description,
                    'quantity': quantity,
                    'unit': unit,
                    'notes': notes,
                }
                submitted_items.append(submitted_item)
                if (
                    not description or not re.fullmatch(r'\d+(?:\.\d{1,3})?', quantity)
                    or float(quantity) <= 0 or not unit
                ):
                    invalid_items = True
                else:
                    items.append(submitted_item)
            if invalid_items:
                items = []

            if action not in {'save', 'approve'}:
                abort(400, description='إجراء المذكرة غير صالح')
            if not department or len(department) > 120:
                flash('يرجى كتابة جهة الإرسال (بحد أقصى 120 حرفاً).', 'danger')
                memo = request.form.to_dict()
                memo.update({
                    'id': submitted_id or None,
                    'status': 'مسودة' if submitted_id else None,
                    'items': submitted_items,
                })
            elif len(manager_name) > 120:
                flash('اسم مدير المعدات يجب ألا يتجاوز 120 حرفاً.', 'danger')
                memo = request.form.to_dict()
                memo.update({
                    'id': submitted_id or None,
                    'status': 'مسودة' if submitted_id else None,
                    'items': submitted_items,
                })
            elif len(receiver_authorization) > 180 or len(receiver_job) > 180:
                flash('يجب ألا يتجاوز التفويض أو المسمى الوظيفي 180 حرفاً.', 'danger')
                memo = request.form.to_dict()
                memo.update({
                    'id': submitted_id or None,
                    'status': 'مسودة' if submitted_id else None,
                    'items': submitted_items,
                })
            elif not subject or len(subject) > 180:
                flash('يرجى كتابة عنوان للمذكرة (بحد أقصى 180 حرفاً).', 'danger')
                memo = request.form.to_dict()
                memo.update({
                    'id': submitted_id or None,
                    'status': 'مسودة' if submitted_id else None,
                    'items': submitted_items,
                })
            elif not purpose or len(purpose) > 500:
                flash('يرجى تحديد الغرض من استخدام المواد (بحد أقصى 500 حرف).', 'danger')
                memo = request.form.to_dict()
                memo.update({
                    'id': submitted_id or None,
                    'status': 'مسودة' if submitted_id else None,
                    'items': submitted_items,
                })
            elif not items or len(items) > 25:
                flash('أضف من مادة واحدة إلى 25 مادة، مع تحديد وصف وكمية ووحدة صحيحة لكل مادة.', 'danger')
                memo = request.form.to_dict()
                memo.update({
                    'id': submitted_id or None,
                    'status': 'مسودة' if submitted_id else None,
                    'items': submitted_items,
                })
            else:
                user_id = session.get('user_id')
                user = connection.execute(
                    "SELECT full_name, username FROM users WHERE id = ? AND is_active = 1",
                    (user_id,)
                ).fetchone()
                if not user:
                    abort(401)
                requester_name = user['full_name'] or user['username']

                connection.execute('BEGIN IMMEDIATE')
                if submitted_id:
                    if not submitted_id.isdigit():
                        abort(400, description='رقم المذكرة غير صالح')
                    existing = connection.execute(
                        "SELECT status, created_by FROM workshop_memos WHERE id = ?",
                        (int(submitted_id),)
                    ).fetchone()
                    if existing is None:
                        abort(404, description='المذكرة المطلوب تحديثها غير موجودة')
                    if existing['status'] == 'معتمدة':
                        abort(409, description='المذكرة معتمدة ولا يمكن تعديلها')
                    memo_id = int(submitted_id)
                    connection.execute(
                        """UPDATE workshop_memos
                                    SET recipient = 'إدارة المستودعات', department = ?,
                               subject = ?,
                               purpose = ?, background = ?, requested_action = ?,
                               items_json = ?, manager_name = ?,
                               receiver_authorization = ?, receiver_job = ?,
                               updated_at = CURRENT_TIMESTAMP
                           WHERE id = ? AND status = 'مسودة'""",
                        (
                            department, subject, purpose, purpose, 'صرف المواد الموضحة في الجدول أدناه',
                            json.dumps(items, ensure_ascii=False), manager_name,
                            receiver_authorization, receiver_job, memo_id,
                        )
                    )
                else:
                    cursor = connection.execute(
                        """INSERT INTO workshop_memos
                           (recipient, department, subject, priority, background,
                            requested_action, purpose, items_json,
                            manager_name, receiver_authorization, receiver_job,
                            created_by, created_by_name)
                           VALUES ('إدارة المستودعات', ?, ?,
                                   'عادي', ?, 'صرف المواد الموضحة في الجدول أدناه',
                               ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            department, subject, purpose, purpose, json.dumps(items, ensure_ascii=False),
                            manager_name, receiver_authorization, receiver_job,
                            user_id, requester_name,
                        )
                    )
                    memo_id = cursor.lastrowid
                    connection.execute(
                        "UPDATE workshop_memos SET memo_number = ? WHERE id = ?",
                        (f"WS-MEM-{memo_id:06d}", memo_id)
                    )

                connection.commit()
                flash(
                    'تم حفظ المذكرة كمسودة. يمكنك اعتمادها من شريط إجراءات التقرير.',
                    'success'
                )
                return redirect(url_for('reports.workshop_request_form', id=memo_id))

        return render_template(
            'workshop_request_form.html',
            memo=memo,
            memos=memos,
            vehicles=vehicles,
            current_date=datetime.now().strftime('%Y-%m-%d'),
            active_tab='reports',
            document_number='No.000000',
            qr_code_url=None,
            report_title_text='مذكرة طلب مواد لزوم صيانة المعدات والمركبات',
            report_date_gregorian=datetime.now().strftime('%Y/%m/%d'),
            report_date_hijri='',
            show_hijri_date=False,
            hide_approve=not bool(memo and memo.get('status') == 'مسودة'),
            approval_doc_type='workshop_memo',
            approval_item_id=memo.get('id') if memo else '',
            allow_orientation=False,
            orientation='portrait',
        )
    except dbapi.Error:
        if connection:
            connection.rollback()
        current_app.logger.exception('Unable to load or save a workshop memo')
        abort(500, description='تعذر حفظ مذكرة الورشة أو تحميلها')
    finally:
        if connection:
            connection.close()


@reports_bp.route('/workshop-request/<int:memo_id>/delete', methods=['POST'])
def delete_workshop_memo(memo_id):
    try:
        files_to_remove = _delete_memo_and_documents(
            'workshop_memos', 'workshop_memo', memo_id, 'مذكرة الورشة غير موجودة'
        )
    except SQLAlchemyError:
        current_app.logger.exception('Unable to delete workshop memo %s', memo_id)
        abort(500, description='تعذر حذف مذكرة الورشة')

    _remove_memo_artifacts(files_to_remove)
    flash('تم حذف المذكرة وملفاتها المؤرشفة.', 'success')
    return redirect(url_for('reports.workshop_request_form'))
