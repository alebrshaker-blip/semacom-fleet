import os
import time
from datetime import date, timedelta
from pathlib import Path

from flask import current_app, has_app_context

from core import storage
from modules.inspection.models.inspection_model import InspectionModel
from utils.expiry_status import get_expiry_status

UPLOAD_FOLDER = 'inspection'


class InspectionService:
    @staticmethod
    def get_upload_folder():
        """Legacy local folder, kept only so old attachments can still be served."""
        if has_app_context():
            static_folder = current_app.static_folder
        else:
            project_root = Path(__file__).resolve().parents[3]
            static_folder = project_root / 'app' / 'static'
        return os.path.join(str(static_folder), 'uploads', 'inspection')

    @classmethod
    def get_all_inspections(cls, status_type='active'):
        """Recompute each record's expiry state, persist it, and return the requested group."""
        inspections = []
        for record in InspectionModel.list_all():
            inspection = record.to_dict()
            passed = inspection.get('result_status') in ('ناجح', 'Pass', 'pass')
            state = (
                get_expiry_status(
                    inspection.get('expiry_date'), 'ساري', 'قارب على الانتهاء', 'منتهي'
                )
                if passed else 'منتهي'
            )
            status = 'expired' if state == 'منتهي' else 'active'
            if record.status != status or record.status_type != state:
                InspectionModel.set_state(record.id, status, state)
            inspection['status_type'] = state
            inspection['status'] = status
            if (status_type == 'active' and status == 'active') or (
                status_type == 'expired' and status == 'expired'
            ):
                inspections.append(inspection)
        return inspections

    @classmethod
    def create_inspection(cls, form_data, file_attachment):
        attachment_url = storage.upload_file(file_attachment, UPLOAD_FOLDER)

        try:
            InspectionModel.add_inspection(form_data, attachment_url)
        except Exception:
            storage.delete_files(attachment_url)
            raise

    @classmethod
    def mark_as_expired(cls, inspection_id):
        InspectionModel.set_expiry_date(inspection_id, (date.today() - timedelta(days=1)).isoformat())

    @classmethod
    def remove_inspection(cls, inspection_id):
        attachment = InspectionModel.delete_inspection(inspection_id)
        storage.delete_files(attachment)
