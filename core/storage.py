"""Supabase Storage helpers: every uploaded file lives in the 'app-files' bucket
and the database stores the public URL returned here."""
import logging
import mimetypes
import re
import uuid
from pathlib import Path
from urllib.parse import unquote, urlparse

from werkzeug.utils import secure_filename

from config import settings

_client = None
_logger = logging.getLogger(__name__)


class StorageError(RuntimeError):
    """Raised when a file cannot be stored in Supabase Storage."""


def is_url(value):
    return isinstance(value, str) and value.lower().startswith(('http://', 'https://'))


def _get_client():
    global _client
    if _client is None:
        if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
            raise StorageError(
                'Supabase Storage is not configured: set SUPABASE_URL and one of '
                'SUPABASE_SERVICE_ROLE_KEY, SUPABASE_KEY, or SUPABASE_ANON_KEY in .env.'
            )
        from supabase import create_client
        _client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    return _client


def _bucket():
    return _get_client().storage.from_(settings.SUPABASE_BUCKET)


def _validate_object_path(path):
    if (
        not isinstance(path, str)
        or not path
        or path.startswith("/")
        or any(part in {"", ".", ".."} for part in path.split("/"))
    ):
        raise StorageError("Invalid Supabase Storage object path.")
    return path


def _object_path(folder, original_name, extension=None):
    suffix = extension or Path(secure_filename(original_name or '')).suffix.lower()
    stem = re.sub(r'[^A-Za-z0-9_-]', '', Path(secure_filename(original_name or '')).stem)[:40]
    name = f"{uuid.uuid4().hex}{'_' + stem if stem else ''}{suffix}"
    return f"{folder.strip('/')}/{name}"


def upload_bytes(data, folder, original_name='', content_type=None, extension=None,
                 path=None, upsert=False):
    """Upload raw bytes under `folder/` (or an explicit `path`); returns the public URL."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError('Supabase upload_bytes requires an in-memory bytes-like object.')
    data = bytes(data)
    path = path or _object_path(folder, original_name, extension)
    content_type = (
        content_type
        or mimetypes.guess_type(path)[0]
        or 'application/octet-stream'
    )
    try:
        bucket = _get_client().storage.from_(settings.SUPABASE_BUCKET)
        bucket.upload(
            path, data,
            {'content-type': content_type, 'upsert': 'true' if upsert else 'false'},
        )
        return str(bucket.get_public_url(path)).rstrip('?')
    except StorageError:
        raise
    except Exception as exc:
        raise StorageError(
            f'Failed to upload {path} to Supabase Storage bucket '
            f'{settings.SUPABASE_BUCKET}: {exc}'
        ) from exc


def create_signed_upload_url(path):
    """Create a short-lived, single-object upload URL for browser-side uploads."""
    path = _validate_object_path(path)
    try:
        result = _bucket().create_signed_upload_url(path)
        return {
            "path": path,
            "signed_url": result["signed_url"],
        }
    except StorageError:
        raise
    except Exception as exc:
        raise StorageError(
            f'Failed to create a signed Supabase Storage upload URL: {exc}'
        ) from exc


def get_object_size(path):
    """Return the size of an existing object, or raise StorageError if unavailable."""
    path = _validate_object_path(path)
    folder, name = path.rsplit("/", 1)
    try:
        matches = _bucket().list(folder, {"limit": 2, "search": name})
        for item in matches:
            if item.get("name") != name:
                continue
            size = (item.get("metadata") or {}).get("size")
            if size is None:
                break
            return int(size)
        raise StorageError("The uploaded Supabase Storage object was not found.")
    except StorageError:
        raise
    except (TypeError, ValueError) as exc:
        raise StorageError("Supabase Storage returned an invalid object size.") from exc
    except Exception as exc:
        raise StorageError(f'Failed to inspect Supabase Storage object: {exc}') from exc


def download_object(path):
    """Download an object by its in-bucket path."""
    path = _validate_object_path(path)
    try:
        return _bucket().download(path)
    except StorageError:
        raise
    except Exception as exc:
        raise StorageError(f'Failed to download file from Supabase Storage: {exc}') from exc


def get_public_url(path):
    """Return the configured bucket's public URL for an in-bucket object."""
    path = _validate_object_path(path)
    try:
        return str(_bucket().get_public_url(path)).rstrip('?')
    except StorageError:
        raise
    except Exception as exc:
        raise StorageError(f'Failed to resolve Supabase Storage URL: {exc}') from exc


def delete_object(path):
    """Best-effort removal of an object identified by its in-bucket path."""
    try:
        path = _validate_object_path(path)
        _bucket().remove([path])
        return True
    except Exception:
        _logger.exception('Failed to delete Supabase Storage object %s', path)
        return False


def upload_file(file_storage, folder):
    """Upload a werkzeug FileStorage; returns the public URL or None when empty."""
    if not file_storage or not getattr(file_storage, 'filename', ''):
        return None
    data = file_storage.read()
    file_storage.stream.seek(0)
    return upload_bytes(
        data, folder, file_storage.filename,
        content_type=file_storage.mimetype or None,
    )


def download_file(url):
    """Download one of this application's Supabase Storage objects as bytes."""
    path = object_path_from_url(url)
    if not path:
        raise StorageError('The requested file is not in the configured Supabase bucket.')
    try:
        return _bucket().download(path)
    except StorageError:
        raise
    except Exception as exc:
        raise StorageError(f'Failed to download file from Supabase Storage: {exc}') from exc


def object_path_from_url(url):
    """Return the in-bucket object path for one of our public URLs, else None."""
    if not is_url(url):
        return None
    parsed = urlparse(url)
    configured_host = urlparse(settings.SUPABASE_URL).netloc
    if not configured_host or parsed.netloc.lower() != configured_host.lower():
        return None
    marker = f"/{settings.SUPABASE_BUCKET}/"
    path = unquote(parsed.path)
    index = path.find(marker)
    if index < 0:
        return None
    return path[index + len(marker):] or None


def delete_file(url):
    """Best-effort removal; legacy local filenames and foreign URLs are ignored."""
    path = object_path_from_url(url)
    if not path:
        return False
    try:
        _bucket().remove([path])
        return True
    except Exception:
        _logger.exception('Failed to delete Supabase Storage object %s', path)
        return False


def delete_files(*urls):
    for url in urls:
        if url:
            delete_file(url)


def resolve_url(value, legacy_prefix=''):
    """Value to put in <a>/<img>: stored URLs pass through, legacy names map to /static."""
    if not value:
        return ''
    if is_url(value):
        return value
    value = str(value).lstrip('/')
    if value.startswith('static/'):
        value = value[len('static/'):]
    if legacy_prefix and not value.startswith('uploads/'):
        value = f"{legacy_prefix.strip('/')}/{value}"
    return '/static/' + value
