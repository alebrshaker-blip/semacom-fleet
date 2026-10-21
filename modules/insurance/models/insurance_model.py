from sqlalchemy import select

from core import storage
from core.database import engine, get_session, sync_columns
from core.orm_utils import to_float
from modules.insurance.models.insurance_orm import InsurancePolicy
from utils.expiry_status import get_expiry_status


class InsuranceModel:

    @staticmethod
    def create_table():
        InsurancePolicy.__table__.create(bind=engine, checkfirst=True)
        sync_columns()

    @staticmethod
    def get_all(tab='active'):
        wanted = 'active' if tab == 'active' else 'expired'
        with get_session() as session:
            for policy in session.scalars(select(InsurancePolicy)):
                state = get_expiry_status(
                    policy.end_date, "ساري", "قارب على الانتهاء", "منتهية"
                )
                policy.status = "expired" if state == "منتهية" else (policy.status or "active")
                policy.status_type = state
            session.flush()
            rows = session.scalars(
                select(InsurancePolicy)
                .where(InsurancePolicy.status == wanted)
                .order_by(InsurancePolicy.id.desc())
            ).all()
            return [row.to_dict() for row in rows]

    @staticmethod
    def add_policy(data, attachment_filename):
        with get_session() as session:
            session.add(InsurancePolicy(
                policy_number=data.get('policy_number'),
                vehicle_plate=data.get('vehicle_plate'),
                insurance_company=data.get('insurance_company'),
                insurance_type=data.get('insurance_type'),
                start_date=data.get('start_date'),
                end_date=data.get('end_date'),
                policy_cost=to_float(data.get('policy_cost'), 0.0),
                description=data.get('description'),
                policy_attachment=attachment_filename,
                status='active',
                status_type='ساري',
            ))

    @staticmethod
    def expire_policy(policy_id):
        with get_session() as session:
            policy = session.get(InsurancePolicy, policy_id)
            if policy:
                policy.status = 'expired'
                policy.status_type = 'منتهي'

    @staticmethod
    def delete_policy(policy_id):
        with get_session() as session:
            policy = session.get(InsurancePolicy, policy_id)
            if policy:
                storage.delete_file(policy.policy_attachment)
                session.delete(policy)
