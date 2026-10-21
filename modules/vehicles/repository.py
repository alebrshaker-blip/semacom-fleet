"""ORM-backed CRUD for vehicles, custom vehicle fields and the vehicle archive."""
from sqlalchemy import column, exists, func, inspect, or_, select, table, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from core.database import engine, get_session
from modules.vehicles.models.vehicle_orm import (
    AVAILABLE,
    CORE_COLUMNS,
    Vehicle,
    VehicleArchive,
    VehicleField,
)

OUT_OF_SERVICE = "خارج الخدمة"
DUPLICATE_MESSAGE = "تنبيه: كود المركبة أو رقم اللوحة مسجل مسبقًا، يرجى إدخال قيمة مختلفة."
_DUPLICATE_MARKERS = (
    "vehicle code or plate already exists",
    "duplicate key value violates unique constraint",
)
_SEARCH_COLUMNS = (
    "vehicle_code", "plate_number", "vehicle_type", "model", "manufacturer", "color",
    "fuel_type", "engine_number", "chassis_number", "status", "ownership",
)


class DuplicateVehicleError(ValueError):
    pass


def _all_vehicle_columns():
    """Select every vehicles column, including user-added custom columns."""
    return select(text("vehicles.*")).select_from(Vehicle.__table__)


def _active_filter():
    archived = exists().where(VehicleArchive.vehicle_id == Vehicle.id)
    return ~archived, func.coalesce(Vehicle.status, "") != OUT_OF_SERVICE


def _norm(col):
    return func.lower(func.trim(col))


def is_unique_violation(error):
    message = str(getattr(error, "orig", error)).lower()
    return any(marker in message for marker in _DUPLICATE_MARKERS)


# ---------------------------------------------------------------- vehicles

def list_active(search_query=None):
    stmt = _all_vehicle_columns().where(*_active_filter()).order_by(Vehicle.id)
    if search_query:
        pattern = f"%{search_query}%"
        stmt = stmt.where(or_(*[getattr(Vehicle, name).ilike(pattern) for name in _SEARCH_COLUMNS]))
    with get_session() as session:
        return [dict(row) for row in session.connection().execute(stmt).mappings()]


def get_vehicle(vehicle_id):
    stmt = _all_vehicle_columns().where(Vehicle.id == vehicle_id)
    with get_session() as session:
        row = session.connection().execute(stmt).mappings().first()
        return dict(row) if row else None


def is_duplicate(field, value):
    """Case/space-insensitive uniqueness probe for vehicle_code or plate_number."""
    if field not in ("vehicle_code", "plate_number") or not str(value or "").strip():
        return False
    col = getattr(Vehicle, field)
    stmt = select(Vehicle.id).where(
        col.is_not(None), func.trim(col) != "", _norm(col) == str(value).strip().lower()
    ).limit(1)
    with get_session() as session:
        return session.execute(stmt).first() is not None


def create_vehicle(data):
    """Insert a vehicle. Keys that are not core columns are written to custom columns."""
    data = dict(data)
    data.setdefault("status", AVAILABLE)
    code = str(data.get("vehicle_code") or "").strip()
    plate = str(data.get("plate_number") or "").strip()
    if is_duplicate("vehicle_code", code) or is_duplicate("plate_number", plate):
        raise DuplicateVehicleError(DUPLICATE_MESSAGE)

    core = {key: value for key, value in data.items() if key in CORE_COLUMNS or key == "plate_number"}
    extras = {key: value for key, value in data.items() if key not in core}
    try:
        with get_session() as session:
            vehicle = Vehicle(**core)
            session.add(vehicle)
            session.flush()
            if extras:
                custom = table("vehicles", column("id"), *[column(name) for name in extras])
                session.execute(update(custom).where(custom.c.id == vehicle.id).values(**extras))
            return vehicle.id
    except IntegrityError as error:
        if is_unique_violation(error):
            raise DuplicateVehicleError(DUPLICATE_MESSAGE) from error
        raise


# ----------------------------------------------------------- custom fields

def list_custom_fields():
    with get_session() as session:
        rows = session.execute(
            select(VehicleField.name, VehicleField.label, VehicleField.required).order_by(VehicleField.id)
        ).all()
        return [{"name": r.name, "label": r.label, "required": r.required} for r in rows]


