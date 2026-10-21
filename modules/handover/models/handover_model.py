from sqlalchemy import delete, insert, or_, select

from core.database import get_session
from modules.handover.models.handover_orm import HandoverRecord


def init_handover_db():
    """Create the handover tables and certify legacy documents."""
    from modules.handover.services.handover_service import init_handovers
    init_handovers()


def get_all_records(search_query=None):
    stmt = select(HandoverRecord)
    if search_query:
        pattern = f"%{search_query}%"
        stmt = stmt.where(or_(
            HandoverRecord.vehicle_info.ilike(pattern),
            HandoverRecord.driver_info.ilike(pattern),
            HandoverRecord.electrical_technician.ilike(pattern),
            HandoverRecord.mechanical_technician.ilike(pattern),
        ))
    with get_session() as session:
        return [row.to_dict() for row in session.scalars(stmt.order_by(HandoverRecord.id.desc()))]


def insert_handover_record(data):
    allowed = {key: value for key, value in data.items() if key in HandoverRecord.__table__.columns and key != 'id'}
    with get_session() as session:
        session.execute(insert(HandoverRecord).values(**allowed))


def delete_handover_record(record_id):
    with get_session() as session:
        session.execute(delete(HandoverRecord).where(HandoverRecord.id == record_id))
