import os
from datetime import datetime

from sqlalchemy import or_, select

from core import storage
from core.database import engine, get_session, sync_columns
from core.orm_utils import to_float
from modules.handover.services.handover_service import get_driver_at_datetime
from modules.violations.models.violation_orm import Violation

UPLOAD_FOLDER = 'violations'


def init_violations_db():
    """Create the violations table (and any missing columns) from the ORM model."""
    Violation.__table__.create(bind=engine, checkfirst=True)
    sync_columns()


def _remove_upload(url):
    storage.delete_file(url)


def _save_upload(file_obj, prefix):
    return storage.upload_file(file_obj, UPLOAD_FOLDER)


class ViolationsService:

    @staticmethod
    def get_all_violations(tab='active'):
        if tab == 'closed':
            condition = Violation.status == 'closed'
        else:
            condition = or_(Violation.status == 'active', Violation.status.is_(None))
        with get_session() as session:
            rows = session.scalars(
                select(Violation).where(condition).order_by(Violation.id.desc())
            ).all()
            return [row.to_dict() for row in rows]

    @staticmethod
    def add_violation(form_data, file_att):
        filename = _save_upload(file_att, 'viol')
        driver_name = get_driver_at_datetime(
            form_data.get('vehicle_plate'), form_data.get('violation_datetime')
        )
        with get_session() as session:
            session.add(Violation(
                violation_number=form_data.get('violation_number'),
                vehicle_plate=form_data.get('vehicle_plate'),
                driver_name=driver_name,
                violation_type=form_data.get('violation_type'),
                issuer=form_data.get('issuer'),
                location=form_data.get('location'),
                violation_datetime=form_data.get('violation_datetime'),
                fine_amount=to_float(form_data.get('fine_amount')),
                description=form_data.get('description'),
                violation_attachment=filename,
                status='active',
                status_type='نشطة',
            ))

    @staticmethod
    def close_violation(violation_id, form_data, payment_att):
        filename = _save_upload(payment_att, 'pay')
        with get_session() as session:
            violation = session.get(Violation, violation_id)
            if violation is None:
                _remove_upload(filename)
                return False
            violation.status = 'closed'
            violation.status_type = 'مسددة'
            violation.payment_date = form_data.get('payment_date')
            violation.payment_receipt = form_data.get('payment_receipt')
            violation.payment_amount = to_float(form_data.get('payment_amount'))
            violation.payment_notes = form_data.get('payment_notes')
            violation.payment_attachment = filename
        return True

    @staticmethod
    def delete_violation(violation_id):
        with get_session() as session:
            violation = session.get(Violation, violation_id)
            if violation is None:
                return False
            attachments = (violation.violation_attachment, violation.payment_attachment)
            session.delete(violation)
        for name in attachments:
            _remove_upload(name)
        return True
