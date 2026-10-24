"""Handover (custody) business logic on top of the SQLAlchemy ORM."""
from pathlib import Path

from sqlalchemy import Text, cast, delete, exists, or_, select, text

from core import database as dbapi
from core.database import SessionLocal, get_session
from modules.drivers.models.driver_orm import Driver
from modules.handover.models.handover_orm import Handover
from modules.reports.models.report_orm import ApprovedDocument
from modules.vehicles import repository as vehicles_repository
from modules.vehicles.models.vehicle_orm import Vehicle, VehicleArchive

MANAGEMENT_CUSTODY = "عهدة إدارة المعدات"
STATUS_ACTIVE = "نشط"
STATUS_ARCHIVED = "مؤرشف"
STATUS_PENDING = "بانتظار التوثيق"
OUT_OF_SERVICE = "خارج الخدمة"
UNDER_MAINTENANCE = "تحت الصيانة"
DELIVERED = "مسلمة"
AVAILABLE = "متاحة"


def get_db_connection():
    """Raw compat connection for cross-module reads (tables are created at startup)."""
    conn = dbapi.connect()
    conn.row_factory = dbapi.Row
    return conn


def init_handovers():
    """Create the schema and certify legacy handovers that already have an approved document."""
    dbapi.init_orm_schema()
    reports_root = (Path(__file__).resolve().parents[3] / 'app' / 'static' / 'uploads' / 'reports').resolve()
    with get_session() as session:
        legacy = session.execute(
            select(ApprovedDocument.created_at, ApprovedDocument.doc_number,
                   ApprovedDocument.file_path, Handover)
            .join(Handover, cast(Handover.id, Text) == ApprovedDocument.item_id)
            .where(ApprovedDocument.doc_type == 'handover_document', Handover.is_certified == 0)
        ).all()
        for created_at, doc_number, file_path, handover in legacy:
            report_data = None
            if file_path:
                try:
                    saved = Path(file_path).resolve()
                    saved.relative_to(reports_root)
                    report_data = saved.read_text(encoding='utf-8')
                except (OSError, UnicodeError, ValueError):
                    report_data = None
            handover.is_certified = 1
            handover.certified_at = handover.certified_at or created_at
            handover.certified_by = handover.certified_by or 'غير محدد'
            handover.document_number = handover.document_number or doc_number
            handover.report_data = handover.report_data or report_data
            handover.report_file_path = handover.report_file_path or file_path


def _list_by_status(status, search_query=None):
    stmt = select(Handover).where(Handover.status == status)
    if search_query:
        pattern = f"%{search_query}%"
        stmt = stmt.where(or_(
            Handover.vehicle_info.ilike(pattern),
            Handover.driver_info.ilike(pattern),
            Handover.electrical_technician.ilike(pattern),
        ))
    with get_session() as session:
        return [row.to_dict() for row in session.scalars(stmt.order_by(Handover.id.desc()))]


def get_active_handovers(search_query=None):
    return _list_by_status(STATUS_ACTIVE, search_query)


def get_archived_handovers(search_query=None):
    return _list_by_status(STATUS_ARCHIVED, search_query)


def get_pending_handovers(search_query=None):
    return _list_by_status(STATUS_PENDING, search_query)


def _latest_inspection_mileage(session):
    if not session.execute(text("SELECT to_regclass('comprehensive_inspections')")).scalar():
        return {}
    rows = session.execute(text(
        "SELECT vehicle_plate, current_mileage FROM comprehensive_inspections "
        "ORDER BY inspection_date DESC, id DESC"
    )).all()
    latest = {}
    for plate, mileage in rows:
        plate = str(plate or '').strip()
        if plate and plate not in latest:
            latest[plate] = mileage
    return latest


