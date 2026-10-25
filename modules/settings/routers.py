from flask import Blueprint, abort, current_app, render_template, request, jsonify, session, redirect, url_for, flash
from werkzeug.security import generate_password_hash, check_password_hash
import hashlib
import secrets
import os
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
import re
import json
import smtplib
from pathlib import Path
from urllib.parse import urlsplit
from config import settings as app_config
from modules.settings import repository
from modules.vehicles import repository as vehicles_repository
from modules.settings.reference_lists import REFERENCE_LISTS, load_reference_lists
from modules.settings.services.email_service import (
    EmailConfigurationError,
    get_email_setting,
    get_public_base_url,
    send_email,
)
from modules.reports.typography import (
    REPORT_FONT_DEFAULT,
    REPORT_FONT_FILES,
    REPORT_FONT_SIZE_DEFAULT,
    REPORT_FONT_SIZES,
    available_report_fonts,
)

# تعريف البلوبرينت الخاص بالإعدادات
settings_bp = Blueprint(
    'settings', 
    __name__, 
    template_folder='views',
)


@settings_bp.after_request
def protect_password_reset_response(response):
    if request.endpoint == 'settings.reset_password':
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
    return response


def load_settings():
    """جلب كافة إعدادات النظام وتجميعها حسب المجموعة (group_name)"""
    try:
        return repository.get_grouped_settings(raw=True)
    except SQLAlchemyError:
        return {}


def load_vehicle_fields():
    """جلب الحقول الديناميكية للمركبات"""
    try:
        return repository.list_dynamic_fields('vehicle', include_inactive=True)
    except SQLAlchemyError:
        current_app.logger.exception('Unable to load vehicle dynamic fields')
        return []


@settings_bp.route('/login', methods=['GET', 'POST'])
def login():
    """راوتر تسجيل الدخول"""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        user = repository.get_user_by_username(username)
        
        if user and user['is_active'] and check_password_hash(user['password_hash'], password):
            session.clear()
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = 'admin' if user['role'] == 'admin' else 'visitor'
            return redirect(url_for('home'))
        else:
            flash('اسم المستخدم أو كلمة المرور غير صحيحة', 'danger')
            
    return render_template(
        'login.html',
        email_reset_enabled=(
            get_email_setting('email_password_reset_enabled', '1') == '1'
            and get_email_setting('smtp_enabled', '0') == '1'
        ),
    )


@settings_bp.route('/password/forgot', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'GET':
        return render_template(
            'forgot_password.html',
            email_reset_enabled=(
                get_email_setting('email_password_reset_enabled', '1') == '1'
                and get_email_setting('smtp_enabled', '0') == '1'
            ),
        )

    generic_message = 'إذا كان البريد مسجلاً لدينا، فستصلك رسالة برابط استعادة كلمة المرور.'
    email = request.form.get('email', '').strip()
    reset_email_enabled = get_email_setting('email_password_reset_enabled', '1') == '1'
    smtp_enabled = get_email_setting('smtp_enabled', '0') == '1'
    if (
        reset_email_enabled and smtp_enabled
        and re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email)
    ):
        reset_token = None
        user_id = None
        try:
            candidate_token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(candidate_token.encode('utf-8')).hexdigest()
            user_id = repository.create_reset_token(email, token_hash)
            if user_id is not None:
                reset_token = candidate_token
        except SQLAlchemyError:
            current_app.logger.exception('Unable to create a password reset token')
            reset_token = None

        if reset_token and user_id is not None:
            try:
                reset_url = (
                    get_public_base_url()
                    + url_for('settings.reset_password', token=reset_token)
                )
                send_email(
                    'استعادة كلمة مرور نظام SEMACOM',
                    'وصلنا طلب لاستعادة كلمة مرور حسابك. استخدم الرابط التالي خلال 30 دقيقة، '
                    'وسيصبح غير صالح بعد الاستخدام:\n\n'
                    f'{reset_url}\n\nإذا لم تطلب الاستعادة، فتجاهل هذه الرسالة.',
                    email,
                )
            except (
                EmailConfigurationError, SQLAlchemyError, smtplib.SMTPException,
                TimeoutError, OSError,
            ):
                current_app.logger.exception('Unable to send a password reset email')
                try:
                    repository.invalidate_user_tokens(user_id)
                except SQLAlchemyError:
                    current_app.logger.exception('Unable to invalidate an unsent password reset token')

    flash(generic_message, 'info')
    return redirect(url_for('settings.forgot_password'))


