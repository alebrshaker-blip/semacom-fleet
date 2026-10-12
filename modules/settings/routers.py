from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, flash
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import re
from pathlib import Path
from core.database import DB_PATH

# تعريف البلوبرينت الخاص بالإعدادات
settings_bp = Blueprint(
    'settings', 
    __name__, 
    template_folder='views',
)

# دالة للاتصال بقاعدة البيانات
def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def load_settings():
    """جلب كافة إعدادات النظام وتجميعها حسب المجموعة (group_name)"""
    conn = get_db()
    try:
        rows = conn.execute('SELECT key, value, group_name FROM system_settings').fetchall()
        settings = {}
        for row in rows:
            group = row['group_name'] or 'general'
            if group not in settings:
                settings[group] = {}
            settings[group][row['key']] = row['value']
        return settings
    except Exception:
        return {}
    finally:
        conn.close()


def load_vehicle_fields():
    """جلب الحقول الديناميكية للمركبات"""
    conn = get_db()
    try:
        fields = conn.execute('SELECT * FROM vehicle_fields').fetchall()
        return fields
    except Exception:
        return []
    finally:
        conn.close()


@settings_bp.route('/login', methods=['GET', 'POST'])
def login():
    """راوتر تسجيل الدخول"""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()
        
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            return redirect(url_for('home'))
        else:
            flash('اسم المستخدم أو كلمة المرور غير صحيحة', 'danger')
            
    return render_template('login.html')


@settings_bp.route('/logout')
def logout():
    """راوتر تسجيل الخروج"""
    session.clear()
    return redirect(url_for('settings.login'))


@settings_bp.route('/', methods=['GET'])
def index():
    """عرض صفحة الإعدادات الرئيسية"""
    user_id = session.get('user_id', 1)
    conn = get_db()
    current_user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    
    # جلب الإعدادات وحقول المركبات المخصصة وتمريرها للقالب
    settings = load_settings()
    vehicle_fields = load_vehicle_fields()
    
    return render_template(
        'setting_index.html', 
        current_user=current_user,
        settings=settings,
        vehicle_fields=vehicle_fields
    )


@settings_bp.route('/save', methods=['POST'])
def save_settings():
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': 'غير مسموح'}), 401

    data = request.get_json(silent=True)
    if data is None:
        data = request.form
    if not hasattr(data, 'items'):
        return jsonify({'status': 'error', 'message': 'صيغة الإعدادات غير صالحة'}), 400
    appearance_theme = data.get('appearance_theme')
    font_size = data.get('appearance_font_size')
    primary_color = data.get('appearance_primary_color')

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

    connection = get_db()
    try:
        for key, value in data.items():
            if key in {'action', 'user_id', 'current_password', 'new_password'}:
                continue
            if key.startswith('smtp_'):
                group_name = 'smtp'
            elif key.startswith('gdrive_'):
                group_name = 'gdrive'
            elif key.startswith('prefix_'):
                group_name = 'prefixes'
            elif key.startswith('fleet_') or key in {'insurance_alert_days', 'oil_change_interval_km'}:
                group_name = 'fleet'
            elif key.startswith('appearance_'):
                group_name = 'appearance'
            else:
                group_name = 'general'
            connection.execute(
                """
                INSERT INTO system_settings (key, value, group_name)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    group_name = excluded.group_name,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (key, str(value), group_name),
            )
        connection.commit()
    finally:
        connection.close()
    return jsonify({'status': 'success', 'message': 'تم حفظ الإعدادات بنجاح'}), 200


@settings_bp.route('/account/update', methods=['POST'])
def update_account():
    """راوتر تحديث اسم المستخدم وكلمة المرور وباقي البيانات"""
    try:
        data = request.get_json() or {}
        
        user_id = session.get('user_id', 1)
        
        username = data.get('username', '').strip()
        full_name = data.get('full_name', '').strip()
        email = data.get('email', '').strip()
        google_drive_email = data.get('google_drive_email', '').strip()
        
        current_password = data.get('current_password', '')
        new_password = data.get('new_password', '')
        confirm_password = data.get('confirm_password', '')

        if not username:
            return jsonify({'status': 'error', 'message': 'اسم المستخدم مطلوب ولا يمكن أن يكون فارغاً'}), 400

        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()

        if not user:
            conn.close()
            return jsonify({'status': 'error', 'message': 'المستخدم غير موجود'}), 404

        # التأكد من عدم تكرار اسم المستخدم
        existing_user = conn.execute(
            'SELECT id FROM users WHERE username = ? AND id != ?', 
            (username, user_id)
        ).fetchone()
        
        if existing_user:
            conn.close()
            return jsonify({'status': 'error', 'message': 'اسم المستخدم هذا مُستخدم بالفعل لحساب آخر'}), 400

        # معالجة تغيير كلمة المرور
        if new_password:
            if not current_password:
                conn.close()
                return jsonify({'status': 'error', 'message': 'يرجى إدخال كلمة المرور الحالية لتأكيد التغيير'}), 400
            
            if not check_password_hash(user['password_hash'], current_password):
                conn.close()
                return jsonify({'status': 'error', 'message': 'كلمة المرور الحالية غير صحيحة'}), 400
            
            if new_password != confirm_password:
                conn.close()
                return jsonify({'status': 'error', 'message': 'كلمة المرور الجديدة وتأكيدها غير متطابقين'}), 400

            hashed_pw = generate_password_hash(new_password)
            conn.execute('UPDATE users SET password_hash = ? WHERE id = ?', (hashed_pw, user_id))

        # تحديث باقي بيانات الحساب واسم المستخدم
        conn.execute('''
            UPDATE users 
            SET username = ?, full_name = ?, email = ?, google_drive_email = ?
            WHERE id = ?
        ''', (username, full_name, email, google_drive_email, user_id))

        conn.commit()
        conn.close()

        session['username'] = username

        return jsonify({'status': 'success', 'message': 'تم تحديث بيانات الحساب واسم المستخدم بنجاح!'}), 200

    except Exception as e:
        return jsonify({'status': 'error', 'message': f'حدث خطأ في النظام: {str(e)}'}), 500