def get_form_entities():
    vehicles = vehicles_repository.list_active_summaries()
    with get_session() as session:
        mileage = _latest_inspection_mileage(session)
        active_handovers = [
            row.to_dict() for row in session.scalars(
                select(Handover).where(Handover.status == STATUS_ACTIVE).order_by(Handover.id.desc())
            )
        ]
        drivers = [row.to_dict() for row in session.scalars(select(Driver).order_by(Driver.id))]
        has_team = session.execute(text("SELECT to_regclass('team_members')")).scalar()
        technicians = (
            [dict(row) for row in session.execute(text("SELECT * FROM team_members")).mappings()]
            if has_team else []
        )

    for vehicle in vehicles:
        vehicle['latest_mileage'] = mileage.get(str(vehicle.get('plate_number') or '').strip())

    def vehicle_for_handover(handover):
        vehicle_id = handover.get('vehicle_id')
        if vehicle_id is not None:
            match = next((v for v in vehicles if str(v['id']) == str(vehicle_id)), None)
            if match:
                return match
        info = (handover.get('vehicle_info') or '').strip()
        return next(
            (
                vehicle for vehicle in vehicles
                if info in {
                    str(vehicle.get('plate_number') or '').strip(),
                    str(vehicle.get('vehicle_code') or '').strip(),
                    f"{vehicle.get('vehicle_code') or ''} - {vehicle.get('plate_number') or ''}".strip()
                }
            ),
            None
        )

    assigned_vehicles = []
    assigned_ids = set()
    for handover in active_handovers:
        vehicle = vehicle_for_handover(handover)
        if vehicle:
            assigned_ids.add(str(vehicle['id']))
            assigned_vehicles.append({
                'vehicle_id': vehicle['id'],
                'vehicle_info': f"{vehicle.get('vehicle_code') or ''} - {vehicle.get('plate_number') or ''}".strip(' -'),
                'driver_info': handover.get('driver_info') or '',
                'purpose': handover.get('purpose') or '',
                'department': handover.get('department') or '',
                'description': handover.get('description') or '',
                'latest_mileage': vehicle.get('latest_mileage')
            })

    available_vehicles = [
        vehicle for vehicle in vehicles
        if vehicle.get('status') not in (DELIVERED, UNDER_MAINTENANCE, OUT_OF_SERVICE)
        and vehicle.get('workshop_status') != UNDER_MAINTENANCE
        and str(vehicle['id']) not in assigned_ids
    ]
    return available_vehicles, assigned_vehicles, drivers, technicians