@settings_bp.route('/password/reset/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if (
        get_email_setting('email_password_reset_enabled', '1') != '1'
        or get_email_setting('smtp_enabled', '0') != '1'
    ):
        return render_template('password_reset.html', valid_token=False), 403
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,64}', token):
        return render_template('password_reset.html', valid_token=False), 400

    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    if request.method == 'GET':
        try:
            valid_token = repository.reset_token_is_valid(token_hash)
        except SQLAlchemyError:
            current_app.logger.exception('Unable to validate a password reset token')
            return render_template('password_reset.html', valid_token=False), 500
        return render_template('password_reset.html', valid_token=valid_token)

    password = request.form.get('password', '')
    confirm_password = request.form.get('confirm_password', '')
    if len(password) < 12:
        flash('يجب ألا تقل كلمة المرور عن 12 حرفًا.', 'danger')
        return render_template('password_reset.html', valid_token=True), 400
    if password != confirm_password:
        flash('كلمتا المرور غير متطابقتين.', 'danger')
        return render_template('password_reset.html', valid_token=True), 400

    try:
        updated = repository.consume_reset_token(token_hash, generate_password_hash(password))
    except SQLAlchemyError:
        current_app.logger.exception('Unable to update a password through email recovery')
        return render_template('password_reset.html', valid_token=True), 500
    if not updated:
        return render_template('password_reset.html', valid_token=False), 400

    flash('تم تغيير كلمة المرور. يمكنك تسجيل الدخول الآن.', 'success')
    return redirect(url_for('settings.login'))


@settings_bp.route('/logout')
def logout():
    """راوتر تسجيل الخروج"""
    session.clear()
    return redirect(url_for('settings.login'))


@settings_bp.route('/', methods=['GET'])
def index():
    """عرض صفحة الإعدادات الرئيسية"""
    if session.get('role') != 'admin':
        abort(403)
    user_id = session.get('user_id', 1)
    current_user = repository.get_user(user_id)
    users = repository.list_active_users()
    reference_lists = load_reference_lists()
    
    # جلب الإعدادات وحقول المركبات المخصصة وتمريرها للقالب
    settings = load_settings()
    smtp_password_configured = bool(settings.get('smtp', {}).get('smtp_password'))
    if 'smtp' in settings:
        settings['smtp']['smtp_password'] = ''
    vehicle_fields = load_vehicle_fields()
    
    return render_template(
        'setting_index.html', 
        current_user=current_user,
        settings=settings,
        vehicle_fields=vehicle_fields,
        users=users,
        reference_lists=reference_lists,
        reference_list_definitions=REFERENCE_LISTS,
        smtp_password_configured=smtp_password_configured,
        report_fonts=REPORT_FONT_FILES,
        available_report_fonts=available_report_fonts(),
        report_font_default=REPORT_FONT_DEFAULT,
        report_font_size_default=REPORT_FONT_SIZE_DEFAULT,
        report_font_sizes=REPORT_FONT_SIZES,
    )


def _vehicle_field_required(value):
    return value is True or value == 1 or value == '1' or value == 'true'


@settings_bp.route('/dynamic-fields', methods=['POST'])
def create_vehicle_dynamic_field():
    if session.get('role') != 'admin':
        return jsonify({'status': 'error', 'message': 'غير مسموح'}), 401
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'status': 'error', 'message': 'بيانات الحقل غير صالحة'}), 400
    label = ' '.join(str(data.get('label') or '').split())
    if not label or len(label) > 120:
        return jsonify({'status': 'error', 'message': 'أدخل اسمًا للحقل لا يتجاوز 120 حرفًا'}), 400
    try:
        field = vehicles_repository.add_custom_field(
            label, int(_vehicle_field_required(data.get('required')))
        )
    except (SQLAlchemyError, ValueError):
        current_app.logger.exception('Unable to create vehicle dynamic field')
        return jsonify({'status': 'error', 'message': 'تعذر إنشاء الحقل'}), 500
    return jsonify({
        'status': 'success',
        'message': 'تم حفظ الحقل بنجاح.',
        'field': field,
    }), 200


