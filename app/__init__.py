import os
import re
import secrets
import sqlite3
from contextlib import closing
from pathlib import Path
from flask import Flask, render_template, Blueprint, redirect, url_for, session, request
from jinja2 import ChoiceLoader, FileSystemLoader
from core.database import DB_PATH

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# استيراد بلوبرنت المهام والإشعارات
from modules.tasks.routers import tasks_bp
from modules.notifications.routers import notifications_bp

# استيراد بلوبرنتات الورشة الفرعية (المستودع، الفريق، الفحص الشامل، ومتابعة الزيوت)
from modules.workshop.store.routers import store_bp
from modules.workshop.team.routers import team_bp
from modules.workshop.comp_inspection.router import comp_inspection_bp
from modules.workshop.oil_tracking.router import oil_tracking_bp

# استيراد بلوبرنت مركز التقارير
from modules.reports.routers import reports_bp


def init_db():
    db_path = DB_PATH
    schema_path = PROJECT_ROOT / "database" / "schema.sql"

    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # 1. تنفيذ ملف السكيما المحدث إن وجد
    if schema_path.exists():
        try:
            with open(str(schema_path), "r", encoding="utf-8") as f:
                script_content = f.read().strip()
                if script_content:
                    conn.executescript(script_content)
        except sqlite3.OperationalError as e:
            print(f"تحذير أثناء قراءة schema.sql: {e}")
            
    # 2. التأكد من إنشاء جدول المركبات الأساسي بكافة الحقول
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vehicles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plate_number TEXT UNIQUE NOT NULL,
            vehicle_code TEXT,
            vehicle_type TEXT,
            model TEXT,
            manufacturer TEXT,
            color TEXT,
            fuel_type TEXT,
            engine_number TEXT,
            chassis_number TEXT,
            status TEXT DEFAULT 'متاحة',
            workshop_status TEXT DEFAULT 'متاحة',
            ownership TEXT
        )
    """)
    for column_name, column_type in (
        ("status", "TEXT DEFAULT 'متاحة'"),
        ("workshop_status", "TEXT DEFAULT 'متاحة'"),
        ("ownership", "TEXT"),
    ):
        try:
            cursor.execute(f'ALTER TABLE vehicles ADD COLUMN "{column_name}" {column_type}')
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e).lower():
                raise
    cursor.execute(
        "UPDATE vehicles SET workshop_status = 'تحت الصيانة', status = 'متاحة' "
        "WHERE status = 'تحت الصيانة' "
        "AND (workshop_status IS NULL OR workshop_status = '' OR workshop_status = 'متاحة')"
    )
    cursor.execute(
        "UPDATE vehicles SET workshop_status = 'متاحة' "
        "WHERE workshop_status IS NULL OR workshop_status = ''"
    )
    cursor.execute(
        "UPDATE vehicles SET status = 'متاحة' WHERE status IS NULL OR status = '' OR status = 'active'"
    )

    # 3. القائمة المرجعية الشاملة لكافة حقول الصيانة (الداخلية، الخارجية، الطارئة، الاستثنائية)
    ALL_MAINTENANCE_COLUMNS = [
        ('order_no', 'TEXT'),
        ('type', 'TEXT'),
        ('order_type', 'TEXT'),
        ('status', 'TEXT DEFAULT "open"'),
        ('vehicle_id', 'TEXT'),
        ('vehicle_code', 'TEXT'),
        ('plate_number', 'TEXT'),
        ('driver_id', 'TEXT'),

        # 🛠️ 1. الصيانة الداخلية
        ('maintenance_type', 'TEXT'),
        ('fault_description', 'TEXT'),
        ('fault_cause', 'TEXT'),
        ('severity', 'TEXT'),
        ('technician_name', 'TEXT'),
        ('expected_completion_time', 'TEXT'),
        ('order_date', 'TEXT'),
        ('closure_date', 'TEXT'),
        ('closure_reason', 'TEXT'),
        ('spare_parts', 'TEXT'),
        ('final_cost', 'REAL DEFAULT 0'),
        ('recommendation', 'TEXT'),

        # 🏢 2. الصيانة الخارجية
        ('workshop_name', 'TEXT'),
        ('workshop_phone', 'TEXT'),
        ('workshop_location', 'TEXT'),
        ('send_reason', 'TEXT'),
        ('send_datetime', 'TEXT'),
        ('responsible_person', 'TEXT'),
        ('expected_cost', 'REAL DEFAULT 0'),
        ('expected_time', 'TEXT'),
        ('notes', 'TEXT'),
        ('receipt_datetime', 'TEXT'),
        ('closing_notes', 'TEXT'),

        # 🚨 3. الصيانة الطارئة
        ('reporter_name', 'TEXT'),
        ('case_description', 'TEXT'),
        ('has_injuries', 'TEXT'),
        ('is_drivable', 'TEXT'),
        ('official_notified', 'TEXT'),
        ('emergency_location', 'TEXT'),
        ('action_taken', 'TEXT'),
        ('is_towed', 'TEXT'),
        ('towing_party', 'TEXT'),
        ('intervention_team', 'TEXT'),

        # ⭐ 4. الصيانة الاستثنائية
        ('incident_datetime', 'TEXT'),
        ('subject', 'TEXT'),
        ('description', 'TEXT'),
        ('causes', 'TEXT'),
        ('other_details', 'TEXT'),
        ('closure_datetime', 'TEXT'),
        ('treatment_details', 'TEXT'),

        # 📁 المرفقات المشتركة
        ('photo_before', 'TEXT'),
        ('photo_after', 'TEXT'),
        ('other_attachments', 'TEXT'),

        # حقول النظام الإضافية
        ('created_at', 'TEXT DEFAULT CURRENT_TIMESTAMP')
    ]

    # 4. إنشـاء جدول أوامر الصيانة بجميع الحقول إذا كان غير موجود
    columns_sql = ",\n".join([f"{col} {datatype}" for col, datatype in ALL_MAINTENANCE_COLUMNS])
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS maintenance_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            {columns_sql}
        )
    """)

    # 5. ترقية جدول أوامر الصيانة القائم وتوليد كافة الأعمدة الناقصة
    cursor.execute("PRAGMA table_info(maintenance_orders)")
    existing_columns = [col[1] for col in cursor.fetchall()]

    for col_name, col_type in ALL_MAINTENANCE_COLUMNS:
        if col_name not in existing_columns:
            try:
                cursor.execute(f"ALTER TABLE maintenance_orders ADD COLUMN {col_name} {col_type};")
                print(f"✅ تم إضافة العمود الناقص ({col_name}) إلى جدول maintenance_orders بنجاح.")
            except sqlite3.OperationalError as e:
                print(f"تنبيه أثناء إضافة {col_name}: {e}")

    # 6. إنشاء جداول الفحص الشامل والتشغيلي للأسطول والمعدات
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS comprehensive_inspections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vehicle_plate TEXT NOT NULL,
            inspector_name TEXT NOT NULL,
            inspection_date TEXT NOT NULL,
            current_mileage TEXT,
            oil_change_mileage TEXT,
            overall_status TEXT,
            notes TEXT,
            document_number TEXT DEFAULT 'No.000000',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS comprehensive_inspection_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inspection_id INTEGER,
            category TEXT,      
            item_name TEXT,     
            status TEXT,        
            item_notes TEXT,
            FOREIGN KEY (inspection_id) REFERENCES comprehensive_inspections(id) ON DELETE CASCADE
        )
    """)

    # 7. إنشاء جدول متابعة وتغيير الزيوت والفلاتر المستقل (حسب المسافة أو الوقت)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS oil_change_tracking (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_plate TEXT NOT NULL,
    technician_name TEXT NOT NULL,
    service_date TEXT NOT NULL,
    current_mileage TEXT,
    last_oil_mileage TEXT,
    distance_interval INTEGER DEFAULT 5000,
    time_interval_months INTEGER DEFAULT 3,
    distance_alert_threshold INTEGER DEFAULT 1000, -- حد التنبيه بالمسافة المخصص
    time_alert_threshold INTEGER DEFAULT 15,       -- حد التنبيه بالوقت بالأيام المخصص
    tracking_mode TEXT DEFAULT 'distance',
    overall_status TEXT DEFAULT 'سليم',
    notes TEXT,
    document_number TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
    """)

    # 8. التأكد الوقائي من وجود جداول مركز التقارير والإعدادات
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS generated_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_uuid TEXT UNIQUE NOT NULL,
            doc_number TEXT UNIQUE NOT NULL,
            module_name TEXT NOT NULL,
            report_type TEXT NOT NULL,
            title TEXT NOT NULL,
            template_key TEXT NOT NULL,
            parameters_json TEXT,
            local_pdf_path TEXT,
            local_report_path TEXT,
            local_qr_path TEXT,
            drive_file_id TEXT,
            drive_web_url TEXT,
            sync_status TEXT DEFAULT 'pending',
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("PRAGMA table_info(generated_reports)")
    generated_report_columns = [column[1] for column in cursor.fetchall()]
    if 'local_report_path' not in generated_report_columns:
        cursor.execute("ALTER TABLE generated_reports ADD COLUMN local_report_path TEXT")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS report_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_key TEXT UNIQUE NOT NULL,
            module_name TEXT NOT NULL,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT,
            template_path TEXT NOT NULL,
            is_active INTEGER DEFAULT 1
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS system_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE NOT NULL,
            value TEXT,
            setting_type TEXT DEFAULT 'string',
            group_name TEXT DEFAULT 'general',
            description TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

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

    conn.commit()
    conn.close()
    print("✅ تم فحص وتهيئة قاعدة البيانات بنجاح مع إضافة جداول الفحص الشامل ومتابعة الزيوت ومركز التقارير.")


