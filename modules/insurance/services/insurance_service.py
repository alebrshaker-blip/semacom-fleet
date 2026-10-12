import os
from flask import current_app
from werkzeug.utils import secure_filename
from modules.insurance.models.insurance_model import InsuranceModel

class InsuranceService:

    @staticmethod
    def get_upload_folder():
        """دالة مركزية لضمان استخدام المسار الصحيح حصرياً داخل app/static/uploads/insurance"""
        if current_app:
            base_dir = current_app.static_folder  # يشير إلى app/static
        else:
            # مسار احتياطي في حال تم استدعاء الخدمة خارج سياق الـ request
            base_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'app', 'static')
        
        return os.path.join(base_dir, 'uploads', 'insurance')

    @staticmethod
    def init_module():
        InsuranceModel.create_table()
        folder = InsuranceService.get_upload_folder()
        if not os.path.exists(folder):
            os.makedirs(folder, exist_ok=True)

    @staticmethod
    def get_all_policies(tab='active'):
        return InsuranceModel.get_all(tab=tab)

    @staticmethod
    def add_policy(form_data, file_attachment):
        filename = None
        upload_folder = InsuranceService.get_upload_folder()
        
        if file_attachment and file_attachment.filename:
            filename = secure_filename(file_attachment.filename)
            os.makedirs(upload_folder, exist_ok=True)
            file_path = os.path.join(upload_folder, filename)
            file_attachment.save(file_path)
            
        InsuranceModel.add_policy(form_data, filename)

    @staticmethod
    def expire_policy(policy_id):
        InsuranceModel.expire_policy(policy_id)

    @staticmethod
    def delete_policy(policy_id):
        InsuranceModel.delete_policy(policy_id)