@settings_bp.route('/dynamic-fields/<int:field_id>', methods=['POST'])
def update_vehicle_dynamic_field(field_id):
    if session.get('role') != 'admin':
        return jsonify({'status': 'error', 'message': 'غير مسموح'}), 401
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'status': 'error', 'message': 'بيانات الحقل غير صالحة'}), 400
    label = ' '.join(str(data.get('label') or '').split())
    if not label or len(label) > 120:
        return jsonify({'status': 'error', 'message': 'أدخل اسمًا للحقل لا يتجاوز 120 حرفًا'}), 400
    try:
        updated, message = repository.update_vehicle_field(
            field_id, label, _vehicle_field_required(data.get('required'))
        )
    except ValueError as error:
        return jsonify({'status': 'error', 'message': str(error)}), 400
    except SQLAlchemyError:
        current_app.logger.exception('Unable to update vehicle dynamic field %s', field_id)
        return jsonify({'status': 'error', 'message': 'تعذر تحديث الحقل'}), 500
    if not updated:
        status_code = 404 if message == 'الحقل غير موجود.' else 409
        return jsonify({'status': 'error', 'message': message}), status_code
    return jsonify({'status': 'success', 'message': message}), 200


@settings_bp.route('/dynamic-fields/<int:field_id>/archive', methods=['POST'])
def archive_vehicle_dynamic_field(field_id):
    return _set_vehicle_dynamic_field_active(field_id, False)


@settings_bp.route('/dynamic-fields/<int:field_id>/restore', methods=['POST'])
def restore_vehicle_dynamic_field(field_id):
    return _set_vehicle_dynamic_field_active(field_id, True)


def _set_vehicle_dynamic_field_active(field_id, is_active):
    if session.get('role') != 'admin':
        return jsonify({'status': 'error', 'message': 'غير مسموح'}), 401
    try:
        updated, message = repository.set_vehicle_field_active(field_id, is_active)
    except SQLAlchemyError:
        current_app.logger.exception(
            'Unable to change active state for vehicle dynamic field %s', field_id
        )
        return jsonify({'status': 'error', 'message': 'تعذر تحديث حالة الحقل'}), 500
    if not updated:
        status_code = 404 if message == 'الحقل غير موجود.' else 409
        return jsonify({'status': 'error', 'message': message}), status_code
    return jsonify({'status': 'success', 'message': message}), 200


