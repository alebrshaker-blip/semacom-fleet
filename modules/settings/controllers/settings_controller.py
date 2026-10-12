import os
import sqlite3
from pathlib import Path
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, session, flash, make_response
from werkzeug.security import generate_password_hash, check_password_hash
from core.database import DB_PATH

settings_bp = Blueprint(
    'settings',
    __name__,
    template_folder='../views',
)

def get_db_connection():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def init_users_table():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT,
            email TEXT,
            google_drive_email TEXT,
            role TEXT DEFAULT 'admin'
        )
    """)
    # إنشاء حساب الآدمن الافتراضي إن لم يكن موجوداً
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        default_pass = generate_password_hash('admin123')
        cursor.execute("""
            INSERT INTO users (username, password_hash, full_name, email, role)
            VALUES (?, ?, ?, ?, ?)
        """, ('admin', default_pass, 'مدير النظام', 'admin@semacom.com', 'admin'))
    conn.commit()
    conn.close()

# ==========================================
# 0. صفحة تسجيل الدخول (Login)
# ==========================================
@settings_bp.route('/login', methods=['GET', 'POST'])
def login():
    init_users_table()
    
    # إذا كان المستخدم مسجلاً دخوله بالفعل، نقوم بتوجيهه للصفحة الرئيسية مباشرة
    if request.method == 'GET' and 'user_id' in session:
        return redirect(url_for('home'))

    if request.method == 'POST':
        data = request.form if not request.is_json else request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()

        if not username or not password:
            if request.is_json:
                return jsonify({'status': 'error', 'message': 'يرجى إدخال اسم المستخدم وكلمة المرور'}), 400
            flash('يرجى إدخال اسم المستخدم وكلمة المرور', 'danger')
            return render_template('login.html', error='يرجى إدخال اسم المستخدم وكلمة المرور')

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = cursor.fetchone()
        conn.close()

        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['full_name'] = user['full_name'] or user['username']
            session['role'] = user['role'] or 'user'
            
            if request.is_json:
                return jsonify({'status': 'success', 'redirect': url_for('home')}), 200
            return redirect(url_for('home'))
        else:
            if request.is_json:
                return jsonify({'status': 'error', 'message': 'اسم المستخدم أو كلمة المرور غير صحيحة'}), 401
            flash('اسم المستخدم أو كلمة المرور غير صحيحة', 'danger')
            return render_template('login.html', error='بيانات الدخول غير صحيحة')

    return render_template('login.html')

# ==========================================
# 1. عرض صفحة الإعدادات الرئيسية وإدارة المستخدمين
# ==========================================
@settings_bp.route('/', methods=['GET'])
def index():
    if 'user_id' not in session:
        return redirect(url_for('settings.login'))

    init_users_table()
    conn = get_db_connection()
    cursor = conn.cursor()

    # قراءة كل الإعدادات المحفوظة
    cursor.execute("SELECT key, value, group_name FROM system_settings")
    rows = cursor.fetchall()
    
    settings_data = {'general': {}, 'fleet': {}, 'prefixes': {}, 'smtp': {}, 'gdrive': {}}
    for row in rows:
        grp = row['group_name'] or 'general'
        if grp not in settings_data:
            settings_data[grp] = {}
        settings_data[grp][row['key']] = row['value']

    # قراءة حقول المركبات والسائقين
    cursor.execute("SELECT * FROM vehicle_fields")
    v_fields = [dict(r) for r in cursor.fetchall()]

    cursor.execute("SELECT * FROM driver_fields")
    d_fields = [dict(r) for r in cursor.fetchall()]

    # جلب قائمة جميع المستخدمين للنظام
    cursor.execute("SELECT id, username, full_name, email, role FROM users")
    all_users = [dict(r) for r in cursor.fetchall()]

    # بيانات المستخدم الحالي
    cursor.execute("SELECT id, username, full_name, email, google_drive_email, role FROM users WHERE id = ?", (session.get('user_id'),))
    user_row = cursor.fetchone()
    current_user = dict(user_row) if user_row else {}

    conn.close()

    return render_template(
        'setting_index.html',
        settings=settings_data,
        vehicle_fields=v_fields,
        driver_fields=d_fields,
        current_user=current_user,
        all_users=all_users
    )

# ==========================================
# 2. إضافة مستخدم جديد للنظام
# ==========================================
@settings_bp.route('/users/add', methods=['POST'])
def add_user():
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': 'غير مسموح'}), 401
    try:
        data = request.get_json() or request.form
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        full_name = data.get('full_name', '').strip()
        email = data.get('email', '').strip()
        role = data.get('role', 'user').strip()

        if not username or not password:
            return jsonify({'status': 'error', 'message': 'اسم المستخدم وكلمة المرور إجباريان'}), 400

        hashed_pwd = generate_password_hash(password)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (username, password_hash, full_name, email, role)
            VALUES (?, ?, ?, ?, ?)
        """, (username, hashed_pwd, full_name, email, role))
        conn.commit()
        conn.close()

        return jsonify({'status': 'success', 'message': 'تم إضافة المستخدم بنجاح'}), 200
    except sqlite3.IntegrityError:
        return jsonify({'status': 'error', 'message': 'اسم المستخدم موجود مسبقاً'}), 400
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ==========================================
# 3. حفظ الإعدادات العامة
# ==========================================
@settings_bp.route('/save', methods=['POST'])
def save_settings():
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': 'غير مسموح'}), 401
    try:
        data = request.get_json() or request.form
        conn = get_db_connection()
        cursor = conn.cursor()

        for key, val in data.items():
            if key in ['action', 'user_id', 'current_password', 'new_password']:
                continue
            
            group_name = 'general'
            if key.startswith('smtp_'): group_name = 'smtp'
            elif key.startswith('gdrive_'): group_name = 'gdrive'
            elif key.startswith('prefix_'): group_name = 'prefixes'
            elif key.startswith('fleet_'): group_name = 'fleet'

            cursor.execute("""
                INSERT INTO system_settings (key, value, group_name)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    group_name = excluded.group_name,
                    updated_at = CURRENT_TIMESTAMP
            """, (key, str(val), group_name))

        conn.commit()
        conn.close()
        return jsonify({'status': 'success', 'message': 'تم حفظ الإعدادات بنجاح'}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ==========================================
# 4. تحديث الحساب الشخصي
# ==========================================
@settings_bp.route('/account/update', methods=['POST'])
def update_account():
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': 'غير مسموح'}), 401
    try:
        data = request.get_json() if request.is_json else request.form
        user_id = session.get('user_id')
        full_name = data.get('full_name', '').strip()
        email = data.get('email', '').strip()
        gdrive_email = data.get('google_drive_email', '').strip()
        current_pass = data.get('current_password', '').strip()
        new_pass = data.get('new_password', '').strip()

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        user = cursor.fetchone()

        if not user:
            conn.close()
            return jsonify({'status': 'error', 'message': 'المستخدم غير موجود'}), 444

        if new_pass:
            if not current_pass or not check_password_hash(user['password_hash'], current_pass):
                conn.close()
                return jsonify({'status': 'error', 'message': 'كلمة المرور الحالية غير صحيحة'}), 400
            new_hash = generate_password_hash(new_pass)
            cursor.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user_id))

        cursor.execute("""
            UPDATE users SET full_name = ?, email = ?, google_drive_email = ? WHERE id = ?
        """, (full_name, email, gdrive_email, user_id))

        conn.commit()
        conn.close()

        # تحديث بيانات الجلسة الحالية
        if full_name:
            session['full_name'] = full_name

        return jsonify({'status': 'success', 'message': 'تم تحديث بيانات الحساب والأمان بنجاح'}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ==========================================
# 5. تسجيل الخروج (Logout)
# ==========================================
@settings_bp.route('/logout')
def logout():
    session.clear()  # مسح الجلسة بالكامل
    response = make_response(redirect(url_for('settings.login')))
    # منع المتصفح تماماً من تخزين الصفحة مؤقتاً للرجوع إليها
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response