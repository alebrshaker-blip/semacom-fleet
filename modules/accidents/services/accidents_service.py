import os
from datetime import datetime
from core.database import Database
from werkzeug.utils import secure_filename
from modules.handover.services.handover_service import get_driver_at_datetime

def get_upload_folder():
    """الحصول على مسار مجلد الرفع الخاص بالحوادث المرتبط بـ app/static للمشروع"""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # الصعود للوصول لمجلد المشروع الرئيسي
    base_dir = os.path.abspath(os.path.join(current_dir, '..', '..', '..'))
    
    upload_folder = os.path.join(base_dir, 'app', 'static', 'uploads', 'accidents')
    os.makedirs(upload_folder, exist_ok=True)
    return upload_folder

class AccidentsService:

    @staticmethod
    def get_all_accidents(tab='active'):
        db = Database()
        if tab == 'closed':
            query = "SELECT * FROM accidents WHERE status = 'closed' ORDER BY id DESC"
        else:
            query = "SELECT * FROM accidents WHERE status = 'active' OR status IS NULL ORDER BY id DESC"
        
        rows = db.fetch_all(query)
        db.close()
        
        accidents = []
        for row in rows:
            try:
                if isinstance(row, dict) or hasattr(row, 'keys'):
                    acc_id = row.get('id')
                    acc_num = row.get('accident_number')
                    v_plate = row.get('vehicle_plate')
                    d_name = row.get('driver_name')
                    acc_type = row.get('accident_type')
                    issuer = row.get('issuer')
                    location = row.get('location')
                    acc_dt = row.get('accident_datetime')
                    repair_cost = row.get('repair_cost')
                    desc = row.get('description')
                    acc_att = row.get('accident_attachment')
                    acc_att_2 = row.get('accident_attachment_2')
                    status = row.get('status')
                    status_type = row.get('status_type')
                    closure_reason = row.get('closure_reason')
                    closure_notes = row.get('closure_notes')
                    closed_at = row.get('closed_at')
                    pay_att = row.get('payment_attachment')
                else:
                    acc_id = row[0]
                    acc_num = row[1]
                    v_plate = row[2]
                    d_name = row[3]
                    acc_type = row[4]
                    issuer = row[5]
                    location = row[6]
                    acc_dt = row.get('accident_datetime') if isinstance(row, dict) else row[7]
                    repair_cost = row[8]
                    desc = row[9]
                    acc_att = row[10]
                    acc_att_2 = row.get('accident_attachment_2') if hasattr(row, 'get') else None
                    status = row[11]
                    status_type = row[12]
                    closure_reason = row[13]
                    closure_notes = row[14]
                    closed_at = row[15]
                    pay_att = row[16]
            except Exception:
                continue

            accidents.append({
                'id': acc_id,
                'accident_number': acc_num,
                'vehicle_plate': v_plate,
                'driver_name': d_name,
                'accident_type': acc_type,
                'issuer': issuer,
                'location': location,
                'accident_datetime': acc_dt,
                'repair_cost': repair_cost,
                'description': desc,
                'accident_attachment': acc_att,
                'accident_attachment_2': acc_att_2,
                'status': status,
                'status_type': status_type,
                'closure_reason': closure_reason,
                'closure_notes': closure_notes,
                'closed_at': closed_at,
                'payment_attachment': pay_att
            })
        return accidents

    @staticmethod
    def add_accident(form_data, file_att, file_att_2=None):
        upload_folder = get_upload_folder()

        def save_attachment(upload, suffix):
            if not upload or not upload.filename:
                return None
            safe_name = secure_filename(upload.filename)
            filename = f"acc_{int(datetime.now().timestamp())}_{suffix}_{safe_name}"
            upload.save(os.path.join(upload_folder, filename))
            return filename

        filename = save_attachment(file_att, "1")
        filename_2 = save_attachment(file_att_2, "2")
        driver_name = get_driver_at_datetime(
            form_data.get('vehicle_plate'), form_data.get('accident_datetime')
        )

        db = Database()
        query = """
        INSERT INTO accidents (
            accident_number, vehicle_plate, driver_name, accident_type, 
            issuer, location, accident_datetime, repair_cost, description, 
            accident_attachment, accident_attachment_2, status, status_type
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 'جاري المتابعة')
        """
        params = (
            form_data.get('accident_number'),
            form_data.get('vehicle_plate'),
            driver_name,
            form_data.get('accident_type'),
            form_data.get('issuer'),
            form_data.get('location'),
            form_data.get('accident_datetime'),
            form_data.get('repair_cost'),
            form_data.get('description'),
            filename,
            filename_2
        )
        db.execute(query, params)
        db.close()

    @staticmethod
    def close_accident(accident_id, form_data, payment_att):
        filename = None
        if payment_att and payment_att.filename:
            upload_folder = get_upload_folder()
            filename = f"settle_{int(datetime.now().timestamp())}_{payment_att.filename}"
            payment_att.save(os.path.join(upload_folder, filename))

        closed_date = datetime.now().strftime('%Y-%m-%d %H:%M')

        db = Database()
        query = """
        UPDATE accidents SET 
            status = 'closed',
            status_type = ?,
            closure_reason = ?,
            closure_notes = ?,
            closed_at = ?,
            payment_attachment = ?
        WHERE id = ?
        """
        params = (
            form_data.get('closure_reason', 'تمت التسوية'),
            form_data.get('closure_reason'),
            form_data.get('closure_notes'),
            closed_date,
            filename,
            accident_id
        )
        db.execute(query, params)
        db.close()

    @staticmethod
    def delete_accident(accident_id):
        db = Database()
        rows = db.fetch_all(
            "SELECT accident_attachment, accident_attachment_2, payment_attachment FROM accidents WHERE id = ?",
            (accident_id,)
        )
        
        if rows:
            row = rows[0]
            try:
                if isinstance(row, dict) or hasattr(row, 'keys'):
                    att = row.get('accident_attachment')
                    att_2 = row.get('accident_attachment_2')
                    pay = row.get('payment_attachment')
                else:
                    att = row[0]
                    att_2 = row[1]
                    pay = row[2]
            except Exception:
                att, att_2, pay = None, None, None

            upload_folder = get_upload_folder()
            if att:
                try:
                    os.remove(os.path.join(upload_folder, att))
                except Exception:
                    pass
            if att_2:
                try:
                    os.remove(os.path.join(upload_folder, att_2))
                except Exception:
                    pass
            if pay:
                try:
                    os.remove(os.path.join(upload_folder, pay))
                except Exception:
                    pass
                
        db.execute("DELETE FROM accidents WHERE id = ?", (accident_id,))
        db.close()