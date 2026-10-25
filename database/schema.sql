-- ==========================================
-- 1. جدول الحقول للمركبات (الثابتة والديناميكية)
-- ==========================================
CREATE TABLE IF NOT EXISTS vehicle_fields (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    label TEXT NOT NULL,
    required INTEGER DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1
);

-- ==========================================
-- 2. جدول المركبات الرئيسي
-- ==========================================
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
);

-- ==========================================
-- 2.1 سجل أرشفة المركبات الخارجة عن الخدمة
-- ==========================================
CREATE TABLE IF NOT EXISTS vehicle_archive (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id INTEGER NOT NULL UNIQUE,
    reason TEXT NOT NULL,
    buyer_name TEXT,
    sale_value REAL CHECK (sale_value IS NULL OR sale_value >= 0),
    handover_date TEXT,
    notes TEXT,
    previous_status TEXT,
    previous_workshop_status TEXT,
    archived_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE RESTRICT
);

-- ==========================================
-- 3. جدول الحقول للسائقين والموظفين
-- ==========================================
CREATE TABLE IF NOT EXISTS driver_fields (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    label TEXT NOT NULL,
    required INTEGER DEFAULT 0
);

-- ==========================================
-- 4. جدول السائقين والموظفين الرئيسي
-- ==========================================
CREATE TABLE IF NOT EXISTS drivers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    national_id TEXT,
    phone TEXT,
    nationality TEXT,
    job_title TEXT,
    department TEXT,
    license_number TEXT,
    license_type TEXT,
    restrictions_count INTEGER DEFAULT 0,
    license_issue_date TEXT,
    license_expiry_date TEXT
);

-- ==========================================
-- 5. جدول المخالفات والسداد
-- ==========================================
CREATE TABLE IF NOT EXISTS violations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    violation_number TEXT,
    vehicle_plate TEXT,
    driver_name TEXT,
    violation_type TEXT,
    issuer TEXT,
    location TEXT,
    violation_datetime TEXT,
    fine_amount REAL,
    description TEXT,
    violation_attachment TEXT,
    status TEXT DEFAULT 'active',
    status_type TEXT DEFAULT 'نشطة',
    payment_date TEXT,
    payment_receipt TEXT,
    payment_amount REAL,
    payment_notes TEXT,
    payment_attachment TEXT
);

-- ==========================================
-- 6. جدول الحوادث
-- ==========================================
CREATE TABLE IF NOT EXISTS accidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    accident_number TEXT,
    vehicle_plate TEXT,
    driver_name TEXT,
    accident_type TEXT,
    issuer TEXT,
    location TEXT,
    accident_datetime TEXT,
    repair_cost REAL,
    description TEXT,
    accident_attachment TEXT,
    accident_attachment_2 TEXT,
    status TEXT DEFAULT 'active',
    status_type TEXT DEFAULT 'جاري المتابعة',
    closure_reason TEXT,
    closure_notes TEXT,
    closed_at TEXT,
    payment_attachment TEXT
);

-- ==========================================
-- 7. جدول وثائق التأمين
-- ==========================================
CREATE TABLE IF NOT EXISTS insurance_policies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_number TEXT NOT NULL,
    vehicle_plate TEXT NOT NULL,
    insurance_company TEXT NOT NULL,
    insurance_type TEXT DEFAULT 'شامل',
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    policy_cost REAL DEFAULT 0.0,
    description TEXT,
    policy_attachment TEXT,
    status TEXT DEFAULT 'active',
    status_type TEXT DEFAULT 'ساري',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (vehicle_plate) REFERENCES vehicles(plate_number)
);

-- ==========================================
-- 8. جدول أصناف المستودع
-- ==========================================
CREATE TABLE IF NOT EXISTS store_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    unit TEXT DEFAULT 'قطعة',
    quantity INTEGER DEFAULT 0,
    min_limit INTEGER DEFAULT 5,
    location TEXT,
    unit_price REAL DEFAULT 0.0,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ==========================================
-- 9. جدول الحركات المخزنية
-- ==========================================
CREATE TABLE IF NOT EXISTS store_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_code TEXT NOT NULL,
    transaction_type TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    reference_number TEXT,
    recipient_or_supplier TEXT,
    transaction_date TEXT NOT NULL,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (item_code) REFERENCES store_items(item_code)
);

-- ==========================================
-- 10. جدول أصول وعدّ الورشة
-- ==========================================
CREATE TABLE IF NOT EXISTS workshop_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    status TEXT DEFAULT 'متاح',
    location TEXT,
    purchase_date TEXT,
    condition_status TEXT DEFAULT 'جيد',
    notes TEXT
);

-- ==========================================
-- 11. جدول أجهزة وإعدادات النظام
-- ==========================================
CREATE TABLE IF NOT EXISTS system_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    value TEXT,
    setting_type TEXT DEFAULT 'string',
    group_name TEXT DEFAULT 'general',
    description TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- ==========================================
-- 12. جداول موديول مركز التقارير والوثائق (جديد)
-- ==========================================

-- أ) جدول سجل الأرشيف للتقارير والوثائق المصدورة
CREATE TABLE IF NOT EXISTS generated_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_uuid TEXT UNIQUE NOT NULL,             -- معرف فريد للعمل أوفلاين والمزامنة
    doc_number TEXT UNIQUE NOT NULL,           -- رقم المستند الموحد (مثال: REP-2026-X8F92)
    module_name TEXT NOT NULL,                -- الموديول (vehicles, drivers, workshop, handover...)
    report_type TEXT NOT NULL,                -- النوع (standard, visual, official_form)
    title TEXT NOT NULL,                      -- عنوان التقرير أو الاستمارة
    template_key TEXT NOT NULL,               -- معرف القالب البرمجي
    parameters_json TEXT,                     -- الفلاتر والمدخلات بصيغة JSON
    local_pdf_path TEXT,                      -- مسار حفظ الـ PDF محلياً
    local_report_path TEXT,                   -- مسار نسخة التقرير القابلة للطباعة
    local_qr_path TEXT,                       -- مسار صورة הـ QR محلياً
    drive_file_id TEXT,                       -- معرف الملف على جوجل درايف (عند المزامنة)
    drive_web_url TEXT,                       -- رابط المعاينة من درايف (عند المزامنة)
    sync_status TEXT DEFAULT 'pending',       -- حالة المزامنة: pending (معلق) / synced (تمت)
    created_by INTEGER,                       -- ID المستخدم المنشئ
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ب) جدول قوالب التقارير المعتمدة في النظام
CREATE TABLE IF NOT EXISTS report_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    template_key TEXT UNIQUE NOT NULL,        -- معرف القالب البرمجي
    module_name TEXT NOT NULL,                -- الموديول التابع له
    title TEXT NOT NULL,                      -- اسم النموذج المائل للعرض
    category TEXT NOT NULL,                   -- التصنيف: standard | visual | official_form
    description TEXT,                         -- وصف مختصّر للنموذج
    template_path TEXT NOT NULL,              -- مسار الملف البرمجي للقالب
    is_active INTEGER DEFAULT 1
);