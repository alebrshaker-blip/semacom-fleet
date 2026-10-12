import os
import sqlite3
import uuid
import qrcode
from datetime import datetime
from flask import request
from core.database import DB_PATH

# تحديد المسار الرئيسي للمشروع (SEMACOM_Fleet_System)
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../'))

# المسار المباشر لمجلد الاستاتيك المعتمد: SEMACOM_Fleet_System/app/static/uploads/qrcodes
QR_DIR = os.path.join(BASE_DIR, 'app', 'static', 'uploads', 'qrcodes')
REPORTS_DIR = os.path.join(BASE_DIR, 'app', 'static', 'uploads', 'reports')

# إنشاء مجلد qrcodes تلقائياً إذا لم يكن موجوداً
os.makedirs(QR_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)


def init_report_counter_db():
    """إنشاء جدول التسلسل وجدول المستندات المعتمدة في قاعدة البيانات"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # جدول التسلسل العام للرقم المرجعي
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS document_sequence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            last_number INTEGER NOT NULL DEFAULT 0
        )
    ''')
    
    # ضمان وجود سجل ابتدائي
    cursor.execute('SELECT COUNT(*) FROM document_sequence')
    if cursor.fetchone()[0] == 0:
        cursor.execute('INSERT INTO document_sequence (last_number) VALUES (0)')
        
    # جدول المستندات والوثائق المعتمدة
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS approved_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_number TEXT UNIQUE NOT NULL,
            doc_type TEXT NOT NULL,
            item_id TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            file_path TEXT,
            approval_token TEXT UNIQUE
        )
    ''')

    columns = {
        row[1] for row in cursor.execute("PRAGMA table_info(approved_documents)")
    }
    if "approval_token" not in columns:
        cursor.execute("ALTER TABLE approved_documents ADD COLUMN approval_token TEXT")
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_approved_documents_approval_token "
        "ON approved_documents (approval_token) WHERE approval_token IS NOT NULL"
    )
    
    conn.commit()
    conn.close()


def generate_reference_number() -> str:
    """
    الدالة الأولى: توليد رقم مرجعي تسلسلي موحد بتركيب No.000000
    """
    init_report_counter_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('UPDATE document_sequence SET last_number = last_number + 1 WHERE id = 1')
    cursor.execute('SELECT last_number FROM document_sequence WHERE id = 1')
    row = cursor.fetchone()
    seq_num = row[0] if row else 1
    
    conn.commit()
    conn.close()
    
    # صياغة الرقم المرجعي المتسلسل الموحد: No.000001
    return f"No.{seq_num:06d}"


def generate_document_qr(doc_number: str, doc_type: str = "general", item_id: str = "1") -> str:
    """
    الدالة الثانية: توليد QR Code وحفظه في app/static/uploads/qrcodes/
    """
    try:
        host_url = request.host_url.rstrip('/')
    except RuntimeError:
        host_url = "http://localhost:5000"

    # رابط المستند عند مسح الـ QR بواسطة الجوال
    target_url = f"{host_url}/reports/public/view/{doc_number}"
    
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(target_url)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="#1b365d", back_color="white")
    
    # حفظ الملف في مسار static المعتمد
    clean_doc_num = doc_number.replace('.', '_').replace('-', '_')
    filename = f"qr_{clean_doc_num}.png"
    filepath = os.path.join(QR_DIR, filename)
    img.save(filepath)
    
    # إرجاع المسار النسبي المستعمل في قوالب Flask
    return f"/static/uploads/qrcodes/{filename}"


class ReportsService:
    def fetch_report_data_by_type(self, template_key: str, params: dict) -> dict:
        """تجهيز البيانات الافتراضية للتقرير (الحفاظ على الدالة القديمة)"""
        return {
            "title": "تقرير معتمد",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "params": params
        }

    def process_and_archive_report(self, template_key: str, params: dict) -> dict:
        """توليد الرقم المرجعي الموحد والـ QR وتأكيد عملية الحفظ والأرشفة"""
        doc_number = generate_reference_number()
        item_id = str(params.get('id') or params.get('accident_id') or '1')
        qr_url = generate_document_qr(doc_number, template_key, item_id)
        
        return {
            "status": "success",
            "doc_number": doc_number,
            "qr_code_url": qr_url,
            "message": "تم إنشـاء التقرير المعتمد بنجاح"
        }