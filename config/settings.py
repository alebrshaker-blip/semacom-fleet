"""Central configuration. All values come from environment / the .env file."""
import base64
import json
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _get_bool(name, default=False):
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name, default):
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError:
        raise RuntimeError(f"Environment variable {name} must be an integer.")


def _get_path(name, default):
    value = os.environ.get(name)
    path = Path(value.strip() if value and value.strip() else default).expanduser()
    return (path if path.is_absolute() else BASE_DIR / path).resolve()


APP_ENV = os.environ.get("APP_ENV", "development").strip().lower()
IS_PRODUCTION = APP_ENV == "production"
SECRET_KEY = os.environ.get("SECRET_KEY") or None

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = _get_int("PORT", 8000)

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
DB_POOL_SIZE = _get_int("DB_POOL_SIZE", 5)
DB_MAX_OVERFLOW = _get_int("DB_MAX_OVERFLOW", 10)
DB_POOL_RECYCLE = _get_int("DB_POOL_RECYCLE", 1800)
DB_ECHO = _get_bool("DB_ECHO", False)
SCHEMA_PATH = BASE_DIR / "database" / "schema.sql"

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
_SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
_SUPABASE_KEY_ALIAS = os.environ.get("SUPABASE_KEY", "").strip()
_SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "").strip()


def _is_public_supabase_key(value):
    if value.startswith("sb_publishable_"):
        return True
    if value.startswith("sb_secret_"):
        return False
    parts = value.split(".")
    if len(parts) != 3:
        return False
    try:
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except (ValueError, json.JSONDecodeError):
        return False
    return isinstance(claims, dict) and claims.get("role") == "anon"


# The server can use an anon key when Storage policies permit signed uploads.
# Prefer the service role for server-side operations, but never expose it to browsers.
SUPABASE_KEY = (
    _SUPABASE_SERVICE_ROLE_KEY or _SUPABASE_KEY_ALIAS or _SUPABASE_ANON_KEY
)
SUPABASE_ANON_KEY = _SUPABASE_ANON_KEY
SUPABASE_PUBLIC_KEY = next(
    (
        key for key in (_SUPABASE_ANON_KEY, _SUPABASE_KEY_ALIAS)
        if key and _is_public_supabase_key(key)
    ),
    "",
)
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "app-files").strip() or "app-files"

MAX_CONTENT_LENGTH = _get_int("MAX_CONTENT_LENGTH_MB", 32) * 1024 * 1024
SESSION_COOKIE_SECURE = _get_bool("SESSION_COOKIE_SECURE", IS_PRODUCTION)

DEFAULT_BASE_URL = os.environ.get("DEFAULT_BASE_URL", "http://localhost:5000").rstrip("/")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").strip()
GTK_PATH = os.environ.get("GTK_PATH", r"C:\Program Files\GTK3-Runtime Win64\bin")
