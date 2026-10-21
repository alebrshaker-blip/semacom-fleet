"""SQLAlchemy engine, session factory and declarative Base (PostgreSQL), plus a
DB-API style `connect()` for the raw-SQL code paths, backed by the same engine/pool."""
from contextlib import contextmanager

import psycopg2
from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import declarative_base, scoped_session, sessionmaker

from config import settings
from core.sql_compat import split_statements, translate

Error = psycopg2.Error
DatabaseError = psycopg2.DatabaseError
IntegrityError = psycopg2.IntegrityError
OperationalError = psycopg2.OperationalError

# Flag columns are INTEGER (0/1) across the schema, so send Python bools as ints.
psycopg2.extensions.register_adapter(bool, lambda value: psycopg2.extensions.AsIs(int(value)))

BASE_DIR = settings.BASE_DIR
SCHEMA_PATH = settings.SCHEMA_PATH


def _database_url():
    raw_url = settings.DATABASE_URL
    if not raw_url:
        raise RuntimeError(
            "DATABASE_URL is not set. Add it to .env, e.g. "
            "postgresql+psycopg2://user:password@localhost:5432/semacom"
        )
    url = make_url(raw_url)
    if not url.drivername.startswith(("postgresql", "postgres")):
        raise RuntimeError("DATABASE_URL must point to a PostgreSQL database.")
    if url.drivername in ("postgres", "postgresql"):
        url = url.set(drivername="postgresql+psycopg2")
    return url


engine = create_engine(
    _database_url(),
    pool_pre_ping=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_recycle=settings.DB_POOL_RECYCLE,
    echo=settings.DB_ECHO,
)

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
metadata = MetaData(naming_convention=NAMING_CONVENTION)
Base = declarative_base(metadata=metadata)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
scoped_db_session = scoped_session(SessionLocal)


@contextmanager
def get_session():
    """Transactional SQLAlchemy session: commits on success, rolls back on error."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class Row(tuple):
    """Tuple that can also be indexed by column name (like sqlite3.Row)."""

    def __new__(cls, values, keys):
        row = super().__new__(cls, values)
        row._keys = tuple(keys)
        return row

    def keys(self):
        return list(self._keys)

    def _index(self, key):
        try:
            return self._keys.index(key)
        except ValueError:
            lowered = key.lower()
            for index, name in enumerate(self._keys):
                if name.lower() == lowered:
                    return index
            raise IndexError(f"No item with that key: {key}")

    def __getitem__(self, key):
        if isinstance(key, str):
            return super().__getitem__(self._index(key))
        return super().__getitem__(key)

    def get(self, key, default=None):
        try:
            return self[key]
        except IndexError:
            return default


def dict_factory(cursor, row):
    fields = [column[0] for column in cursor.description]
    return {key: value for key, value in zip(fields, row)}


class Cursor:
    def __init__(self, connection):
        self.connection = connection
        self._cursor = connection._raw.cursor()
        self.row_factory = None
        self.arraysize = 1
        self._last_was_insert = False

    @property
    def description(self):
        return self._cursor.description

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        if not self._last_was_insert:
            return None
        return self.connection._last_insert_id()

    def _wrap(self, values):
        if values is None:
            return None
        factory = self.row_factory or self.connection.row_factory
        names = [column[0] for column in self.description]
        if factory is None or factory is Row:
            return Row(values, names)
        return factory(self, tuple(values))

    def _run(self, statement, params):
        self.connection._run(self._cursor, statement, params)

    def execute(self, sql, params=None):
        params = tuple(params) if params is not None and not isinstance(params, dict) else params
        for statement in translate(sql, has_params=bool(params)):
            self._run(statement, params or None)
        self._last_was_insert = sql.lstrip()[:6].upper() == "INSERT"
        return self

    def executemany(self, sql, seq_of_params):
        statements = translate(sql, has_params=True)
        self.connection._ctl.execute("SAVEPOINT sqlcompat")
        try:
            self._cursor.executemany(statements[-1], list(seq_of_params))
        except Exception:
            self.connection._ctl.execute("ROLLBACK TO SAVEPOINT sqlcompat")
            raise
        self.connection._ctl.execute("RELEASE SAVEPOINT sqlcompat")
        return self

    def executescript(self, script):
        self.connection.commit()
        for statement in split_statements(script):
            for translated in translate(statement):
                self._run(translated, None)
        self.connection.commit()
        return self

    def fetchone(self):
        return self._wrap(self._cursor.fetchone()) if self.description else None

    def fetchall(self):
        if not self.description:
            return []
        return [self._wrap(values) for values in self._cursor.fetchall()]

    def fetchmany(self, size=None):
        if not self.description:
            return []
        rows = self._cursor.fetchmany(size or self.arraysize)
        return [self._wrap(values) for values in rows]

    def __iter__(self):
        return iter(self.fetchall())

    def close(self):
        self._cursor.close()


class Connection:
    """sqlite3-compatible connection on top of the SQLAlchemy engine's pool."""

    def __init__(self):
        self._raw = engine.raw_connection()
        self._ctl = self._raw.cursor()
        self.row_factory = None

    def _run(self, cursor, statement, params):
        # A savepoint per statement keeps the transaction usable after an
        # expected failure (sqlite code often catches an error and carries on).
        self._ctl.execute("SAVEPOINT sqlcompat")
        try:
            cursor.execute(statement, params)
        except Exception:
            self._ctl.execute("ROLLBACK TO SAVEPOINT sqlcompat")
            self._ctl.execute("RELEASE SAVEPOINT sqlcompat")
            raise
        self._ctl.execute("RELEASE SAVEPOINT sqlcompat")

    def _last_insert_id(self):
        self._ctl.execute("SAVEPOINT sqlcompat_id")
        try:
            self._ctl.execute("SELECT lastval()")
            value = self._ctl.fetchone()[0]
        except psycopg2.Error:
            self._ctl.execute("ROLLBACK TO SAVEPOINT sqlcompat_id")
            value = None
        self._ctl.execute("RELEASE SAVEPOINT sqlcompat_id")
        return value

    def cursor(self):
        return Cursor(self)

    def execute(self, sql, params=None):
        return self.cursor().execute(sql, params)

    def executemany(self, sql, seq_of_params):
        return self.cursor().executemany(sql, seq_of_params)

    def executescript(self, script):
        return self.cursor().executescript(script)

    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def close(self):
        if self._raw is not None:
            raw, self._raw = self._raw, None
            raw.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