@settings_bp.route('/save', methods=['POST'])
def save_settings():
    if session.get('role') != 'admin':
        return jsonify({'status': 'error', 'message': 'غير مسموح'}), 401

    data = request.get_json(silent=True)
    if data is None:
        data = request.form
    if not hasattr(data, 'items'):
        return jsonify({'status': 'error', 'message': 'صيغة الإعدادات غير صالحة'}), 400
    appearance_theme = data.get('appearance_theme')
    font_size = data.get('appearance_font_size')
    primary_color = data.get('appearance_primary_color')
    report_font_family = data.get('report_font_family')
    report_font_size = data.get('report_font_size')

    if appearance_theme is not None and (
        not isinstance(appearance_theme, str)
        or appearance_theme not in {'semacom', 'teal', 'forest', 'violet'}
    ):
        return jsonify({'status': 'error', 'message': 'الثيم المحدد غير صالح'}), 400
    if font_size is not None:
        try:
            parsed_font_size = int(font_size)
        except (TypeError, ValueError):
            return jsonify({'status': 'error', 'message': 'حجم الخط غير صالح'}), 400
        if not 15 <= parsed_font_size <= 21:
            return jsonify({'status': 'error', 'message': 'حجم الخط يجب أن يكون بين 15 و21'}), 400
    if primary_color is not None and (
        not isinstance(primary_color, str)
        or not re.fullmatch(r'#[0-9a-fA-F]{6}', primary_color)
    ):
        return jsonify({'status': 'error', 'message': 'لون الواجهة غير صالح'}), 400
    if report_font_family is not None and (
        not isinstance(report_font_family, str)
        or report_font_family not in available_report_fonts()
    ):
        return jsonify({
            'status': 'error',
            'message': 'الخط المحدد غير متوفر؛ تحقق من وجود ملفي Regular وBold المرخصين.',
        }), 400
    if report_font_size is not None and report_font_size not in REPORT_FONT_SIZES:
        return jsonify({'status': 'error', 'message': 'حجم خط التقارير غير صالح'}), 400
    public_base_url = data.get('app_public_url')
    if public_base_url is not None:
        if not isinstance(public_base_url, str):
            return jsonify({'status': 'error', 'message': 'الرابط العام للنظام غير صالح'}), 400
        public_base_url = public_base_url.strip()
        try:
            parsed_public_url = urlsplit(public_base_url)
            public_port = parsed_public_url.port
        except ValueError:
            return jsonify({'status': 'error', 'message': 'منفذ الرابط العام غير صالح'}), 400
        if public_base_url and (
            parsed_public_url.scheme not in {'http', 'https'}
            or not parsed_public_url.hostname
            or not re.fullmatch(r'[A-Za-z0-9.-]+', parsed_public_url.hostname)
            or (public_port is not None and not 1 <= public_port <= 65535)
            or parsed_public_url.username
            or parsed_public_url.password
            or parsed_public_url.path not in {'', '/'}
            or parsed_public_url.query
            or parsed_public_url.fragment
            or any(char in public_base_url for char in '\r\n')
            or (
                app_config.IS_PRODUCTION
                and parsed_public_url.scheme != 'https'
            )
        ):
            return jsonify({'status': 'error', 'message': 'أدخل رابطًا أساسيًا صحيحًا وآمنًا مثل https://fleet.example.com'}), 400

    alert_day_keys = {'insurance_alert_days', 'license_alert_days', 'inspection_alert_days'}
    alert_toggle_keys = {
        'insurance_alert_enabled', 'license_alert_enabled',
        'inspection_alert_enabled', 'oil_alert_enabled',
    }
    for key in alert_day_keys:
        if key in data:
            try:
                value = int(data[key])
            except (TypeError, ValueError):
                return jsonify({'status': 'error', 'message': 'عدد أيام التنبيه غير صالح'}), 400
            if not 0 <= value <= 365:
                return jsonify({'status': 'error', 'message': 'فترة التنبيه يجب أن تكون بين 0 و365 يوماً'}), 400
    if 'oil_change_interval_km' in data:
        try:
            oil_interval = int(data['oil_change_interval_km'])
        except (TypeError, ValueError):
            return jsonify({'status': 'error', 'message': 'فترة تغيير الزيت غير صالحة'}), 400
        if oil_interval < 1:
            return jsonify({'status': 'error', 'message': 'فترة تغيير الزيت يجب أن تكون أكبر من صفر'}), 400
    for key in alert_toggle_keys:
        if key in data and str(data[key]) not in {'0', '1'}:
            return jsonify({'status': 'error', 'message': 'قيمة تفعيل التنبيه غير صالحة'}), 400
    email_toggle_keys = {
        'smtp_enabled', 'email_reports_enabled',
        'email_password_reset_enabled', 'email_fleet_digest_enabled',
    }
    for key in email_toggle_keys:
        if key in data and str(data[key]) not in {'0', '1'}:
            return jsonify({'status': 'error', 'message': 'قيمة تفعيل وظيفة البريد غير صالحة'}), 400
    for key, maximum, description in (
        ('email_fleet_digest_day', 6, 'يوم إرسال الملخص'),
        ('email_fleet_digest_hour', 23, 'ساعة إرسال الملخص'),
    ):
        if key in data:
            try:
                value = int(data[key])
            except (TypeError, ValueError):
                return jsonify({'status': 'error', 'message': f'{description} غير صالح'}), 400
            if not 0 <= value <= maximum:
                return jsonify({'status': 'error', 'message': f'{description} خارج النطاق المسموح'}), 400
    if 'smtp_server' in data:
        smtp_server = str(data['smtp_server']).strip()
        if smtp_server and (
            len(smtp_server) > 253
            or not re.fullmatch(r'[A-Za-z0-9.-]+', smtp_server)
        ):
            return jsonify({'status': 'error', 'message': 'اسم خادم البريد غير صالح'}), 400
    if 'smtp_port' in data:
        try:
            smtp_port = int(data['smtp_port'])
        except (TypeError, ValueError):
            return jsonify({'status': 'error', 'message': 'منفذ خادم البريد غير صالح'}), 400
        if not 1 <= smtp_port <= 65535:
            return jsonify({'status': 'error', 'message': 'منفذ خادم البريد يجب أن يكون بين 1 و65535'}), 400
    if 'smtp_email' in data:
        smtp_email = str(data['smtp_email']).strip()
        if smtp_email and not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', smtp_email):
            return jsonify({'status': 'error', 'message': 'عنوان بريد الإرسال غير صالح'}), 400
    if 'smtp_username' in data:
        smtp_username = str(data['smtp_username']).strip()
        if len(smtp_username) > 254 or any(char in smtp_username for char in '\r\n'):
            return jsonify({'status': 'error', 'message': 'اسم مستخدم SMTP غير صالح'}), 400
    if 'smtp_from_name' in data:
        smtp_from_name = str(data['smtp_from_name']).strip()
        if len(smtp_from_name) > 120 or any(char in smtp_from_name for char in '\r\n'):
            return jsonify({'status': 'error', 'message': 'اسم مرسل البريد غير صالح أو يتجاوز 120 حرفاً'}), 400
    if 'smtp_security' in data and str(data['smtp_security']) not in {'starttls', 'ssl'}:
        return jsonify({'status': 'error', 'message': 'طريقة تشفير البريد غير صالحة'}), 400

    prepared_data = {}
    reference_setting_keys = {
        definition['setting_key'] for definition in REFERENCE_LISTS.values()
    }
    for key, value in data.items():
        if key in reference_setting_keys:
            if not isinstance(value, str):
                return jsonify({'status': 'error', 'message': 'صيغة القائمة المرجعية غير صالحة'}), 400
            values = [item.strip() for item in value.splitlines() if item.strip()]
            if len(values) == 1 and ',' in values[0]:
                values = [item.strip() for item in values[0].split(',') if item.strip()]
            values = list(dict.fromkeys(values))
            if not values:
                return jsonify({'status': 'error', 'message': 'يجب أن تحتوي القائمة على خيار واحد على الأقل'}), 400
            if len(values) > 100 or any(len(item) > 120 for item in values):
                return jsonify({'status': 'error', 'message': 'القائمة تتجاوز الحد المسموح للعناصر'}), 400
            prepared_data[key] = json.dumps(values, ensure_ascii=False)
        else:
            prepared_data[key] = value

    items = []
    for key, value in prepared_data.items():
        if key in {'action', 'user_id', 'current_password', 'new_password'}:
            continue
        if key == 'smtp_password' and not str(value).strip():
            continue
        if key in alert_day_keys or key in alert_toggle_keys or key == 'oil_change_interval_km':
            group_name = 'fleet'
        elif key.startswith('lookup_') or key in {'external_workshops', 'store_categories'}:
            group_name = 'lookups'
        elif key.startswith('smtp_'):
            group_name = 'smtp'
        elif key.startswith('gdrive_'):
            group_name = 'gdrive'
        elif key.startswith('prefix_'):
            group_name = 'prefixes'
        elif key.startswith('fleet_'):
            group_name = 'fleet'
        elif key.startswith('appearance_'):
            group_name = 'appearance'
        elif key.startswith('report_font_'):
            group_name = 'reports'
        else:
            group_name = 'general'
        items.append((key, str(value), group_name))
    repository.upsert_settings(items)
    return jsonify({'status': 'success', 'message': 'تم حفظ الإعدادات بنجاح'}), 200


