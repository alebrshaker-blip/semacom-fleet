import os
from datetime import datetime
from core.database import Database
from modules.handover.services.handover_service import get_driver_at_datetime

def get_upload_folder():
    """الحصول على مسار مجلد الرفع المرتبط حصرياً بمجلد app/static الأصلي للمشروع"""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # الصعود 3 مستويات للوصول لمجلد المشروع الرئيسي SEMACOM_Fleet_System
    base_dir = os.path.abspath(os.path.join(current_dir, '..', '..', '..'))
    
    # توجيه الحفظ مباشرة إلى: SEMACOM_Fleet_System/app/static/uploads/violations
    upload_folder = os.path.join(base_dir, 'app', 'static', 'uploads', 'violations')
    os.makedirs(upload_folder, exist_ok=True)
    return upload_folder

def init_violations_db():
    """إنشاء جدول المخالفات والتأكد من وجود الأعمدة منذ بدء التطبيق"""
    db = Database()
    query = """
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
    )
    """
    db.execute(query)
    
    # التأكد من وجود أعمدة المرفقات والحالة بطريقة آمنة
    columns_to_check = [
        ("violation_attachment", "TEXT"),
        ("payment_attachment", "TEXT"),
        ("status_type", "TEXT DEFAULT 'نشطة'"),
        ("status", "TEXT DEFAULT 'active'")
    ]
    
    for col_name, col_type in columns_to_check:
        try:
            db.execute(f"ALTER TABLE violations ADD COLUMN {col_name} {col_type};")
        except Exception:
            pass  # العمود موجود مسبقاً ولا داعي لإضافته
            
    db.close()

class ViolationsService:

    @staticmethod
    def get_all_violations(tab='active'):
        db = Database()
        if tab == 'closed':
            query = "SELECT * FROM violations WHERE status = 'closed' ORDER BY id DESC"
        else:
            query = "SELECT * FROM violations WHERE status = 'active' OR status IS NULL ORDER BY id DESC"
        
        rows = db.fetch_all(query)
        db.close()
        
        violations = []
        for row in rows:
            # معالجة آمنة ومتوافقة مع جميع أنواع إرجاع الصفوف (Dictionaries أو Tuples) لمنع أخطاء KeyError
            try:
                if isinstance(row, dict) or hasattr(row, 'keys'):
                    v_id = row.get('id')
                    v_number = row.get('violation_number')
                    v_plate = row.get('vehicle_plate')
                    v_driver = row.get('driver_name')
                    v_type = row.get('violation_type')
                    v_issuer = row.get('issuer')
                    v_location = row.get('location')
                    v_datetime = row.get('violation_datetime')
                    v_fine = row.get('fine_amount')
                    v_desc = row.get('description')
                    v_att = row.get('violation_attachment')
                    v_status = row.get('status')
                    v_status_type = row.get('status_type')
                    p_date = row.get('payment_date')
                    p_receipt = row.get('payment_receipt')
                    p_amount = row.get('payment_amount')
                    p_notes = row.get('payment_notes')
                    p_att = row.get('payment_attachment')
                else:
                    v_id = row[0]
                    v_number = row[1]
                    v_plate = row[2]
                    v_driver = row[3]
                    v_type = row[4]
                    v_issuer = row[5]
                    v_location = row[6]
                    v_datetime = row[7]
                    v_fine = row[8]
                    v_desc = row[9]
                    v_att = row[10]
                    v_status = row[11]
                    v_status_type = row[12]
                    p_date = row[13]
                    p_receipt = row[14]
                    p_amount = row[15]
                    p_notes = row[16]
                    p_att = row[17]
            except Exception:
                continue

            violations.append({
                'id': v_id,
                'violation_number': v_number,
                'vehicle_plate': v_plate,
                'driver_name': v_driver,
                'violation_type': v_type,
                'issuer': v_issuer,
                'location': v_location,
                'violation_datetime': v_datetime,
                'fine_amount': v_fine,
                'description': v_desc,
                'violation_attachment': v_att,
                'status': v_status,
                'status_type': v_status_type,
                'payment_date': p_date,
                'payment_receipt': p_receipt,
                'payment_amount': p_amount,
                'payment_notes': p_notes,
                'payment_attachment': p_att
            })
        return violations

    @staticmethod
    def add_violation(form_data, file_att):
        filename = None
        if file_att and file_att.filename:
            upload_folder = get_upload_folder()
            filename = f"viol_{int(datetime.now().timestamp())}_{file_att.filename}"
            file_att.save(os.path.join(upload_folder, filename))

        db = Database()
        query = """
        INSERT INTO violations (
            violation_number, vehicle_plate, driver_name, violation_type, 
            issuer, location, violation_datetime, fine_amount, description, 
            violation_attachment, status, status_type
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 'نشطة')
        """
        driver_name = get_driver_at_datetime(
            form_data.get('vehicle_plate'), form_data.get('violation_datetime')
        )
        params = (
            form_data.get('violation_number'),
            form_data.get('vehicle_plate'),
            driver_name,
            form_data.get('violation_type'),
            form_data.get('issuer'),
            form_data.get('location'),
            form_data.get('violation_datetime'),
            form_data.get('fine_amount'),
            form_data.get('description'),
            filename
        )
        db.execute(query, params)
        db.close()

    @staticmethod
    def close_violation(violation_id, form_data, payment_att):
        filename = None
        if payment_att and payment_att.filename:
            upload_folder = get_upload_folder()
            filename = f"pay_{int(datetime.now().timestamp())}_{payment_att.filename}"
            payment_att.save(os.path.join(upload_folder, filename))

        db = Database()
        query = """
        UPDATE violations SET 
            status = 'closed',
            status_type = 'مسددة',
            payment_date = ?,
            payment_receipt = ?,
            payment_amount = ?,
            payment_notes = ?,
            payment_attachment = ?
        WHERE id = ?
        """
        params = (
            form_data.get('payment_date'),
            form_data.get('payment_receipt'),
            form_data.get('payment_amount'),
            form_data.get('payment_notes'),
            filename,
            violation_id
        )
        db.execute(query, params)
        db.close()

    @staticmethod
    def delete_violation(violation_id):
        db = Database()
        rows = db.fetch_all("SELECT violation_attachment, payment_attachment FROM violations WHERE id = ?", (violation_id,))
        
        if rows:
            row = rows[0]
            # قراءة المرفقات سواء كانت بصيغة قاموس أو فهارس عادية
            try:
                if isinstance(row, dict) or hasattr(row, 'keys'):
                    att = row.get('violation_attachment')
                    pay = row.get('payment_attachment')
                else:
                    att = row[0]
                    pay = row[1]
            except Exception:
                att, pay = None, None

            upload_folder = get_upload_folder()
            if att:
                try:
                    os.remove(os.path.join(upload_folder, att))
                except Exception:
                    pass
            if pay:
                try:
                    os.remove(os.path.join(upload_folder, pay))
                except Exception:
                    pass
                
        db.execute("DELETE FROM violations WHERE id = ?", (violation_id,))
        db.close()