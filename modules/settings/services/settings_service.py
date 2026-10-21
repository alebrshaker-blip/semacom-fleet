import json

from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash, check_password_hash

from core.database import init_orm_schema
from modules.settings import repository
from modules.settings.reference_lists import REFERENCE_LISTS


class SettingsService:

    @staticmethod
    def init_security_and_users():
        """إنشاء جداول المستخدمين والإعدادات والحقول الديناميكية وحساب المدير الافتراضي"""
        init_orm_schema()
        repository.ensure_default_admin(generate_password_hash('admin123'))

    @staticmethod
    def get_user_by_id(user_id=1):
        """جلب بيانات مستخدم معين"""
        user = repository.get_user(user_id)
        if not user:
            return None
        return {key: user[key] for key in (
            'id', 'username', 'full_name', 'email', 'google_drive_email', 'role', 'is_active'
        )}

    @staticmethod
    def update_user_account(user_id, full_name, email, google_drive_email, current_password=None, new_password=None):
        """تحديث بيانات الحساب وكلمة المرور"""
        user = repository.get_user(user_id)
        if not user:
            return False, "المستخدم غير موجود"

        values = {
            'full_name': full_name, 'email': email, 'google_drive_email': google_drive_email,
        }
        if new_password:
            if not current_password or not check_password_hash(user['password_hash'], current_password):
                return False, "كلمة المرور الحالية غير صحيحة"
            values['password_hash'] = generate_password_hash(new_password)

        repository.update_user_fields(user_id, **values)
        return True, "تم تحديث بيانات الحساب بنجاح"

    @staticmethod
    def get_all_grouped():
        """جلب كافة الإعدادات مقسمة حسب مجموعاتها"""
        return repository.get_grouped_settings(raw=False)

    @staticmethod
    def set_batch(data):
        """حفظ أو تحديث مجموعة من الإعدادات دفعة واحدة مع التوجيه للمجموعة المناسبة"""
        group_mapping = {
            'smtp_server': 'smtp', 'smtp_port': 'smtp', 'smtp_email': 'smtp',
            'smtp_username': 'smtp',
            'smtp_password': 'smtp', 'smtp_use_tls': 'smtp',
            'smtp_from_name': 'smtp', 'smtp_security': 'smtp',
            'smtp_enabled': 'smtp', 'email_reports_enabled': 'smtp',
            'email_password_reset_enabled': 'smtp',
            'email_fleet_digest_enabled': 'smtp',
            'email_fleet_digest_day': 'smtp', 'email_fleet_digest_hour': 'smtp',
            'gdrive_enabled': 'gdrive', 'gdrive_folder_id': 'gdrive', 'gdrive_client_id': 'gdrive', 'gdrive_client_secret': 'gdrive',
            'prefix_work_order': 'prefixes', 'prefix_store_item': 'prefixes', 'prefix_asset': 'prefixes',
            'appearance_theme': 'appearance', 'appearance_font_size': 'appearance', 'appearance_primary_color': 'appearance'
        }
        items = []
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                value_str = json.dumps(value, ensure_ascii=False)
            else:
                value_str = str(value)
            items.append((key, value_str, group_mapping.get(key, 'general')))
        repository.upsert_settings(items)

    @staticmethod
    def get_dynamic_fields(entity_type):
        """جلب الحقول الديناميكية الخاصة بالمركبات أو السائقين"""
        return [
            {'name': f['name'], 'label': f['label'], 'required': f['required']}
            for f in repository.list_dynamic_fields(entity_type)
        ]

    @staticmethod
    def add_dynamic_field(entity_type, name, label, required=False):
        """إضافة حقل ديناميكي جديد"""
        try:
            repository.add_dynamic_field(entity_type, name, label, required)
            return True, "تم إضافة الحقل بنجاح"
        except IntegrityError:
            return False, "اسم الحقل موجود بالفعل"
        except Exception as e:
            return False, f"حدث خطأ: {str(e)}"


