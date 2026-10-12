from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from app import db  # كائن قاعدة البيانات SQLAlchemy / SQLite

class SystemSetting(db.Model):
    """جدول تخزين الإعدادات بنظام المفتاح والقيمة (Key-Value Dynamic Store)"""
    __tablename__ = 'system_settings'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    value = db.Column(db.Text, nullable=True)
    setting_type = db.Column(db.String(20), default='string')  # string, integer, float, boolean, json
    group_name = db.Column(db.String(50), default='general', index=True) # general, fleet, security, gdrive, smtp
    description = db.Column(db.String(255), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'key': self.key,
            'value': self.value,
            'setting_type': self.setting_type,
            'group_name': self.group_name,
            'description': self.description,
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S') if self.updated_at else None
        }

    @classmethod
    def get_val(cls, key, default=None):
        """دالة مساعدة للحصول على قيمة إعداد سريعاً"""
        setting = cls.query.filter_by(key=key).first()
        return setting.value if setting else default

    @classmethod
    def set_val(cls, key, value, group_name='general', setting_type='string', description=None):
        """دالة مساعدة لحفظ أو تحديث قيمة إعداد"""
        setting = cls.query.filter_by(key=key).first()
        if not setting:
            setting = cls(key=key, group_name=group_name, setting_type=setting_type, description=description)
            db.session.add(setting)
        setting.value = str(value) if value is not None else ""
        setting.updated_at = datetime.utcnow()
        db.session.commit()
        return setting


class User(db.Model):
    """جدول مستخدمي النظام والحسابات بالأمان والبريد"""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(100), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    google_drive_email = db.Column(db.String(120), nullable=True) # بريد Google Drive المخصص للمزامنة والنسخ الاحتياطي
    role = db.Column(db.String(30), default='admin') # admin, manager, user
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def set_password(self, password):
        """تشفير كلمة المرور بحماية Werkzeug"""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """التحقق من صحة كلمة المرور"""
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'full_name': self.full_name or '',
            'email': self.email or '',
            'google_drive_email': self.google_drive_email or '',
            'role': self.role,
            'is_active': self.is_active,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None
        }


class VehicleFieldModel(db.Model):
    """ربط مع جدول vehicle_fields في السكيما"""
    __tablename__ = 'vehicle_fields'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    label = db.Column(db.String(100), nullable=False)
    required = db.Column(db.Integer, default=0)

    def to_dict(self):
        return {'id': self.id, 'name': self.name, 'label': self.label, 'required': bool(self.required)}


class DriverFieldModel(db.Model):
    """ربط مع جدول driver_fields في السكيما"""
    __tablename__ = 'driver_fields'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    label = db.Column(db.String(100), nullable=False)
    required = db.Column(db.Integer, default=0)

    def to_dict(self):
        return {'id': self.id, 'name': self.name, 'label': self.label, 'required': bool(self.required)}


def init_default_security_data():
    """إنشاء حساب المدير الافتراضي وإعدادات النظام الأساسية للبريد والـ Drive عند التشغيل لأول مرة"""
    db.create_all()

    # 1. إنشاء حساب مدير افتراضي إن لم يكن موجوداً (المستخدم: admin / كلمة المرور: admin123)
    admin_user = User.query.filter_by(username='admin').first()
    if not admin_user:
        admin_user = User(
            username='admin',
            full_name='مدير النظام',
            email='admin@semacom.com',
            role='admin',
            is_active=True
        )
        admin_user.set_password('admin123')
        db.session.add(admin_user)
        db.session.commit()

    # 2. إدخال المفاتيح المبدئية للـ Google Drive وإعدادات البريد SMTP
    default_keys = [
        ('gdrive_enabled', '0', 'gdrive', 'مفتاح تفعيل المزامنة مع Google Drive (1/0)'),
        ('gdrive_folder_id', '', 'gdrive', 'معرّف مجلد النسخ الاحتياطي على Google Drive'),
        ('gdrive_client_id', '', 'gdrive', 'Client ID لربط Google Drive API'),
        ('gdrive_client_secret', '', 'gdrive', 'Client Secret لربط Google Drive API'),
        ('gdrive_refresh_token', '', 'gdrive', 'Refresh Token لتوثيق Google Drive'),
        ('smtp_server', 'smtp.gmail.com', 'smtp', 'خادم إرسال البريد SMTP'),
        ('smtp_port', '587', 'smtp', 'منفذ خادم البريد'),
        ('smtp_email', '', 'smtp', 'عنوان بريد الإرسال للإنذارات والتقارير'),
        ('smtp_password', '', 'smtp', 'كلمة مرور البريد الإلكتروني أو App Password'),
        ('smtp_use_tls', '1', 'smtp', 'تفعيل التشفير TLS (1/0)')
    ]

    for key, default_val, group, desc in default_keys:
        if not SystemSetting.query.filter_by(key=key).first():
            setting = SystemSetting(key=key, value=default_val, group_name=group, description=desc)
            db.session.add(setting)
    
    db.session.commit()