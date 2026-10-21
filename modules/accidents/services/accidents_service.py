import os
from datetime import datetime

from sqlalchemy import or_, select

from core import storage
from core.database import get_session
from modules.accidents.models.accidents_orm import Accident
from modules.handover.services.handover_service import get_driver_at_datetime

UPLOAD_FOLDER = 'accidents'


def _to_float(value):
    if value is None or str(value).strip() == '':
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class AccidentsService:

    @staticmethod
    def get_all_accidents(tab='active'):
        if tab == 'closed':
            condition = Accident.status == 'closed'
        else:
            condition = or_(Accident.status == 'active', Accident.status.is_(None))
        with get_session() as session:
            rows = session.scalars(
                select(Accident).where(condition).order_by(Accident.id.desc())
            ).all()
            return [row.to_dict() for row in rows]

    @staticmethod
    def add_accident(form_data, file_att, file_att_2=None):
        filename = storage.upload_file(file_att, UPLOAD_FOLDER)
        try:
            filename_2 = storage.upload_file(file_att_2, UPLOAD_FOLDER)
        except Exception:
            storage.delete_files(filename)
            raise
        driver_name = get_driver_at_datetime(
            form_data.get('vehicle_plate'), form_data.get('accident_datetime')
        )

        try:
            with get_session() as session:
                session.add(Accident(
                    accident_number=form_data.get('accident_number'),
                    vehicle_plate=form_data.get('vehicle_plate'),
                    driver_name=driver_name,
                    accident_type=form_data.get('accident_type'),
                    issuer=form_data.get('issuer'),
                    location=form_data.get('location'),
                    accident_datetime=form_data.get('accident_datetime'),
                    repair_cost=_to_float(form_data.get('repair_cost')),
                    description=form_data.get('description'),
                    accident_attachment=filename,
                    accident_attachment_2=filename_2,
                    status='active',
                    status_type='جاري المتابعة',
                ))
        except Exception:
            storage.delete_files(filename, filename_2)
            raise

    @staticmethod
    def close_accident(accident_id, form_data, payment_att):
        filename = storage.upload_file(payment_att, UPLOAD_FOLDER)

        try:
            with get_session() as session:
                accident = session.get(Accident, int(accident_id))
                if accident is None:
                    raise ValueError("الحادث غير موجود.")
                accident.status = 'closed'
                accident.status_type = form_data.get('closure_reason', 'تمت التسوية')
                accident.closure_reason = form_data.get('closure_reason')
                accident.closure_notes = form_data.get('closure_notes')
                accident.closed_at = datetime.now().strftime('%Y-%m-%d %H:%M')
                accident.payment_attachment = filename
        except Exception:
            storage.delete_files(filename)
            raise

    @staticmethod
    def delete_accident(accident_id):
        with get_session() as session:
            accident = session.get(Accident, int(accident_id))
            if accident is None:
                return
            attachments = [
                accident.accident_attachment,
                accident.accident_attachment_2,
                accident.payment_attachment,
            ]
            session.delete(accident)

        storage.delete_files(*attachments)
