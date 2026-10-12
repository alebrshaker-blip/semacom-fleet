import os
import sqlite3
import time
from pathlib import Path
from flask import current_app, has_app_context
from werkzeug.utils import secure_filename
from modules.inspection.models.inspection_model import InspectionModel
from utils.expiry_status import get_expiry_status

class InspectionService:
    @staticmethod
    def get_upload_folder():
        if has_app_context():
            static_folder = current_app.static_folder
        else:
            project_root = Path(__file__).resolve().parents[3]
            static_folder = project_root / 'app' / 'static'
        return os.path.join(str(static_folder), 'uploads', 'inspection')

    @staticmethod
    def ensure_upload_folder():
        os.makedirs(InspectionService.get_upload_folder(), exist_ok=True)

    @classmethod
    def get_all_inspections(cls, status_type='active'):
        conn = sqlite3.connect(InspectionModel.DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        query = "SELECT * FROM inspections ORDER BY id DESC"
        
        cursor.execute(query)
        rows = cursor.fetchall()
        inspections = []
        for row in rows:
            inspection = dict(row)
            passed = inspection.get('result_status') in ('ناجح', 'Pass', 'pass')
            state = (
                get_expiry_status(
                    inspection.get('expiry_date'), 'ساري', 'قارب على الانتهاء', 'منتهي'
                )
                if passed else 'منتهي'
            )
            inspection['status_type'] = state
            inspection['status'] = 'expired' if state == 'منتهي' else 'active'
            cursor.execute(
                "UPDATE inspections SET status = ?, status_type = ? WHERE id = ?",
                (inspection['status'], state, inspection['id']),
            )
            if status_type == 'active' and inspection['status'] == 'active':
                inspections.append(inspection)
            elif status_type == 'expired' and inspection['status'] == 'expired':
                inspections.append(inspection)
        conn.commit()
        conn.close()
        return inspections

    @classmethod
    def create_inspection(cls, form_data, file_attachment):
        vehicle_plate = form_data.get('vehicle_plate')
        inspection_date = form_data.get('inspection_date')
        expiry_date = form_data.get('expiry_date')
        result_status = form_data.get('result_status')
        inspection_center = form_data.get('inspection_center')
        
        attachment_filename = None
        if file_attachment and file_attachment.filename != '':
            cls.ensure_upload_folder()
            filename = secure_filename(file_attachment.filename)
            unique_filename = f"{int(time.time())}_{filename}"
            file_path = os.path.join(cls.get_upload_folder(), unique_filename)
            file_attachment.save(file_path)
            attachment_filename = unique_filename

        conn = sqlite3.connect(InspectionModel.DB_PATH)
        cursor = conn.cursor()
        
        # التأكد من إنشاء الجدول وتوافق أسماء الأعمدة بدقة مطلقة
        InspectionModel.create_table()
        
        cursor.execute("""
            INSERT INTO inspections (
                vehicle_plate, inspection_date, expiry_date, result_status,
                inspection_center, inspection_cost, attachment, notes, status, status_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', 'ساري')
        """, (
            vehicle_plate, inspection_date, expiry_date, result_status, inspection_center,
            float(form_data.get('inspection_cost') or 0.0), attachment_filename,
            form_data.get('notes')
        ))
        
        conn.commit()
        conn.close()

    @classmethod
    def mark_as_expired(cls, inspection_id):
        conn = sqlite3.connect(InspectionModel.DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE inspections SET expiry_date = DATE('now', '-1 day') WHERE id = ?", (inspection_id,))
        conn.commit()
        conn.close()

    @classmethod
    def remove_inspection(cls, inspection_id):
        conn = sqlite3.connect(InspectionModel.DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # جلب اسم الملف المرفق لحذفه من الخادم إن وجد
        cursor.execute("SELECT attachment FROM inspections WHERE id = ?", (inspection_id,))
        row = cursor.fetchone()
        if row and row['attachment']:
            file_path = os.path.join(cls.get_upload_folder(), row['attachment'])
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass

        cursor.execute("DELETE FROM inspections WHERE id = ?", (inspection_id,))
        conn.commit()
        conn.close()