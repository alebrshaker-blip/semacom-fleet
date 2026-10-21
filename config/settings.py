"""Central configuration. All values come from environment / the .env file."""
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
# Server-side key (service_role) so uploads work regardless of bucket policies.
SUPABASE_KEY = (
    os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY") or ""
).strip()
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "app-files").strip() or "app-files"

MAX_CONTENT_LENGTH = _get_int("MAX_CONTENT_LENGTH_MB", 32) * 1024 * 1024
SESSION_COOKIE_SECURE = _get_bool("SESSION_COOKIE_SECURE", IS_PRODUCTION)

DEFAULT_BASE_URL = os.environ.get("DEFAULT_BASE_URL", "http://localhost:5000").rstrip("/")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").strip()
GTK_PATH = os.environ.get("GTK_PATH", r"C:\Program Files\GTK3-Runtime Win64\bin")