@settings_bp.route('/email/test', methods=['POST'])
def test_email_settings():
    if session.get('role') != 'admin':
        return jsonify({'status': 'error', 'message': 'غير مسموح'}), 401

    data = request.get_json(silent=True)
    recipient = str(data.get('recipient', '')).strip() if isinstance(data, dict) else ''
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', recipient):
        return jsonify({'status': 'error', 'message': 'أدخل عنوان بريد مستلماً صالحاً'}), 400

    try:
        send_email(
            'اختبار إعدادات البريد - SEMACOM',
            'تم إرسال هذه الرسالة بنجاح للتحقق من إعدادات SMTP في نظام إدارة المركبات والمعدات SEMACOM.',
            recipient,
            allow_when_disabled=True,
        )
    except EmailConfigurationError as error:
        return jsonify({'status': 'error', 'message': str(error)}), 400
    except smtplib.SMTPAuthenticationError:
        current_app.logger.exception('SMTP authentication failed while sending a test email')
        return jsonify({'status': 'error', 'message': 'فشل تسجيل الدخول إلى خادم البريد؛ تحقق من البريد وكلمة مرور التطبيق'}), 502
    except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, TimeoutError, OSError):
        current_app.logger.exception('Unable to connect to the configured SMTP server')
        return jsonify({'status': 'error', 'message': 'تعذر الاتصال بخادم البريد؛ تحقق من الخادم والمنفذ والاتصال بالشبكة'}), 502
    except smtplib.SMTPException:
        current_app.logger.exception('SMTP rejected a test email')
        return jsonify({'status': 'error', 'message': 'رفض خادم البريد إرسال رسالة الاختبار؛ راجع إعدادات الحساب ومزود البريد'}), 502
    except SQLAlchemyError:
        current_app.logger.exception('Unable to load SMTP settings for a test email')
        return jsonify({'status': 'error', 'message': 'تعذر قراءة إعدادات البريد'}), 500

    return jsonify({'status': 'success', 'message': f'تم إرسال رسالة اختبار إلى {recipient}'}), 200