def connect():
    """Open a pooled PostgreSQL connection with a sqlite3-style interface."""
    return Connection()


MODEL_MODULES = (
    "modules.drivers.models.driver_orm",
    "modules.vehicles.models.vehicle_orm",
    "modules.workshop.equ.models.asset_orm",
    "modules.violations.models.violation_orm",
    "modules.insurance.models.insurance_orm",
    "modules.workshop.maintenance.models.maintenance_orm",
    "modules.reports.models.report_orm",
    "modules.handover.models.handover_orm",
    "modules.workshop.oil_tracking.oil_orm",
    "modules.inspection.models.inspection_orm",
    "modules.tasks.models.tasks_orm",
    "modules.accidents.models.accidents_orm",
    "modules.settings.models.settings_orm",
    "modules.workshop.store.models.store_model",
    "modules.workshop.team.team_orm",
    "modules.workshop.comp_inspection.comp_inspection_orm",
    "modules.notifications.models.notifications_orm",
    "modules.vehicles.models.public_submission_orm",
)


def load_models():
    """Import every ORM model module so its tables register on Base.metadata."""
    import importlib

    for name in MODEL_MODULES:
        importlib.import_module(name)


def now_text():
    """UTC timestamp as 'YYYY-MM-DD HH:MM:SS' text (matches the Text column defaults)."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class DictMixin:
    """Adds to_dict() returning {column_name: value} for mapped columns."""

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}


def sync_columns():
    """Add columns that a model declares but an older table lacks (nullable, no data loss)."""
    from sqlalchemy import text

    # information_schema instead of inspect(): the global bool->int adapter breaks the inspector.
    preparer = engine.dialect.identifier_preparer
    with engine.begin() as connection:
        existing_by_table = {}
        for table_name, column_name in connection.execute(text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema()"
        )):
            existing_by_table.setdefault(table_name, set()).add(column_name)
        for table in Base.metadata.sorted_tables:
            existing = existing_by_table.get(table.name)
            if existing is None:
                continue
            for column in table.columns:
                if column.name in existing:
                    continue
                ddl = column.type.compile(dialect=engine.dialect)
                connection.execute(text(
                    f"ALTER TABLE {preparer.quote(table.name)} "
                    f"ADD COLUMN IF NOT EXISTS {preparer.quote(column.name)} {ddl}"
                ))


def init_orm_schema():
    """Create any missing tables and columns for the registered ORM models."""
    load_models()
    Base.metadata.create_all(bind=engine)
    sync_columns()


def ensure_compat_views():
    """sqlite_master lookalike so existing 'does table exist' checks keep working."""
    connection = connect()
    try:
        connection._ctl.execute(
            "CREATE OR REPLACE VIEW sqlite_master AS "
            "SELECT 'table'::text AS type, table_name::text AS name, "
            "table_name::text AS tbl_name, NULL::text AS sql "
            "FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE' "
            "UNION ALL "
            "SELECT 'index'::text, indexname::text, tablename::text, indexdef::text "
            "FROM pg_indexes WHERE schemaname = current_schema()"
        )
        connection.commit()
    finally:
        connection.close()


class Database:
    def __init__(self):
        self.connection = connect()
        self.connection.row_factory = dict_factory
        self.cursor = self.connection.cursor()
        self.initialize_database()

    def initialize_database(self):
        with open(SCHEMA_PATH, "r", encoding="utf-8") as schema_file:
            self.cursor.executescript(schema_file.read())

    def fetch_all(self, query, params=()):
        self.cursor.execute(query, params)
        return self.cursor.fetchall()

    def execute(self, query, params=()):
        self.cursor.execute(query, params)
        self.connection.commit()

    def close(self):
        self.connection.close()
