from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from core import database as dbapi
from core.database import engine, get_session
from modules.drivers.models.driver_orm import Driver

# Case-insensitive uniqueness of name / national id. The SQLite-style trigger
# DDL is translated to plpgsql by core.sql_compat.
IDENTITY_TRIGGERS = '''
    CREATE TRIGGER IF NOT EXISTS drivers_unique_identity_insert
    BEFORE INSERT ON drivers
    WHEN (NEW.name IS NOT NULL AND TRIM(NEW.name) != '' AND EXISTS (
            SELECT 1 FROM drivers WHERE LOWER(TRIM(name)) = LOWER(TRIM(NEW.name))
         )) OR (NEW.national_id IS NOT NULL AND TRIM(NEW.national_id) != '' AND EXISTS (
            SELECT 1 FROM drivers WHERE LOWER(TRIM(national_id)) = LOWER(TRIM(NEW.national_id))
         ))
    BEGIN
        SELECT RAISE(ABORT, 'driver name or national id already exists');
    END;
    CREATE TRIGGER IF NOT EXISTS drivers_unique_identity_update
    BEFORE UPDATE OF name, national_id ON drivers
    WHEN (NEW.name IS NOT NULL AND TRIM(NEW.name) != '' AND EXISTS (
            SELECT 1 FROM drivers WHERE id != NEW.id AND LOWER(TRIM(name)) = LOWER(TRIM(NEW.name))
         )) OR (NEW.national_id IS NOT NULL AND TRIM(NEW.national_id) != '' AND EXISTS (
            SELECT 1 FROM drivers WHERE id != NEW.id AND LOWER(TRIM(national_id)) = LOWER(TRIM(NEW.national_id))
         ))
    BEGIN
        SELECT RAISE(ABORT, 'driver name or national id already exists');
    END;
'''

def init_driver_db():
    """Create the drivers table from the ORM model and install identity triggers."""
    Driver.__table__.create(bind=engine, checkfirst=True)
    conn = dbapi.connect()
    try:
        conn.executescript(IDENTITY_TRIGGERS)
        conn.commit()
    finally:
        conn.close()


def _normalized(column, value):
    return func.lower(func.trim(column)) == str(value).strip().lower()


def is_driver_value_duplicate(field, value, exclude_id=None):
    columns = {'name': Driver.name, 'national_id': Driver.national_id}
    if field not in columns or not str(value or '').strip():
        return False
    init_driver_db()
    column = columns[field]
    stmt = select(Driver.id).where(
        column.is_not(None), func.trim(column) != '', _normalized(column, value)
    )
    if exclude_id is not None:
        stmt = stmt.where(Driver.id != exclude_id)
    with get_session() as session:
        return session.execute(stmt.limit(1)).first() is not None


def get_all_drivers(search_query=""):
    init_driver_db()
    stmt = select(Driver).order_by(Driver.id)
    if search_query:
        pattern = f"%{search_query}%"
        stmt = stmt.where(or_(
            Driver.name.ilike(pattern),
            Driver.national_id.ilike(pattern),
            Driver.phone.ilike(pattern),
            Driver.license_number.ilike(pattern),
        ))
    with get_session() as session:
        return [driver.to_dict() for driver in session.scalars(stmt)]


def get_driver(driver_id):
    init_driver_db()
    with get_session() as session:
        driver = session.get(Driver, driver_id)
        return driver.to_dict() if driver else None


def add_driver(form_data):
    init_driver_db()
    name = str(form_data.get('name') or '').strip()
    national_id = str(form_data.get('national_id') or '').strip()
    if is_driver_value_duplicate('name', name):
        return False, 'اسم الموظف مسجل مسبقًا، يرجى إدخال اسم مختلف.'
    if national_id and is_driver_value_duplicate('national_id', national_id):
        return False, 'رقم الهوية مسجل مسبقًا لموظف آخر.'
    try:
        with get_session() as session:
            session.add(Driver(
                name=name,
                national_id=national_id,
                phone=form_data.get('phone'),
                nationality=form_data.get('nationality'),
                job_title=form_data.get('job_title'),
                department=form_data.get('department'),
                license_number=form_data.get('license_number'),
                license_type=form_data.get('license_type'),
                restrictions_count=int(form_data.get('restrictions_count', 0) or 0),
                license_issue_date=form_data.get('license_issue_date'),
                license_expiry_date=form_data.get('license_expiry_date'),
            ))
        return True, "تمت إضافة الموظف بنجاح"
    except IntegrityError as error:
        if 'driver name or national id' in str(error.orig).lower() or 'duplicate key' in str(error.orig).lower():
            return False, 'اسم الموظف أو رقم الهوية مسجل مسبقًا.'
        return False, f"خطأ: {error.orig}"
    except (SQLAlchemyError, ValueError) as error:
        return False, f"خطأ: {error}"


def update_driver(driver_id, form_data):
    init_driver_db()
    fields = ('name', 'national_id', 'phone', 'nationality', 'job_title', 'department',
              'license_number', 'license_type', 'restrictions_count',
              'license_issue_date', 'license_expiry_date')
    try:
        with get_session() as session:
            driver = session.get(Driver, driver_id)
            if driver is None:
                return False, 'الموظف غير موجود.'
            for field in fields:
                if field in form_data:
                    value = form_data.get(field)
                    if field == 'restrictions_count':
                        value = int(value or 0)
                    elif field in ('name', 'national_id'):
                        value = str(value or '').strip()
                    setattr(driver, field, value)
        return True, 'تم تحديث بيانات الموظف.'
    except IntegrityError:
        return False, 'اسم الموظف أو رقم الهوية مسجل مسبقًا.'
    except (SQLAlchemyError, ValueError) as error:
        return False, f"خطأ: {error}"


def delete_driver(driver_id):
    init_driver_db()
    with get_session() as session:
        driver = session.get(Driver, driver_id)
        if driver is None:
            return False
        session.delete(driver)
    return True
