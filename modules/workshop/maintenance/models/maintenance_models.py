import sqlite3
from pathlib import Path
from core.database import DB_PATH

def get_effective_db_path():
    return DB_PATH


def dict_factory(cursor, row):
    """تحويل صفوف قاعدة البيانات إلى قواميس لسهولة الاستخدام .get()"""
    fields = [column[0] for column in cursor.description]
    return {key: value for key, value in zip(fields, row)}


class MaintenanceModel:
    @staticmethod
    def get_connection():
        target_path = get_effective_db_path()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(target_path))
        conn.row_factory = dict_factory
        return conn

    @classmethod
    def execute_query(cls, query, params=()):
        conn = cls.get_connection()
        cur = conn.cursor()
        try:
            cur.execute(query, params)
            conn.commit()
        finally:
            conn.close()

    @classmethod
    def fetch_all(cls, query, params=()):
        conn = cls.get_connection()
        cur = conn.cursor()
        try:
            cur.execute(query, params)
            result = cur.fetchall()
        finally:
            conn.close()
        return result

    @classmethod
    def fetch_one(cls, query, params=()):
        conn = cls.get_connection()
        cur = conn.cursor()
        try:
            cur.execute(query, params)
            result = cur.fetchone()
        finally:
            conn.close()
        return result


def init_maintenance_table():
    """إنشاء جدول الصيانة الموحد وجدول فريق العمل إذا لم يسبق إنشاؤهما"""
    
    # تم توحيد جميع الحقول المطلوبة للصيانة (الداخلية، الخارجية، الطارئة، الاستثنائية)
    query_orders = """
    CREATE TABLE IF NOT EXISTS maintenance_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        status TEXT DEFAULT 'open',
        type TEXT NOT NULL, -- نوع الصيانة: internal, external, emergency, exceptional

        -- =======================================
        -- 1. بيانات الفتح (مشتركة ومخصصة)
        -- =======================================
        order_no TEXT UNIQUE NOT NULL,
        vehicle_code TEXT,           -- كود المركبة
        plate_number TEXT,           -- رقم اللوحة
        vehicle_id TEXT,
        driver_id TEXT,              -- السائق المرتبط بالأمر
        
        -- حقول عامة (داخلية وخارجية وطارئة)
        maintenance_type TEXT,       -- نوع الصيانة
        fault_description TEXT,      -- وصف العطل
        fault_cause TEXT,            -- سبب العطل
        severity TEXT,               -- درجة الخطورة
        
        -- مخصص للداخلية
        technician_name TEXT,        -- الفني المستلم
        expected_completion_time TEXT, -- الوقت المتوقع للانجاز
        order_date TEXT,             -- تاريخ أمر العمل
        
        -- مخصص للخارجية
        workshop_name TEXT,          -- اسم الورشة الخارجية
        workshop_phone TEXT,         -- رقم التواصل
        workshop_location TEXT,      -- موقع الورشة
        send_reason TEXT,            -- سبب الارسال
        send_datetime TEXT,          -- تاريخ ووقت الارسال
        responsible_person TEXT,     -- المسؤل/المتابع
        expected_cost REAL DEFAULT 0.0, -- التكلفة المتوقعة
        expected_time TEXT,          -- الوقت المتوقع
        notes TEXT,                  -- الملاحظات (قبل الاقفال)
        
        -- مخصص للطارئة
        driver_name TEXT,            -- اسم السائق
        reporter_name TEXT,          -- اسم المبلغ
        case_description TEXT,       -- وصف الحالة
        has_injuries TEXT,           -- هل يوجد اصابات (نعم/لا)
        is_drivable TEXT,            -- هل المركبة قابل للحركة (نعم/لا)
        official_notified TEXT,      -- هل تم ابلاغ جهة رسمية
        emergency_location TEXT,     -- موقع الحالة الطارئة
        
        -- مخصص للاستثنائية
        incident_datetime TEXT,      -- التاريخ والوقت
        subject TEXT,                -- الموضوع
        description TEXT,            -- الوصف
        causes TEXT,                 -- الاسباب
        other_details TEXT,          -- أخرى (تفاصيل اضافية)

        -- =======================================
        -- 2. بيانات الإقفال
        -- =======================================
        closure_date TEXT,           -- تاريخ الاقفال (للداخلية والخارجية)
        receipt_datetime TEXT,       -- تاريخ ووقت الاستلام (للخارجية)
        closure_datetime TEXT,       -- تاريخ ووقت التقفيل (للاستثنائية)
        
        closure_reason TEXT,         -- سبب الاقفال (معالجة كليا، جزئيا، اخرى)
        
        action_taken TEXT,           -- الإجراء المتخذ (للطارئة)
        is_towed TEXT,               -- هل تم سحب المركبة (للطارئة)
        towing_party TEXT,           -- جهة السحب (للطارئة)
        intervention_team TEXT,      -- فريق التدخل (للطارئة)
        
        treatment_details TEXT,      -- المعالجة (للاستثنائية)
        closing_notes TEXT,          -- ملاحظات الاقفال (للخارجية والاستثنائية)
        
        spare_parts TEXT,            -- قطع الغيار المستخدمة
        final_cost REAL DEFAULT 0.0, -- التكلفة النهائية
        recommendation TEXT,         -- التوصية

        -- =======================================
        -- 3. المرفقات (مشتركة للجميع)
        -- =======================================
        photo_before TEXT,           -- صور قبل
        photo_after TEXT,            -- صور بعد
        other_attachments TEXT       -- مرفقات اخرى
    )
    """
    MaintenanceModel.execute_query(query_orders)

    query_team = """
    CREATE TABLE IF NOT EXISTS team_members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT,
        name TEXT,
        job_title TEXT,
        phone TEXT
    )
    """
    MaintenanceModel.execute_query(query_team)