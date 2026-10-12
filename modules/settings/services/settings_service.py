import sqlite3
import json
from werkzeug.security import generate_password_hash, check_password_hash
from core.database import DB_PATH

def get_db_connection():
    """إنشاء اتصال مباشر بقاعدة بيانات النظام semacom.db"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row  # لإرجاع النتائج على شكل قواميس
    return conn


class SettingsService:

    @staticmethod
    def init_security_and_users():
        """إنشاء جدول المستخدمين، الإعدادات، الحقول الديناميكية وإدخال حساب المدير الافتراضي"""
        conn = get_db_connection()
        cursor = conn.cursor()

        # 1. إنشاء جدول المستخدمين users
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                full_name TEXT,
                email TEXT,
                google_drive_email TEXT,
                role TEXT DEFAULT 'admin',
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 2. إنشاء جدول إعدادات النظام system_settings
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                setting_type TEXT DEFAULT 'string',
                group_name TEXT DEFAULT 'general',
                description TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 3. إنشاء جداول الحقول الديناميكية للمركبات والسائقين
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS vehicle_fields (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                label TEXT NOT NULL,
                required INTEGER DEFAULT 0
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS driver_fields (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                label TEXT NOT NULL,
                required INTEGER DEFAULT 0
            )
        """)

        # 4. إنشاء حساب أدمن افتراضي إذا لم يكن موجوداً (admin / admin123)
        cursor.execute("SELECT id FROM users WHERE username = 'admin'")
        admin_exists = cursor.fetchone()

        if not admin_exists:
            default_password_hash = generate_password_hash('admin123')
            cursor.execute("""
                INSERT INTO users (username, password_hash, full_name, email, role, is_active)
                VALUES (?, ?, ?, ?, ?, 1)
            """, ('admin', default_password_hash, 'مدير النظام', 'admin@semacom.com', 'admin'))

        conn.commit()
        conn.close()

    @staticmethod
    def get_user_by_id(user_id=1):
        """جلب بيانات مستخدم معين"""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, full_name, email, google_drive_email, role, is_active FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    @staticmethod
    def update_user_account(user_id, full_name, email, google_drive_email, current_password=None, new_password=None):
        """تحديث بيانات الحساب وكلمة المرور"""
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,))
        user = cursor.fetchone()

        if not user:
            conn.close()
            return False, "المستخدم غير موجود"

        # إذا طلب تغيير كلمة المرور
        if new_password:
            if not current_password or not check_password_hash(user['password_hash'], current_password):
                conn.close()
                return False, "كلمة المرور الحالية غير صحيحة"
            
            new_hash = generate_password_hash(new_password)
            cursor.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user_id))

        # تحديث باقي البيانات الشخصية وبريد Google Drive
        cursor.execute("""
            UPDATE users 
            SET full_name = ?, email = ?, google_drive_email = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (full_name, email, google_drive_email, user_id))

        conn.commit()
        conn.close()
        return True, "تم تحديث بيانات الحساب بنجاح"

    @staticmethod
    def get_all_grouped():
        """جلب كافة الإعدادات مقسمة حسب مجموعاتها"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT key, value, group_name FROM system_settings")
            rows = cursor.fetchall()
        except sqlite3.OperationalError:
            conn.close()
            return {}
            
        conn.close()

        grouped = {}
        for row in rows:
            group = row['group_name'] if row['group_name'] else 'general'
            key = row['key']
            val = row['value']
            
            try:
                val = json.loads(val)
            except (ValueError, TypeError):
                pass
                
            if group not in grouped:
                grouped[group] = {}
            grouped[group][key] = val
            
        return grouped

    @staticmethod
    def set_batch(data):
        """حفظ أو تحديث مجموعة من الإعدادات دفعة واحدة مع التوجيه للمجموعة المناسبة"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # ربط المفاتيح بمجموعاتها لضمان التنسيق
        group_mapping = {
            'smtp_server': 'smtp', 'smtp_port': 'smtp', 'smtp_email': 'smtp', 'smtp_password': 'smtp', 'smtp_use_tls': 'smtp',
            'gdrive_enabled': 'gdrive', 'gdrive_folder_id': 'gdrive', 'gdrive_client_id': 'gdrive', 'gdrive_client_secret': 'gdrive',
            'prefix_work_order': 'prefixes', 'prefix_store_item': 'prefixes', 'prefix_asset': 'prefixes',
            'appearance_theme': 'appearance', 'appearance_font_size': 'appearance', 'appearance_primary_color': 'appearance'
        }

        for key, value in data.items():
            if isinstance(value, (dict, list)):
                value_str = json.dumps(value, ensure_ascii=False)
            else:
                value_str = str(value)

            group_name = group_mapping.get(key, 'general')
                
            cursor.execute("""
                INSERT INTO system_settings (key, value, group_name)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    group_name = excluded.group_name,
                    updated_at = CURRENT_TIMESTAMP
            """, (key, value_str, group_name))
            
        conn.commit()
        conn.close()

    @staticmethod
    def get_dynamic_fields(entity_type):
        """جلب الحقول الديناميكية الخاصة بالمركبات أو السائقين"""
        table_name = "vehicle_fields" if entity_type == 'vehicle' else "driver_fields"
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(f"SELECT name, label, required FROM {table_name}")
            rows = cursor.fetchall()
            conn.close()
            return [dict(row) for row in rows]
        except sqlite3.OperationalError:
            conn.close()
            return []

    @staticmethod
    def add_dynamic_field(entity_type, name, label, required=False):
        """إضافة حقل ديناميكي جديد"""
        table_name = "vehicle_fields" if entity_type == 'vehicle' else "driver_fields"
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(f"""
                INSERT INTO {table_name} (name, label, required)
                VALUES (?, ?, ?)
            """, (name, label, 1 if required else 0))
            conn.commit()
            conn.close()
            return True, "تم إضافة الحقل بنجاح"
        except sqlite3.IntegrityError:
            conn.close()
            return False, "اسم الحقل موجود بالفعل"
        except Exception as e:
            conn.close()
            return False, f"حدث خطأ: {str(e)}"


def seed_fleet_initial_settings():
    """بذر البيانات والإعدادات الافتراضية لنظام أسطول سيماكم وتأكيد الجداول الأمنية"""
    # تهيئة جدول المستخدمين والأمان والجداول الأساسية أولاً
    SettingsService.init_security_and_users()

    defaults = [
        # البيانات العامة
        ('company_name', 'الشركة السعودية للكهرباء والتبريد للاستثمار (سيماكم)', 'string', 'general', 'اسم المنشأة الرئيسي'),
        ('currency', 'ر.س', 'string', 'general', 'العملة الافتراضية'),

        # قواعد الأسطول والصيانة
        ('insurance_alert_days', '30', 'number', 'fleet', 'تنبيه انتهاء التأمين (يوم)'),
        ('oil_change_interval_km', '5000', 'number', 'maintenance', 'فترة تغيير زيت المحرك (كم)'),
        ('default_min_stock_limit', '5', 'number', 'store', 'حد المخزون الأدنى الافتراضي'),

        # بادئات الترقيم
        ('prefix_work_order', 'WO-2026-', 'string', 'prefixes', 'بادئة أرقام أمر العمل'),
        ('prefix_store_item', 'STM-', 'string', 'prefixes', 'بادئة أرقام أصناف المستودع'),
        ('prefix_asset', 'SEMACOM-EQ-', 'string', 'prefixes', 'بادئة أرقام الأصول والعدّة'),

        # مظهر النظام الموحد
        ('appearance_theme', 'semacom', 'string', 'appearance', 'الثيم الموحد'),
        ('appearance_font_size', '17', 'number', 'appearance', 'حجم الخط الأساسي'),
        ('appearance_primary_color', '#1b365d', 'string', 'appearance', 'اللون الرئيسي للواجهة'),

        # إعدادات البريد الإلكتروني SMTP
        ('smtp_server', 'smtp.gmail.com', 'string', 'smtp', 'خادم إرسال البريد'),
        ('smtp_port', '587', 'number', 'smtp', 'منفذ البريد'),
        ('smtp_email', '', 'string', 'smtp', 'بريد إرسال التقارير والإنذارات'),
        ('smtp_password', '', 'string', 'smtp', 'كلمة مرور التطبيق لـ SMTP'),
        ('smtp_use_tls', '1', 'boolean', 'smtp', 'تفعيل تشفير TLS'),

        # إعدادات Google Drive
        ('gdrive_enabled', '0', 'boolean', 'gdrive', 'تفعيل مزامنة Google Drive'),
        ('gdrive_folder_id', '', 'string', 'gdrive', 'معرف مجلد التخزين السحابي'),
        ('gdrive_client_id', '', 'string', 'gdrive', 'Client ID لـ Google Cloud'),
        ('gdrive_client_secret', '', 'string', 'gdrive', 'Client Secret لـ Google Cloud'),

        # القوائم المرجعية
        ('external_workshops', json.dumps(["ورشة المحرك الذهبي", "مركز الفحص الشامل", "ورشة الهيدروليك الوطنية"], ensure_ascii=False), 'json', 'lookups', 'قائمة الورش الخارجية'),
        ('store_categories', json.dumps(["قطع غيار محركات", "زيوت وفلاتر", "إطارات وبطاريات", "مستلزمات كهربائية"], ensure_ascii=False), 'json', 'lookups', 'تصنيفات الأصناف بالمخزن')
    ]

    conn = get_db_connection()
    cursor = conn.cursor()

    for key, value, setting_type, group_name, description in defaults:
        cursor.execute("""
            INSERT INTO system_settings (key, value, setting_type, group_name, description)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(key) DO NOTHING
        """, (key, value, setting_type, group_name, description))

    conn.commit()
    conn.close()