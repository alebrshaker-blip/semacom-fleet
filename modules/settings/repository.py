"""ORM data access for users, system settings, dynamic fields and password-reset tokens."""
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.database import get_session, now_text
from modules.settings.models.settings_orm import (
    DriverField,
    PasswordResetToken,
    SystemSetting,
    User,
)
from modules.vehicles.models.vehicle_orm import VehicleField

_TS_FORMAT = "%Y-%m-%d %H:%M:%S"


def _ts(delta=None):
    moment = datetime.now(timezone.utc)
    if delta is not None:
        moment += delta
    return moment.strftime(_TS_FORMAT)


# ---------------------------------------------------------------- settings
def get_setting(key, default=None):
    with get_session() as session:
        row = session.execute(select(SystemSetting.value).where(SystemSetting.key == key)).first()
        return row[0] if row else default


def get_settings(keys):
    """{key: value} for the given keys that exist."""
    with get_session() as session:
        rows = session.execute(
            select(SystemSetting.key, SystemSetting.value).where(SystemSetting.key.in_(list(keys)))
        ).all()
        return {key: value for key, value in rows}


def get_group_settings(group_name):
    with get_session() as session:
        rows = session.execute(
            select(SystemSetting.key, SystemSetting.value).where(SystemSetting.group_name == group_name)
        ).all()
        return {key: value for key, value in rows}


def get_all_settings():
    """[(key, value, group_name)] for every stored setting."""
    with get_session() as session:
        return [tuple(row) for row in session.execute(
            select(SystemSetting.key, SystemSetting.value, SystemSetting.group_name)
        ).all()]


def get_grouped_settings(raw=True):
    """{group: {key: value}}; values are JSON-decoded when raw is False."""
    grouped = {}
    for key, value, group in get_all_settings():
        if not raw:
            try:
                value = json.loads(value)
            except (ValueError, TypeError):
                pass
        grouped.setdefault(group or "general", {})[key] = value
    return grouped


def upsert_settings(items):
    """items: iterable of (key, value, group_name)."""
    rows = [
        {"key": key, "value": value, "group_name": group, "updated_at": now_text()}
        for key, value, group in items
    ]
    if not rows:
        return
    with get_session() as session:
        for row in rows:
            statement = pg_insert(SystemSetting).values(**row)
            session.execute(statement.on_conflict_do_update(
                index_elements=[SystemSetting.key],
                set_={
                    "value": statement.excluded.value,
                    "group_name": statement.excluded.group_name,
                    "updated_at": statement.excluded.updated_at,
                },
            ))


def seed_defaults(defaults):
    """defaults: iterable of (key, value, setting_type, group_name, description); keeps existing rows."""
    with get_session() as session:
        for key, value, setting_type, group_name, description in defaults:
            session.execute(pg_insert(SystemSetting).values(
                key=key, value=value, setting_type=setting_type,
                group_name=group_name, description=description,
            ).on_conflict_do_nothing(index_elements=[SystemSetting.key]))


def update_setting_description(key, description):
    with get_session() as session:
        session.execute(
            update(SystemSetting).where(SystemSetting.key == key).values(description=description)
        )


def replace_setting_value(key, old_value, new_value):
    with get_session() as session:
        session.execute(
            update(SystemSetting)
            .where(SystemSetting.key == key, SystemSetting.value == old_value)
            .values(value=new_value, updated_at=now_text())
        )


def set_setting_group(key, group_name):
    with get_session() as session:
        session.execute(
            update(SystemSetting).where(SystemSetting.key == key).values(group_name=group_name)
        )


# ------------------------------------------------------------------- users
def get_user(user_id):
    with get_session() as session:
        user = session.get(User, int(user_id)) if user_id is not None else None
        return user.to_dict() if user else None


def get_active_user(user_id):
    with get_session() as session:
        user = session.scalar(
            select(User).where(User.id == int(user_id), User.is_active == 1)
        ) if user_id is not None else None
        return user.to_dict() if user else None


def get_user_by_username(username):
    with get_session() as session:
        user = session.scalar(select(User).where(User.username == username))
        return user.to_dict() if user else None


def list_active_users():
    with get_session() as session:
        return [
            {"id": u.id, "username": u.username, "full_name": u.full_name,
             "role": u.role, "is_active": u.is_active}
            for u in session.scalars(select(User).where(User.is_active == 1).order_by(User.id))
        ]


def list_active_user_emails(role=None):
    with get_session() as session:
        statement = select(User.email).where(
            User.is_active == 1, User.email.is_not(None), func.trim(User.email) != ""
        )
        if role:
            statement = statement.where(User.role == role)
        return [email.strip() for email in session.scalars(statement).all()]