def seed_fleet_initial_settings():
    """بذر البيانات والإعدادات الافتراضية لنظام المركبات والمعدات وتأكيد الجداول الأمنية"""
    # تهيئة جدول المستخدمين والأمان والجداول الأساسية أولاً
    SettingsService.init_security_and_users()

    defaults = [
        # البيانات العامة
        ('company_name', 'الشركة السعودية للكهرباء والتبريد للاستثمار (سيماكم)', 'string', 'general', 'اسم المنشأة الرئيسي'),
        ('currency', 'ر.س', 'string', 'general', 'العملة الافتراضية'),

        # قواعد المركبات والمعدات والصيانة
        ('license_alert_enabled', '1', 'boolean', 'fleet', 'تفعيل تنبيه انتهاء رخص القيادة'),
        ('license_alert_days', '30', 'number', 'fleet', 'التنبيه بانتهاء الرخص قبل (يوم)'),
        ('inspection_alert_enabled', '1', 'boolean', 'fleet', 'تفعيل تنبيه انتهاء الفحص الدوري'),
        ('inspection_alert_days', '30', 'number', 'fleet', 'التنبيه بانتهاء الفحص الدوري قبل (يوم)'),
        ('insurance_alert_enabled', '1', 'boolean', 'fleet', 'تفعيل تنبيه انتهاء التأمين'),
        ('insurance_alert_days', '30', 'number', 'fleet', 'تنبيه انتهاء التأمين (يوم)'),
        ('oil_alert_enabled', '1', 'boolean', 'fleet', 'تفعيل تنبيهات تغيير الزيوت'),
        ('oil_change_interval_km', '5000', 'number', 'fleet', 'فترة تغيير زيت المحرك (كم)'),
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
        ('smtp_username', '', 'string', 'smtp', 'اسم المستخدم لتسجيل الدخول إلى خادم SMTP'),
        ('smtp_password', '', 'string', 'smtp', 'كلمة مرور التطبيق لـ SMTP'),
        ('smtp_use_tls', '1', 'boolean', 'smtp', 'تفعيل تشفير TLS'),
        ('smtp_from_name', 'SEMACOM', 'string', 'smtp', 'اسم مرسل البريد'),
        ('smtp_security', 'starttls', 'string', 'smtp', 'نوع تشفير اتصال SMTP'),
        ('smtp_enabled', '0', 'boolean', 'smtp', 'تفعيل إرسال البريد من النظام'),
        ('email_reports_enabled', '1', 'boolean', 'smtp', 'السماح بإرسال التقارير المعتمدة بالبريد'),
        ('email_password_reset_enabled', '1', 'boolean', 'smtp', 'السماح باستعادة كلمة المرور عبر البريد'),
        ('email_fleet_digest_enabled', '1', 'boolean', 'smtp', 'تفعيل ملخص تنبيهات المركبات والمعدات الأسبوعي'),
        ('email_fleet_digest_day', '0', 'number', 'smtp', 'يوم إرسال ملخص المركبات والمعدات (0 الإثنين إلى 6 الأحد)'),
        ('email_fleet_digest_hour', '9', 'number', 'smtp', 'ساعة إرسال ملخص المركبات والمعدات حسب توقيت الخادم'),

        # إعدادات Google Drive
        ('gdrive_enabled', '0', 'boolean', 'gdrive', 'تفعيل مزامنة Google Drive'),
        ('gdrive_folder_id', '', 'string', 'gdrive', 'معرف مجلد التخزين السحابي'),
        ('gdrive_client_id', '', 'string', 'gdrive', 'Client ID لـ Google Cloud'),
        ('gdrive_client_secret', '', 'string', 'gdrive', 'Client Secret لـ Google Cloud'),

        # القوائم المرجعية
    ]
    defaults.extend(
        (
            definition['setting_key'],
            json.dumps(definition['defaults'], ensure_ascii=False),
            'json',
            'lookups',
            definition['label'],
        )
        for definition in REFERENCE_LISTS.values()
    )

    repository.seed_defaults(defaults)

    for key, description in (
        ('email_fleet_digest_enabled', 'تفعيل ملخص تنبيهات المركبات والمعدات الأسبوعي'),
        ('email_fleet_digest_day', 'يوم إرسال ملخص المركبات والمعدات (0 الإثنين إلى 6 الأحد)'),
        ('email_fleet_digest_hour', 'ساعة إرسال ملخص المركبات والمعدات حسب توقيت الخادم'),
    ):
        repository.update_setting_description(key, description)

    legacy_categories = json.dumps(
        ["قطع غيار محركات", "زيوت وفلاتر", "إطارات وبطاريات", "مستلزمات كهربائية"],
        ensure_ascii=False,
    )
    repository.replace_setting_value(
        'store_categories',
        legacy_categories,
        json.dumps(REFERENCE_LISTS['store_categories']['defaults'], ensure_ascii=False),
    )

    repository.normalize_user_roles()
    repository.set_setting_group('oil_change_interval_km', 'fleet')