@settings_bp.route('/users', methods=['POST'])
def create_user():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({'status': 'error', 'message': 'بيانات المستخدم غير صالحة'}), 400
    username = str(data.get('username', '')).strip()
    full_name = str(data.get('full_name', '')).strip()
    password = data.get('password', '')
    role = data.get('role', 'visitor')
    if not re.fullmatch(r'[\w.@-]{3,64}', username, flags=re.UNICODE):
        return jsonify({'status': 'error', 'message': 'اسم المستخدم يجب أن يتكون من 3 إلى 64 حرفاً أو رقماً'}), 400
    if not full_name:
        return jsonify({'status': 'error', 'message': 'الاسم الكامل مطلوب'}), 400
    if not isinstance(password, str) or len(password) < 8:
        return jsonify({'status': 'error', 'message': 'كلمة المرور يجب ألا تقل عن 8 أحرف'}), 400
    if not isinstance(role, str) or role not in {'admin', 'visitor'}:
        return jsonify({'status': 'error', 'message': 'صلاحية المستخدم غير صالحة'}), 400

    try:
        repository.create_user(username, generate_password_hash(password), full_name, role)
    except IntegrityError:
        return jsonify({'status': 'error', 'message': 'اسم المستخدم مستخدم مسبقاً'}), 409
    return jsonify({'status': 'success', 'message': 'تم إنشاء المستخدم بنجاح'}), 201


@settings_bp.route('/users/<int:user_id>/role', methods=['POST'])
def update_user_role(user_id):
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({'status': 'error', 'message': 'بيانات المستخدم غير صالحة'}), 400
    role = data.get('role')
    if not isinstance(role, str) or role not in {'admin', 'visitor'}:
        return jsonify({'status': 'error', 'message': 'صلاحية المستخدم غير صالحة'}), 400

    changed, error = repository.change_user_role(user_id, role)
    if not changed and error == 'missing':
        return jsonify({'status': 'error', 'message': 'المستخدم غير موجود أو غير مفعل'}), 404
    if not changed:
        return jsonify({'status': 'error', 'message': 'لا يمكن تغيير صلاحية آخر مدير في النظام'}), 400
    return jsonify({'status': 'success', 'message': 'تم تحديث صلاحية المستخدم'}), 200


@settings_bp.route('/account/update', methods=['POST'])
def update_account():
    """راوتر تحديث اسم المستخدم وكلمة المرور وباقي البيانات"""
    try:
        data = request.get_json() or {}
        
        user_id = session.get('user_id')
        
        username = data.get('username', '').strip()
        full_name = data.get('full_name', '').strip()
        email = data.get('email', '').strip()
        google_drive_email = data.get('google_drive_email', '').strip()
        
        current_password = data.get('current_password', '')
        new_password = data.get('new_password', '')
        confirm_password = data.get('confirm_password', '')

        if not username:
            return jsonify({'status': 'error', 'message': 'اسم المستخدم مطلوب ولا يمكن أن يكون فارغاً'}), 400

        user = repository.get_user(user_id)

        if not user:
            return jsonify({'status': 'error', 'message': 'المستخدم غير موجود'}), 404

        # التأكد من عدم تكرار اسم المستخدم
        if repository.username_taken(username, user_id):
            return jsonify({'status': 'error', 'message': 'اسم المستخدم هذا مُستخدم بالفعل لحساب آخر'}), 400

        values = {
            'username': username, 'full_name': full_name,
            'email': email, 'google_drive_email': google_drive_email,
        }

        # معالجة تغيير كلمة المرور
        if new_password:
            if not current_password:
                return jsonify({'status': 'error', 'message': 'يرجى إدخال كلمة المرور الحالية لتأكيد التغيير'}), 400

            if not check_password_hash(user['password_hash'], current_password):
                return jsonify({'status': 'error', 'message': 'كلمة المرور الحالية غير صحيحة'}), 400

            if new_password != confirm_password:
                return jsonify({'status': 'error', 'message': 'كلمة المرور الجديدة وتأكيدها غير متطابقين'}), 400

            values['password_hash'] = generate_password_hash(new_password)

        repository.update_user_fields(user_id, **values)

        session['username'] = username

        return jsonify({'status': 'success', 'message': 'تم تحديث بيانات الحساب واسم المستخدم بنجاح!'}), 200

    except Exception as e:
        return jsonify({'status': 'error', 'message': f'حدث خطأ في النظام: {str(e)}'}), 500