def save_handover_process(data):
    handover_type = data.get('handover_type')
    if handover_type not in ('تسليم عهدة', 'إرجاع عهدة'):
        raise ValueError("نوع عملية الاستلام أو التسليم غير صحيح.")
    if handover_type == 'تسليم عهدة' and data.get('purpose') not in ('صرف', 'مهمة عمل', 'أخرى'):
        raise ValueError("يرجى اختيار غرض صحيح للعملية.")

    selected = (data.get('vehicle_info') or '').strip()
    session = SessionLocal()
    try:
        # Row lock on the vehicle serialises concurrent handovers of the same vehicle.
        vehicle = session.scalars(
            select(Vehicle).where(or_(
                cast(Vehicle.id, Text) == selected,
                Vehicle.plate_number == selected,
                Vehicle.vehicle_code == selected,
            )).limit(1).with_for_update()
        ).first()
        if vehicle is None:
            raise ValueError("المركبة المحددة غير موجودة.")

        vehicle_info = f"{vehicle.vehicle_code or ''} - {vehicle.plate_number or ''}".strip(' -')
        driver_info = (data.get('driver_info') or '').strip()
        archived_vehicle = session.scalar(
            select(exists().where(VehicleArchive.vehicle_id == vehicle.id))
        )
        active_record = session.scalars(
            select(Handover).where(
                or_(Handover.vehicle_id == vehicle.id, Handover.vehicle_info == vehicle_info),
                Handover.status == STATUS_ACTIVE,
            ).order_by(Handover.id.desc()).limit(1)
        ).first()

        if handover_type == 'تسليم عهدة':
            if archived_vehicle or vehicle.status == OUT_OF_SERVICE:
                raise ValueError("لا يمكن تسليم مركبة مؤرشفة وخارجة عن الخدمة.")
            if vehicle.status == DELIVERED or active_record:
                raise ValueError("المركبة مسلمة بالفعل ولا يمكن تسليمها مرة أخرى.")
            if vehicle.workshop_status == UNDER_MAINTENANCE or vehicle.status == UNDER_MAINTENANCE:
                raise ValueError("لا يمكن تسليم مركبة حالتها تحت الصيانة.")
            if not (data.get('department') or '').strip():
                raise ValueError("يرجى إدخال القسم التابع له.")
            if not (data.get('description') or '').strip():
                raise ValueError("يرجى إدخال وصف العملية.")
            record_status, vehicle_status = STATUS_ACTIVE, DELIVERED
        else:
            if not active_record:
                raise ValueError("لا توجد عهدة نشطة للمركبة المحددة لإرجاعها.")
            if driver_info != (active_record.driver_info or '').strip():
                raise ValueError("السائق المحدد لا يطابق العهدة النشطة للمركبة.")
            data['purpose'] = active_record.purpose
            data['department'] = active_record.department
            data['description'] = active_record.description
            if data.get('purpose') not in ('صرف', 'مهمة عمل', 'أخرى'):
                raise ValueError("غرض العملية النشطة غير صالح؛ يرجى مراجعة بيانات العهدة.")
            if not (data.get('department') or '').strip():
                raise ValueError("القسم غير مسجل في العهدة النشطة.")
            if not (data.get('description') or '').strip():
                raise ValueError("الوصف غير مسجل في العهدة النشطة.")
            active_record.status = STATUS_ARCHIVED
            record_status, vehicle_status = STATUS_PENDING, AVAILABLE

        session.add(Handover(
            handover_type=handover_type, vehicle_id=vehicle.id,
            handover_date=data.get('handover_date'), vehicle_info=vehicle_info,
            driver_info=driver_info, purpose=data.get('purpose'),
            department=data.get('department'), description=data.get('description'),
            odometer=data.get('odometer'), fuel_level=data.get('fuel_level'),
            body_condition=data.get('body_condition'),
            interior_condition=data.get('interior_condition'),
            tires_condition=data.get('tires_condition'),
            mechanical_condition=data.get('mechanical_condition'),
            electrical_condition=data.get('electrical_condition'),
            electrical_technician=data.get('electrical_technician'),
            mechanical_technician=data.get('mechanical_technician'),
            notes=data.get('notes'), status=record_status,
        ))
        vehicle.status = vehicle_status
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def delete_archived_handover_record(record_id):
    """Returns 'deleted', 'missing' or 'not_archived'."""
    with get_session() as session:
        record = session.get(Handover, record_id)
        if record is None:
            return 'missing'
        if record.status != STATUS_ARCHIVED:
            return 'not_archived'
        session.execute(delete(ApprovedDocument).where(
            ApprovedDocument.doc_type == 'handover_document',
            ApprovedDocument.item_id == str(record_id),
        ))
        session.delete(record)
    return 'deleted'


def get_driver_at_datetime(vehicle_plate, event_datetime):
    plate = str(vehicle_plate or '').strip()
    target = str(event_datetime or '').replace('T', ' ').strip()
    if not plate or not target:
        return MANAGEMENT_CUSTODY

    with get_session() as session:
        vehicle_id = session.scalar(select(Vehicle.id).where(Vehicle.plate_number == plate).limit(1))
        condition = Handover.vehicle_info.like(f"%{plate}%")
        if vehicle_id is not None:
            condition = or_(Handover.vehicle_id == vehicle_id, condition)
        records = session.scalars(
            select(Handover).where(condition).order_by(Handover.handover_date.asc(), Handover.id.asc())
        ).all()

    driver = MANAGEMENT_CUSTODY
    for record in records:
        recorded_at = str(record.handover_date or '').replace('T', ' ').strip()
        if not recorded_at or recorded_at[:16] > target[:16]:
            continue
        if record.handover_type == 'تسليم عهدة':
            driver = record.driver_info or MANAGEMENT_CUSTODY
        elif record.handover_type == 'إرجاع عهدة':
            driver = MANAGEMENT_CUSTODY
    return driver
