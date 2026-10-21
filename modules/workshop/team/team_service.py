import re

from sqlalchemy import column, delete, func, literal_column, or_, select, table, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.database import get_session
from modules.workshop.team.team_orm import TeamField, TeamMember

_IDENTIFIER = re.compile(r"^(?!\d)\w{1,63}$")
_IDENTITY_LOCK = 7420001
_SEARCH_COLUMNS = (
    TeamMember.full_name, TeamMember.national_id, TeamMember.phone,
    TeamMember.license_number, TeamMember.license_type, TeamMember.specialization,
)


class DuplicateMemberError(Exception):
    def __init__(self, field):
        super().__init__(field)
        self.field = field


def _normalized(expression):
    return func.lower(func.trim(expression))


def list_fields():
    with get_session() as session:
        return [row.to_dict() for row in session.scalars(select(TeamField).order_by(TeamField.id))]


def list_members(search=''):
    """Return members as dicts, including any custom columns added at runtime."""
    statement = select(literal_column('*')).select_from(TeamMember.__table__).order_by(TeamMember.id)
    if search:
        pattern = f"%{search}%"
        statement = statement.where(or_(*[col.ilike(pattern) for col in _SEARCH_COLUMNS]))
    with get_session() as session:
        return [dict(row) for row in session.execute(statement).mappings()]


def is_duplicate(field, value, session=None):
    if field not in ('full_name', 'national_id'):
        raise ValueError(field)
    column_ = getattr(TeamMember, field)
    statement = select(TeamMember.id).where(
        column_.is_not(None), func.trim(column_) != '', _normalized(column_) == _normalized(value),
    ).limit(1)
    if session is not None:
        return session.execute(statement).first() is not None
    with get_session() as own_session:
        return own_session.execute(statement).first() is not None


def _ensure_column(session, name):
    if not _IDENTIFIER.match(name):
        return False
    quoted = session.get_bind().dialect.identifier_preparer.quote(name)
    session.execute(text(f"ALTER TABLE team_members ADD COLUMN IF NOT EXISTS {quoted} TEXT"))
    return True


def add_member(data, custom_fields):
    """Insert a member and register custom fields.

    custom_fields: list of (name, label, value, required). Raises DuplicateMemberError.
    """
    base_names = {c.name for c in TeamMember.__table__.columns}
    with get_session() as session:
        session.execute(select(func.pg_advisory_xact_lock(_IDENTITY_LOCK)))
        if is_duplicate('full_name', data['full_name'], session):
            raise DuplicateMemberError('full_name')
        if data.get('national_id') and is_duplicate('national_id', data['national_id'], session):
            raise DuplicateMemberError('national_id')

        member = TeamMember(**{k: v for k, v in data.items() if k in base_names and k != 'id'})
        session.add(member)
        session.flush()

        extra = {}
        for name, label, value, required in custom_fields:
            if not name or name in base_names or not _ensure_column(session, name):
                continue
            session.execute(
                pg_insert(TeamField).values(name=name, label=label, required=required)
                .on_conflict_do_nothing(index_elements=['name'])
            )
            extra[name] = value
        if extra:
            session.execute(
                update(table('team_members', column('id'), *[column(n) for n in extra]))
                .where(column('id') == member.id).values(**extra)
            )
        return member.id


def delete_member(member_id):
    with get_session() as session:
        return session.execute(delete(TeamMember).where(TeamMember.id == member_id)).rowcount > 0