def count_active_admins(session=None):
    def _count(active_session):
        return active_session.scalar(
            select(func.count()).select_from(User).where(User.role == "admin", User.is_active == 1)
        )
    if session is not None:
        return _count(session)
    with get_session() as new_session:
        return _count(new_session)


def create_user(username, password_hash, full_name, role, email=None, is_active=1):
    """Raises sqlalchemy.exc.IntegrityError on a duplicate username."""
    with get_session() as session:
        user = User(
            username=username, password_hash=password_hash, full_name=full_name,
            email=email, role=role, is_active=is_active,
        )
        session.add(user)
        session.flush()
        return user.id


def ensure_default_admin(password_hash):
    with get_session() as session:
        exists = session.scalar(select(User.id).where(User.username == "admin"))
        if exists is None:
            session.add(User(
                username="admin", password_hash=password_hash, full_name="مدير النظام",
                email="admin@semacom.com", role="admin", is_active=1,
            ))


def normalize_user_roles():
    with get_session() as session:
        session.execute(
            update(User)
            .where(User.role.is_(None) | User.role.not_in(["admin", "visitor"]))
            .values(role="visitor")
        )


def update_user_fields(user_id, **values):
    values.setdefault("updated_at", now_text())
    with get_session() as session:
        session.execute(update(User).where(User.id == int(user_id)).values(**values))


def username_taken(username, exclude_user_id):
    with get_session() as session:
        return session.scalar(
            select(User.id).where(User.username == username, User.id != int(exclude_user_id))
        ) is not None


def change_user_role(user_id, role):
    """Returns (ok, error_code). The admin rows are locked so the last-admin rule is race-free."""
    with get_session() as session:
        admins = session.scalars(
            select(User).where(User.role == "admin", User.is_active == 1).with_for_update()
        ).all()
        target = session.scalar(
            select(User).where(User.id == int(user_id), User.is_active == 1).with_for_update()
        )
        if target is None:
            return False, "missing"
        if target.role == "admin" and role != "admin" and len(admins) <= 1:
            return False, "last_admin"
        target.role = role
        target.updated_at = now_text()
        return True, None


# ----------------------------------------------------- password reset tokens
def create_reset_token(email, token_hash, max_per_hour=3, lifetime_minutes=30):
    """Registers a reset token for the active user with this e-mail.
    Returns the user id when a token was stored, otherwise None."""
    with get_session() as session:
        user = session.scalar(
            select(User).where(User.is_active == 1, func.lower(func.trim(User.email)) == email.lower())
            .with_for_update()
        )
        if user is None:
            return None
        session.execute(delete(PasswordResetToken).where(
            PasswordResetToken.expires_at < _ts(timedelta(days=-1))
        ))
        recent = session.scalar(
            select(func.count()).select_from(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.created_at > _ts(timedelta(hours=-1)),
            )
        )
        if recent >= max_per_hour:
            return None
        session.execute(update(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None)
        ).values(used_at=_ts()))
        session.add(PasswordResetToken(
            user_id=user.id, token_hash=token_hash,
            expires_at=_ts(timedelta(minutes=lifetime_minutes)), created_at=_ts(),
        ))
        return user.id


def invalidate_user_tokens(user_id):
    with get_session() as session:
        session.execute(update(PasswordResetToken).where(
            PasswordResetToken.user_id == int(user_id), PasswordResetToken.used_at.is_(None)
        ).values(used_at=_ts()))


def reset_token_is_valid(token_hash):
    with get_session() as session:
        return session.scalar(
            select(PasswordResetToken.id).where(
                PasswordResetToken.token_hash == token_hash,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at > _ts(),
            )
        ) is not None


def consume_reset_token(token_hash, new_password_hash):
    """Sets the new password and burns the user's outstanding tokens. True on success."""
    with get_session() as session:
        token = session.scalar(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == token_hash,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at > _ts(),
            ).with_for_update()
        )
        if token is None:
            return False
        user = session.scalar(
            select(User).where(User.id == token.user_id, User.is_active == 1).with_for_update()
        )
        if user is None:
            return False
        user.password_hash = new_password_hash
        user.updated_at = now_text()
        session.execute(update(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None)
        ).values(used_at=_ts()))
        return True


# ---------------------------------------------------------- dynamic fields
def _field_model(entity_type):
    return VehicleField if entity_type == "vehicle" else DriverField


def list_dynamic_fields(entity_type):
    model = _field_model(entity_type)
    with get_session() as session:
        return [
            {"id": f.id, "name": f.name, "label": f.label, "required": f.required}
            for f in session.scalars(select(model))
        ]


def add_dynamic_field(entity_type, name, label, required=False):
    """Raises sqlalchemy.exc.IntegrityError on a duplicate name."""
    model = _field_model(entity_type)
    with get_session() as session:
        session.add(model(name=name, label=label, required=1 if required else 0))