def add_custom_field(name, label, required=0):
    """Register a custom field and add its TEXT column to vehicles (idempotent)."""
    quoted = engine.dialect.identifier_preparer.quote_identifier(name)
    with engine.begin() as connection:
        connection.execute(text(f"ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS {quoted} TEXT"))
        connection.execute(
            pg_insert(VehicleField.__table__)
            .values(name=name, label=label, required=int(required or 0))
            .on_conflict_do_nothing(index_elements=["name"])
        )


# ----------------------------------------------------------------- archive

def list_archived(search_query=""):
    stmt = (
        select(
            text("vehicles.*"),
            VehicleArchive.id.label("archive_id"), VehicleArchive.reason,
            VehicleArchive.buyer_name, VehicleArchive.sale_value,
            VehicleArchive.handover_date, VehicleArchive.notes, VehicleArchive.archived_at,
        )
        .select_from(VehicleArchive)
        .join(Vehicle, Vehicle.id == VehicleArchive.vehicle_id)
        .order_by(VehicleArchive.archived_at.desc(), VehicleArchive.id.desc())
    )
    if search_query:
        pattern = f"%{search_query}%"
        stmt = stmt.where(or_(
            Vehicle.vehicle_code.ilike(pattern), Vehicle.plate_number.ilike(pattern),
            Vehicle.vehicle_type.ilike(pattern), Vehicle.model.ilike(pattern),
            VehicleArchive.reason.ilike(pattern), VehicleArchive.buyer_name.ilike(pattern),
            VehicleArchive.notes.ilike(pattern),
        ))
    with get_session() as session:
        return [dict(row) for row in session.connection().execute(stmt).mappings()]


def is_archived(vehicle_id):
    with get_session() as session:
        return session.execute(
            select(VehicleArchive.id).where(VehicleArchive.vehicle_id == vehicle_id)
        ).first() is not None


def archive_vehicle(vehicle_id, reason, buyer_name=None, sale_value=None, handover_date=None, notes=None):
    """Returns 'ok', 'not_found', 'active_handover' or 'conflict'."""
    try:
        with get_session() as session:
            vehicle = session.get(Vehicle, vehicle_id, with_for_update=True)
            if vehicle is None:
                return "not_found"
            if inspect(engine).has_table("handovers"):
                active = session.execute(
                    text("SELECT 1 FROM handovers WHERE vehicle_id = :vid AND status = 'نشط' LIMIT 1"),
                    {"vid": vehicle_id},
                ).first()
                if active:
                    return "active_handover"
            session.add(VehicleArchive(
                vehicle_id=vehicle_id, reason=reason, buyer_name=buyer_name or None,
                sale_value=sale_value, handover_date=handover_date or None, notes=notes or None,
                previous_status=vehicle.status, previous_workshop_status=vehicle.workshop_status,
            ))
            vehicle.status = OUT_OF_SERVICE
            vehicle.workshop_status = OUT_OF_SERVICE
        return "ok"
    except IntegrityError:
        return "conflict"


def restore_vehicle(vehicle_id):
    """Returns 'ok', 'no_archive' or 'no_vehicle'."""
    with get_session() as session:
        record = session.scalars(
            select(VehicleArchive).where(VehicleArchive.vehicle_id == vehicle_id).with_for_update()
        ).first()
        if record is None:
            return "no_archive"
        vehicle = session.get(Vehicle, vehicle_id, with_for_update=True)
        if vehicle is None:
            return "no_vehicle"
        vehicle.status = record.previous_status or AVAILABLE
        vehicle.workshop_status = record.previous_workshop_status or AVAILABLE
        session.delete(record)
    return "ok"


def delete_archive_record(vehicle_id):
    """Removes only the archive record; the vehicle stays out of service."""
    with get_session() as session:
        record = session.scalars(
            select(VehicleArchive).where(VehicleArchive.vehicle_id == vehicle_id)
        ).first()
        if record is None:
            return False
        session.delete(record)
    return True


__all__ = [
    "DuplicateVehicleError", "SQLAlchemyError", "add_custom_field", "archive_vehicle",
    "create_vehicle", "delete_archive_record", "get_vehicle", "is_archived", "is_duplicate",
    "list_active", "list_archived", "list_custom_fields", "restore_vehicle",
]