def create_app():
    # 1. إنشاء التطبيق وتهيئة الإعدادات الأساسية أولاً
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent / "templates"),
        static_folder=str(Path(__file__).parent / "static"),
    )

    is_production = os.environ.get("APP_ENV", "development").strip().lower() == "production"
    secret_key = os.environ.get("SECRET_KEY")
    if is_production and not secret_key:
        raise RuntimeError("SECRET_KEY must be set when APP_ENV=production.")
    app.secret_key = secret_key or secrets.token_hex(32)
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=is_production,
        MAX_CONTENT_LENGTH=32 * 1024 * 1024,
    )

    # تحديث الـ ChoiceLoader ليشمل مسارات الـ views لكل موديول (بما فيها الفحص الشامل ومتابعة الزيوت ومركز التقارير)
    app.jinja_loader = ChoiceLoader([
        FileSystemLoader(str(Path(__file__).parent / "templates")),
        FileSystemLoader(str(Path(__file__).parent.parent / "modules")),
        FileSystemLoader(str(Path(__file__).parent.parent / "modules" / "settings" / "views")),
        FileSystemLoader(str(Path(__file__).parent.parent / "modules" / "accidents" / "views")),
        FileSystemLoader(str(Path(__file__).parent.parent / "modules" / "violations" / "views")),
        FileSystemLoader(str(Path(__file__).parent.parent / "modules" / "handover" / "views")),
        FileSystemLoader(str(Path(__file__).parent.parent / "modules" / "vehicles" / "views")),
        FileSystemLoader(str(Path(__file__).parent.parent / "modules" / "drivers" / "views")),
        FileSystemLoader(str(Path(__file__).parent.parent / "modules" / "insurance" / "views")),
        FileSystemLoader(str(Path(__file__).parent.parent / "modules" / "inspection" / "views")),
        FileSystemLoader(str(Path(__file__).parent.parent / "modules" / "reports" / "views")),
        FileSystemLoader(str(Path(__file__).parent.parent / "modules" / "workshop" / "store" / "views")),
        FileSystemLoader(str(Path(__file__).parent.parent / "modules" / "workshop" / "equ" / "views")),
        FileSystemLoader(str(Path(__file__).parent.parent / "modules" / "workshop" / "team" / "views")),
        FileSystemLoader(str(Path(__file__).parent.parent / "modules" / "workshop" / "maintenance" / "views")),
        FileSystemLoader(str(Path(__file__).parent.parent / "modules" / "workshop" / "comp_inspection" / "views")),
        FileSystemLoader(str(Path(__file__).parent.parent / "modules" / "workshop" / "oil_tracking" / "views")),
    ])

    # 2. تهيئة قاعدة البيانات العامة والجداول الفرعية داخل سياق التطبيق
    with app.app_context():
        init_db()
        
        # استدعاء دوال تهيئة الجداول والموديولات الفرعية
        from modules.handover.models.handover_model import init_handover_db
        from modules.violations.services.violations_service import init_violations_db
        from modules.accidents.models.accidents_model import init_accidents_db
        from modules.insurance.services.insurance_service import InsuranceService
        from modules.inspection.models.inspection_model import InspectionModel
        from modules.inspection.services.inspection_service import InspectionService
        
        # استدعاء دالة تهيئة جدول الصيانة الشامل
        from modules.workshop.maintenance.models.maintenance_models import init_maintenance_table

        # تهيئة الأمان والمستخدمين وبذر الإعدادات الافتراضية
        from modules.settings.services.settings_service import SettingsService, seed_fleet_initial_settings
        
        init_handover_db()
        init_violations_db()
        init_accidents_db()
        InsuranceService.init_module()
        
        # تهيئة جدول ومجلدات الفحص الدوري
        InspectionModel.create_table()
        
        # تنفيذ تهيئة جدول الصيانة فور إقلاع التطبيق
        init_maintenance_table()

        from modules.tasks.services.tasks_service import TasksService
        TasksService.initialize()

        # تهيئة جداول الحسابات والأمان
        SettingsService.init_security_and_users()

        # زراعة إعدادات أسطول سيماكم التلقائية
        try:
            seed_fleet_initial_settings()
        except Exception as e:
            print(f"تنبيه أثناء زراعة إعدادات النظام: {e}")

    @app.errorhandler(404)
    def page_not_found(_error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def internal_server_error(error):
        app.logger.error("Unhandled server error: %s", error)
        return render_template("errors/500.html"), 500

    # ==========================================
    # 🛡️ نظام الحماية الشامل لجميع المسارات
    # ==========================================
    @app.before_request
    def require_login():
        # إذا كان الطلب لمورد غير معروف أو ملف استثنائي
        if request.endpoint is None:
            return

        # المسارات المسموح بها بدون تسجيل دخول
        allowed_endpoints = [
            'settings.login',
            'static',
            'reports.public_view_document',
            'vehicles.public_landing',
            'vehicles.public_information',
            'vehicles.public_request_update',
            'vehicles.public_issue_form',
            'vehicles.public_submit_issue',
        ]
        
        # السماح بصفحة تسجيل الدخول والملفات الثابتة (css/js/images)
        if request.endpoint in allowed_endpoints or request.endpoint.startswith('static.'):
            return

        # إعادة التوجيه إلى تسجيل الدخول إن لم تكن هناك جلسة
        if 'user_id' not in session:
            return redirect(url_for('settings.login'))

    @app.context_processor
    def inject_appearance_settings():
        try:
            with closing(sqlite3.connect(str(DB_PATH))) as connection:
                rows = connection.execute(
                    "SELECT key, value FROM system_settings WHERE key IN "
                    "('appearance_theme', 'appearance_font_size', 'appearance_primary_color')"
                ).fetchall()
            saved = dict(rows)
        except sqlite3.Error as error:
            app.logger.error("Unable to load appearance settings: %s", error)
            saved = {}
        themes = {
            "semacom": "#1b365d",
            "teal": "#087e82",
            "forest": "#356548",
            "violet": "#614b8b",
        }
        theme = saved.get("appearance_theme", "semacom")
        if theme not in themes:
            theme = "semacom"

        primary = saved.get("appearance_primary_color", themes[theme])
        if not isinstance(primary, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", primary):
            primary = themes[theme]

        try:
            font_size = int(saved.get("appearance_font_size", "17"))
        except (TypeError, ValueError):
            font_size = 17
        font_size = min(max(font_size, 15), 21)

        return {
            "appearance": {
                "theme": theme,
                "primary_color": primary,
                "font_size": font_size,
                "style": f"--app-primary: {primary}; --app-font-size: {font_size}px;",
            }
        }

    @app.context_processor
    def inject_notification_count():
        user_id = session.get("user_id")
        if not user_id:
            return {"notification_unread_count": 0}
        from modules.notifications.services.notifications_service import NotificationsService

        try:
            unread_count = NotificationsService.unread_count(user_id)
        except sqlite3.Error as error:
            app.logger.error("Unable to load notification count: %s", error)
            unread_count = 0
        return {"notification_unread_count": unread_count}

    @app.route("/")
    def home():
        return render_template("home.html")

    # ==========================================
    # ⚙️ تسجيل موديولات النظام والبلوبرنتات
    # ==========================================
    from modules.settings.routers import settings_bp
    app.register_blueprint(settings_bp, url_prefix='/settings')

    # تسجيل موديول المركبات
    from modules.vehicles.routers import vehicles_bp
    app.register_blueprint(vehicles_bp)
    
    # تسجيل موديول السائقين
    from modules.drivers.routers import drivers_bp
    app.register_blueprint(drivers_bp)

    # تسجيل موديول الورشة والصيانة الرئيسي
    from modules.workshop.routers import workshop_bp
    app.register_blueprint(workshop_bp)

    from modules.handover.routers import handover_bp
    app.register_blueprint(handover_bp)

    from modules.violations.routers import violations_bp
    app.register_blueprint(violations_bp)

    # تسجيل موديول الحوادث المرورية
    from modules.accidents.routers import accidents_bp
    app.register_blueprint(accidents_bp)

    # تسجيل موديول وثائق التأمين
    from modules.insurance.routers import insurance_bp
    app.register_blueprint(insurance_bp)

    # تسجيل موديول الفحص الدوري للمركبات
    from modules.inspection.routers import inspection_bp
    app.register_blueprint(inspection_bp, url_prefix='/inspection')

    # 📊 تسجيل موديول مركز التقارير الرئيسي
    app.register_blueprint(reports_bp)

    # تسجيل بلوبرنت المهام والإشعارات
    app.register_blueprint(tasks_bp, url_prefix='/tasks')
    app.register_blueprint(notifications_bp, url_prefix='/notifications')

    # تسجيل بلوبرنتات الورشة الفرعية (المخزن، الفريق، الفحص الشامل، ومتابعة الزيوت)
    app.register_blueprint(store_bp, url_prefix='/workshop/store')
    app.register_blueprint(team_bp, url_prefix='/workshop/team')
    app.register_blueprint(comp_inspection_bp, url_prefix='/workshop/comp-inspection')
    app.register_blueprint(oil_tracking_bp, url_prefix='/workshop/oil-tracking')

    return app
