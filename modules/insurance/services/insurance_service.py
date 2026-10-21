import os
from modules.insurance.models.insurance_model import InsuranceModel
from core import storage

UPLOAD_FOLDER = 'insurance'


class InsuranceService:

    @staticmethod
    def get_upload_folder():
        """Legacy local folder, kept only so old attachments can still be served."""
        from flask import current_app
        return os.path.join(current_app.static_folder, 'uploads', 'insurance')

    @staticmethod
    def init_module():
        InsuranceModel.create_table()

    @staticmethod
    def get_all_policies(tab='active'):
        return InsuranceModel.get_all(tab=tab)

    @staticmethod
    def add_policy(form_data, file_attachment):
        url = storage.upload_file(file_attachment, UPLOAD_FOLDER)
        try:
            InsuranceModel.add_policy(form_data, url)
        except Exception:
            storage.delete_files(url)
            raise

    @staticmethod
    def expire_policy(policy_id):
        InsuranceModel.expire_policy(policy_id)

    @staticmethod
    def delete_policy(policy_id):
        InsuranceModel.delete_policy(policy_id)