from sqlalchemy import delete, func, select, text, update

from core import database as dbapi
from core.database import get_session
from modules.inspection.models.inspection_orm import Inspection

_LEGACY_COLUMNS = (
    'id', 'vehicle_plate', 'inspection_center', 'inspection_date', 'expiry_date',
    'result_status', 'inspection_cost', 'attachment', 'notes', 'status', 'status_type',
)


class InspectionModel:

    @staticmethod
    def create_table():
        """Create the inspections table and import rows from the legacy vehicle_inspections table."""
        dbapi.init_orm_schema()
        with get_session() as session:
            if not session.execute(text("SELECT to_regclass('vehicle_inspections')")).scalar():
                return
            if session.scalar(select(func.count()).select_from(Inspection)):
                return
            source = set(session.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = 'vehicle_inspections'"
            )).scalars())
            columns = [name for name in _LEGACY_COLUMNS if name in source]
            if 'vehicle_plate' not in columns:
                return
            column_sql = ', '.join(f'"{name}"' for name in columns)
            session.execute(text(
                f'INSERT INTO inspections ({column_sql}) SELECT {column_sql} FROM vehicle_inspections '
                'ON CONFLICT DO NOTHING'
            ))
            if 'id' in columns:
                session.execute(text(
                    "SELECT setval(pg_get_serial_sequence('inspections', 'id'), "
                    "COALESCE((SELECT MAX(id) FROM inspections), 1))"
                ))

    @staticmethod
    def get_all(status_type='active'):
        order = Inspection.expiry_date.asc() if status_type == 'active' else Inspection.expiry_date.desc()
        state = 'active' if status_type == 'active' else 'expired'
        with get_session() as session:
            rows = session.scalars(select(Inspection).where(Inspection.status == state).order_by(order))
            return [row.to_dict() for row in rows]

    @staticmethod
    def list_all():
        with get_session() as session:
            return list(session.scalars(select(Inspection).order_by(Inspection.id.desc())))

    @staticmethod
    def add_inspection(form_data, attachment_filename):
        with get_session() as session:
            session.add(Inspection(
                vehicle_plate=form_data.get('vehicle_plate') or form_data.get('plate_number'),
                inspection_center=form_data.get('inspection_center') or form_data.get('inspector_name', '-'),
                inspection_date=form_data.get('inspection_date'),
                expiry_date=form_data.get('expiry_date'),
                result_status=form_data.get('result_status') or form_data.get('result', 'ناجح'),
                inspection_cost=float(form_data.get('inspection_cost') or 0.0),
                attachment=attachment_filename,
                notes=form_data.get('notes'),
                status='active',
                status_type='ساري',
            ))

    @staticmethod
    def expire_inspection(inspection_id):
        with get_session() as session:
            session.execute(
                update(Inspection).where(Inspection.id == inspection_id)
                .values(status='expired', status_type='منتهي')
            )

    @staticmethod
    def set_state(inspection_id, status, status_type):
        with get_session() as session:
            session.execute(
                update(Inspection).where(Inspection.id == inspection_id)
                .values(status=status, status_type=status_type)
            )

    @staticmethod
    def set_expiry_date(inspection_id, expiry_date):
        with get_session() as session:
            session.execute(
                update(Inspection).where(Inspection.id == inspection_id).values(expiry_date=expiry_date)
            )

    @staticmethod
    def delete_inspection(inspection_id):
        """Delete a record and return its attachment filename (if any)."""
        with get_session() as session:
            attachment = session.scalar(select(Inspection.attachment).where(Inspection.id == inspection_id))
            session.execute(delete(Inspection).where(Inspection.id == inspection_id))
            return attachment
