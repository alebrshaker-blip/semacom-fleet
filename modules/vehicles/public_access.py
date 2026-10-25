import json
import math
import mimetypes
import os
import re
import struct
from config import settings
from core import database as dbapi
from core import storage
import uuid
from io import BytesIO
from pathlib import Path

import qrcode
from PIL import Image, UnidentifiedImageError
from flask import current_app, request, url_for
from werkzeug.utils import secure_filename

from utils.expiry_status import get_expiry_status

UPLOAD_FOLDER = "vehicle_qr_reports"

BASE_DIR = Path(__file__).resolve().parents[2]

PUBLIC_FIELDS = [
    ("vehicle_code", "كود المركبة", "vehicle"),
    ("plate_number", "رقم اللوحة", "vehicle"),
    ("vehicle_type", "نوع المركبة", "vehicle"),
    ("model", "الموديل", "vehicle"),
    ("manufacturer", "الشركة المصنعة", "vehicle"),
    ("color", "اللون", "vehicle"),
    ("fuel_type", "نوع الوقود", "vehicle"),
    ("status", "حالة المركبة", "vehicle"),
    ("ownership", "الملكية", "vehicle"),
    ("insurance_status", "حالة التأمين", "insurance"),
    ("inspection_status", "حالة الفحص الدوري", "inspection"),
    ("active_violations", "المخالفات السارية", "violations"),
    ("assigned_driver", "السائق المستلم", "handover"),
    ("oil_status", "حالة الزيت", "oil"),
    ("odometer", "قراءة العداد", "comprehensive"),
    ("oil_odometer", "قراءة العداد عند تغيير الزيت", "comprehensive"),
    ("comprehensive_status", "حالة الفحص الشامل", "comprehensive"),
]

IMMUTABLE_PUBLIC_FIELDS = {
    "vehicle_code",
    "plate_number",
    "vehicle_type",
    "model",
    "manufacturer",
    "color",
    "fuel_type",
}
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm"}
MAX_VIDEO_BYTES = 200 * 1024 * 1024
MAX_VIDEO_DURATION_SECONDS = 120
MAX_PUBLIC_SUBMISSION_BYTES = 3 * MAX_IMAGE_BYTES + 1024 * 1024
MAX_PUBLIC_ISSUE_JSON_BYTES = 1024 * 1024
PUBLIC_VIDEO_UPLOAD_FOLDER = "vehicle_public_uploads"
THANK_YOU_MESSAGE = "شكراً لكم، سيتم النظر في طلبكم وإبلاغكم بالرد في أقرب وقت."


def get_connection():
    connection = dbapi.connect()
    connection.row_factory = dbapi.Row
    return connection


def ensure_public_tables(connection=None):
    owns_connection = connection is None
    connection = connection or get_connection()
    try:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS vehicle_public_access (
                vehicle_id INTEGER PRIMARY KEY,
                token TEXT NOT NULL UNIQUE,
                field_settings TEXT NOT NULL DEFAULT '{}',
                inquiries_enabled INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS vehicle_public_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle_id INTEGER NOT NULL,
                submission_type TEXT NOT NULL,
                message TEXT NOT NULL,
                proposed_values TEXT,
                photo_1 TEXT,
                photo_2 TEXT,
                photo_3 TEXT,
                video_1 TEXT,
                response TEXT,
                status TEXT NOT NULL DEFAULT 'جديد',
                submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TIMESTAMP
            );
            """
        )
        access_columns = {
            row["name"] for row in connection.execute(
                "PRAGMA table_info(vehicle_public_access)"
            ).fetchall()
        }
        if "inquiries_enabled" not in access_columns:
            connection.execute(
                "ALTER TABLE vehicle_public_access ADD COLUMN inquiries_enabled INTEGER NOT NULL DEFAULT 1"
            )
        submission_columns = {
            row["name"] for row in connection.execute(
                "PRAGMA table_info(vehicle_public_submissions)"
            ).fetchall()
        }
        for column in ("photo_3", "video_1", "response"):
            if column not in submission_columns:
                connection.execute(
                    f'ALTER TABLE vehicle_public_submissions ADD COLUMN "{column}" TEXT'
                )
        if owns_connection:
            connection.commit()
    finally:
        if owns_connection:
            connection.close()


def ensure_vehicle_token(connection, vehicle_id):
    row = connection.execute(
        "SELECT token FROM vehicle_public_access WHERE vehicle_id = ?",
        (vehicle_id,),
    ).fetchone()
    if row:
        return row["token"]

    while True:
        token = uuid.uuid4().hex
        try:
            connection.execute(
                "INSERT INTO vehicle_public_access (vehicle_id, token) VALUES (?, ?)",
                (vehicle_id, token),
            )
            connection.commit()
            return token
        except dbapi.IntegrityError:
            connection.rollback()
            existing = connection.execute(
                "SELECT token FROM vehicle_public_access WHERE vehicle_id = ?",
                (vehicle_id,),
            ).fetchone()
            if existing:
                return existing["token"]


def get_public_profile(connection, token):
    return connection.execute(
        """
        SELECT a.vehicle_id, a.token, a.field_settings, a.inquiries_enabled, v.*
        FROM vehicle_public_access a
        JOIN vehicles v ON v.id = a.vehicle_id
        WHERE a.token = ?
        """,
        (token,),
    ).fetchone()


def _table_exists(connection, table_name):
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone() is not None


def get_vehicle_information(connection, vehicle):
    plate = vehicle["plate_number"]
    values = {
        key: vehicle[key] if key in vehicle.keys() and vehicle[key] not in (None, "") else "غير مسجل"
        for key, _label, source in PUBLIC_FIELDS
        if source == "vehicle"
    }
    values["insurance_status"] = "غير مسجل"
    values["inspection_status"] = "غير مسجل"
    values["active_violations"] = "لا توجد مخالفات سارية"
    values["assigned_driver"] = "عهدة إدارة المعدات"
    values["oil_status"] = "غير مسجل"
    values["odometer"] = "غير مسجل"
    values["oil_odometer"] = "غير مسجل"
    values["comprehensive_status"] = "غير مسجل"

    if _table_exists(connection, "insurance_policies"):
        policy = connection.execute(
            """
            SELECT end_date FROM insurance_policies
            WHERE vehicle_plate = ?
            ORDER BY end_date DESC, id DESC LIMIT 1
            """,
            (plate,),
        ).fetchone()
        if policy:
            values["insurance_status"] = get_expiry_status(
                policy["end_date"], "ساري", "قارب على الانتهاء", "منتهي"
            )

    if _table_exists(connection, "inspections"):
        inspection = connection.execute(
            """
            SELECT expiry_date, result_status FROM inspections
            WHERE vehicle_plate = ?
            ORDER BY inspection_date DESC, id DESC LIMIT 1
            """,
            (plate,),
        ).fetchone()
        if inspection:
            passed = str(inspection["result_status"] or "").strip().lower() in {
                "ناجح", "pass", "passed"
            }
            values["inspection_status"] = (
                get_expiry_status(
                    inspection["expiry_date"], "ساري", "قارب على الانتهاء", "منتهي"
                )
                if passed else "غير مجتاز"
            )

    if _table_exists(connection, "violations"):
        violations = connection.execute(
            """
            SELECT violation_number, violation_type, violation_datetime,
                   fine_amount, location
            FROM violations
            WHERE vehicle_plate = ?
              AND (status = 'active' OR status IS NULL)
              AND (status_type IS NULL OR status_type = 'نشطة')
            ORDER BY violation_datetime DESC, id DESC
            """,
            (plate,),
        ).fetchall()
        if violations:
            values["active_violations"] = "\n".join(
                " - ".join(
                    str(value) for value in (
                        row["violation_number"] or row["violation_type"],
                        row["violation_datetime"],
                        f"{row['fine_amount']} ريال" if row["fine_amount"] is not None else None,
                        row["location"],
                    ) if value not in (None, "")
                )
                for row in violations
            )

    if _table_exists(connection, "handovers"):
        handover = connection.execute(
            """
            SELECT driver_info FROM handovers
            WHERE (vehicle_id = ? OR vehicle_info LIKE ?)
              AND status = 'نشط'
            ORDER BY handover_date DESC, id DESC LIMIT 1
            """,
            (vehicle["id"], f"%{plate}%"),
        ).fetchone()
        if handover and handover["driver_info"]:
            values["assigned_driver"] = handover["driver_info"]

    if _table_exists(connection, "oil_change_tracking"):
        oil_record = connection.execute(
            """
            SELECT current_mileage, last_oil_mileage, distance_interval,
                   distance_alert_threshold, tracking_mode
            FROM oil_change_tracking
            WHERE vehicle_plate = ?
            ORDER BY service_date DESC, id DESC LIMIT 1
            """,
            (plate,),
        ).fetchone()
        if oil_record:
            try:
                current = int(oil_record["current_mileage"] or 0)
                last = int(oil_record["last_oil_mileage"] or 0)
                interval = int(oil_record["distance_interval"] or 5000)
                threshold = int(oil_record["distance_alert_threshold"] or 1000)
                remaining = last + interval - current
                if oil_record["tracking_mode"] == "time":
                    values["oil_status"] = "تتبع زمني"
                elif last <= 0:
                    values["oil_status"] = "غير محدد"
                elif remaining < 0:
                    values["oil_status"] = f"متأخر بمقدار {abs(remaining)} كم"
                elif remaining <= threshold:
                    values["oil_status"] = f"قارب موعد التغيير، متبقي {remaining} كم"
                else:
                    values["oil_status"] = f"سليم، متبقي {remaining} كم"
            except (TypeError, ValueError):
                values["oil_status"] = "غير محدد"

    if _table_exists(connection, "comprehensive_inspections"):
        inspection = connection.execute(
            """
            SELECT current_mileage, oil_change_mileage, overall_status
            FROM comprehensive_inspections
            WHERE vehicle_plate = ?
            ORDER BY inspection_date DESC, id DESC LIMIT 1
            """,
            (plate,),
        ).fetchone()
        if inspection:
            values["odometer"] = inspection["current_mileage"] or "غير مسجل"
            values["oil_odometer"] = inspection["oil_change_mileage"] or "غير مسجل"
            values["comprehensive_status"] = inspection["overall_status"] or "غير مسجل"

    known_vehicle_fields = {key for key, _label, source in PUBLIC_FIELDS if source == "vehicle"}
    if _table_exists(connection, "vehicle_fields"):
        field_columns = {
            row["name"] for row in connection.execute(
                "PRAGMA table_info(vehicle_fields)"
            ).fetchall()
        }
        active_filter = " WHERE is_active = 1" if "is_active" in field_columns else ""
        custom_fields = connection.execute(
            f"SELECT name, label FROM vehicle_fields{active_filter} ORDER BY id"
        ).fetchall()
        seen_labels = set()
        for field in custom_fields:
            name = field["name"]
            normalized_label = " ".join((field["label"] or name).split()).casefold()
            if (
                name in vehicle.keys()
                and name not in known_vehicle_fields
                and normalized_label not in seen_labels
            ):
                values[f"custom:{name}"] = vehicle[name] or "غير مسجل"
                seen_labels.add(normalized_label)
    return values


def get_field_definitions(connection, vehicle):
    definitions = [
        {"key": key, "label": label, "value_source": source}
        for key, label, source in PUBLIC_FIELDS
    ]
    if _table_exists(connection, "vehicle_fields"):
        field_columns = {
            row["name"] for row in connection.execute(
                "PRAGMA table_info(vehicle_fields)"
            ).fetchall()
        }
        active_filter = " WHERE is_active = 1" if "is_active" in field_columns else ""
        seen_labels = set()
        for field in connection.execute(
            f"SELECT name, label FROM vehicle_fields{active_filter} ORDER BY id"
        ).fetchall():
            normalized_label = " ".join((field["label"] or field["name"]).split()).casefold()
            if field["name"] in vehicle.keys() and all(
                item["key"] != field["name"] for item in definitions
            ) and normalized_label not in seen_labels:
                definitions.append({
                    "key": f"custom:{field['name']}",
                    "label": field["label"] or field["name"],
                    "value_source": "vehicle",
                })
                seen_labels.add(normalized_label)
    return definitions


def read_field_settings(raw_settings, definitions):
    saved = json.loads(raw_settings or "{}")
    settings = {}
    for field in definitions:
        current = saved.get(field["key"], {})
        settings[field["key"]] = {
            "visible": bool(
                current.get("visible", not field["key"].startswith("custom:"))
            ),
        }
        settings[field["key"]]["editable"] = (
            settings[field["key"]]["visible"]
            and field["key"] not in IMMUTABLE_PUBLIC_FIELDS
            and bool(current.get("editable", False))
        )
    return settings


_QR_URLS = {}


def create_vehicle_qr(token):
    base_url = (
        current_app.config.get("PUBLIC_BASE_URL")
        or settings.PUBLIC_BASE_URL
        or request.host_url
    ).rstrip("/")
    public_path = url_for("vehicles.public_landing", token=token)
    public_url = f"{base_url}{public_path}"
    cache_key = (token, public_url)
    qr_url = _QR_URLS.get(cache_key)
    if qr_url is None:
        qr_url = storage.upload_bytes(
            generate_vehicle_qr_png(public_url), "vehicle_qr", content_type="image/png",
            path=f"vehicle_qr/{token}.png", upsert=True,
        )
        _QR_URLS[cache_key] = qr_url
    return qr_url, public_url


def generate_vehicle_qr_png(public_url):
    buffer = BytesIO()
    qrcode.make(public_url).save(buffer, format="PNG")
    return buffer.getvalue()


def validate_and_save_photos(files):
    saved_names = []
    contents = []
    for upload in files:
        if not upload or not upload.filename:
            contents.append(None)
            continue
        extension = Path(secure_filename(upload.filename)).suffix.lower()
        if extension not in ALLOWED_IMAGE_EXTENSIONS:
            raise ValueError("يرجى إرفاق صور بصيغة JPG أو PNG أو WEBP فقط.")
        payload = upload.read(MAX_IMAGE_BYTES + 1)
        upload.stream.seek(0)
        if len(payload) > MAX_IMAGE_BYTES:
            raise ValueError("يجب ألا يتجاوز حجم كل صورة 5 ميجابايت.")
        try:
            with Image.open(BytesIO(payload)) as image:
                image.verify()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            raise ValueError("تعذر قراءة إحدى الصور المرفقة؛ يرجى اختيار صورة صالحة.")
        contents.append((extension, payload))

    for item in contents:
        if item is None:
            saved_names.append(None)
            continue
        extension, payload = item
        try:
            url = storage.upload_bytes(
                payload, UPLOAD_FOLDER, extension=extension,
                content_type=mimetypes.guess_type(f"x{extension}")[0],
            )
        except storage.StorageError:
            storage.delete_files(*saved_names)
            raise
        saved_names.append(url)
    return saved_names


def _mp4_duration_seconds(payload):
    def read_box(start, end, target):
        offset = start
        while offset + 8 <= end:
            size = int.from_bytes(payload[offset:offset + 4], "big")
            box_type = payload[offset + 4:offset + 8]
            header_size = 8
            if size == 1:
                if offset + 16 > end:
                    return None
                size = int.from_bytes(payload[offset + 8:offset + 16], "big")
                header_size = 16
            elif size == 0:
                size = end - offset
            if size < header_size or offset + size > end:
                return None
            box_start = offset + header_size
            box_end = offset + size
            if box_type == target or (
                target == b"hdlr_vide" and box_type == b"hdlr"
            ):
                if target != b"hdlr_vide" or (
                    box_end - box_start >= 12
                    and payload[box_start + 8:box_start + 12] == b"vide"
                ):
                    return box_start, box_end
            if box_type in {b"moov", b"trak", b"mdia"}:
                result = read_box(box_start, box_end, target)
                if result:
                    return result
            offset = box_end
        return None

    moov = read_box(0, len(payload), b"moov")
    if not moov:
        return None
    file_type = read_box(0, len(payload), b"ftyp")
    if not file_type:
        return None
    mvhd = read_box(moov[0], moov[1], b"mvhd")
    if not mvhd:
        return None
    start, end = mvhd
    version = payload[start]
    if version == 0 and end - start >= 20:
        timescale = int.from_bytes(payload[start + 12:start + 16], "big")
        duration = int.from_bytes(payload[start + 16:start + 20], "big")
    elif version == 1 and end - start >= 32:
        timescale = int.from_bytes(payload[start + 20:start + 24], "big")
        duration = int.from_bytes(payload[start + 24:start + 32], "big")
    else:
        return None
    if not timescale or not duration:
        return None
    if not read_box(moov[0], moov[1], b"hdlr_vide"):
        return None
    return duration / timescale


def _read_ebml_vint(payload, offset, strip_marker):
    if offset >= len(payload) or payload[offset] == 0:
        return None
    first = payload[offset]
    marker = 0x80
    length = 1
    while not first & marker:
        marker >>= 1
        length += 1
        if length > 8:
            return None
    if offset + length > len(payload):
        return None
    value = first & (marker - 1) if strip_marker else first
    for byte in payload[offset + 1:offset + length]:
        value = (value << 8) | byte
    if strip_marker and value == (1 << (7 * length)) - 1:
        return None
    return value, offset + length


def _webm_duration_seconds(payload):
    if not payload.startswith(b"\x1a\x45\xdf\xa3"):
        return None
    segment_offset = payload.find(b"\x18\x53\x80\x67")
    info_offset = payload.find(b"\x15\x49\xa9\x66", segment_offset + 4)
    if segment_offset < 0 or info_offset < 0:
        return None

    info_size = _read_ebml_vint(payload, info_offset + 4, True)
    if not info_size:
        return None
    info_end = min(info_size[1] + info_size[0], len(payload))
    offset = info_size[1]
    timecode_scale = 1_000_000
    duration = None
    while offset < info_end:
        element_id = _read_ebml_vint(payload, offset, False)
        if not element_id:
            return None
        element_size = _read_ebml_vint(payload, element_id[1], True)
        if not element_size:
            return None
        data_start = element_size[1]
        data_end = data_start + element_size[0]
        if data_end > info_end:
            return None
        if element_id[0] == 0x2AD7B1 and 0 < element_size[0] <= 8:
            timecode_scale = int.from_bytes(payload[data_start:data_end], "big")
        elif element_id[0] == 0x4489:
            if element_size[0] == 4:
                duration = struct.unpack(">f", payload[data_start:data_end])[0]
            elif element_size[0] == 8:
                duration = struct.unpack(">d", payload[data_start:data_end])[0]
        offset = data_end
    if duration is None or not math.isfinite(duration) or duration <= 0 or timecode_scale <= 0:
        return None
    return duration * timecode_scale / 1_000_000_000


def create_public_video_upload_path(vehicle_id, extension):
    extension = str(extension or "").lower()
    if extension not in ALLOWED_VIDEO_EXTENSIONS:
        raise ValueError("يرجى إرفاق مقطع بصيغة MP4 أو MOV أو WEBM.")
    return (
        f"{PUBLIC_VIDEO_UPLOAD_FOLDER}/{int(vehicle_id)}/"
        f"{uuid.uuid4().hex}{extension}"
    )


def create_public_image_upload_path(vehicle_id, extension):
    extension = str(extension or "").lower()
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError("يرجى إرفاق صور بصيغة JPG أو PNG أو WEBP فقط.")
    return (
        f"{PUBLIC_VIDEO_UPLOAD_FOLDER}/{int(vehicle_id)}/images/"
        f"{uuid.uuid4().hex}{extension}"
    )


def is_public_video_upload_path(path, vehicle_id):
    prefix = f"{PUBLIC_VIDEO_UPLOAD_FOLDER}/{int(vehicle_id)}/"
    filename = path[len(prefix):] if isinstance(path, str) and path.startswith(prefix) else ""
    return bool(re.fullmatch(r"[a-f0-9]{32}\.(mp4|mov|webm)", filename))


def is_public_image_upload_path(path, vehicle_id):
    prefix = f"{PUBLIC_VIDEO_UPLOAD_FOLDER}/{int(vehicle_id)}/images/"
    filename = path[len(prefix):] if isinstance(path, str) and path.startswith(prefix) else ""
    return bool(re.fullmatch(r"[a-f0-9]{32}\.(jpg|jpeg|png|webp)", filename))


def is_public_issue_upload_path(path, vehicle_id):
    return (
        is_public_video_upload_path(path, vehicle_id)
        or is_public_image_upload_path(path, vehicle_id)
    )


def validate_uploaded_video(path, vehicle_id):
    path = str(path or "").strip()
    if not is_public_video_upload_path(path, vehicle_id):
        raise ValueError("تعذر التحقق من مقطع الفيديو؛ يرجى رفعه من جديد.")
    filename = path.rsplit("/", 1)[-1]
    extension = Path(filename).suffix.lower()
    size = storage.get_object_size(path)
    if size <= 0:
        raise ValueError("ملف الفيديو فارغ أو غير صالح.")
    if size > MAX_VIDEO_BYTES:
        raise ValueError("يجب ألا يتجاوز حجم مقطع الفيديو 200 ميجابايت.")
    payload = storage.download_object(path)
    if len(payload) > MAX_VIDEO_BYTES:
        raise ValueError("يجب ألا يتجاوز حجم مقطع الفيديو 200 ميجابايت.")
    duration = (
        _webm_duration_seconds(payload)
        if extension == ".webm"
        else _mp4_duration_seconds(payload)
    )
    if duration is None:
        raise ValueError("تعذر التحقق من مدة المقطع؛ أرفق ملف فيديو صالحاً.")
    if duration > MAX_VIDEO_DURATION_SECONDS:
        raise ValueError("يجب ألا تتجاوز مدة مقطع الفيديو دقيقتين.")
    return storage.get_public_url(path)


def save_submission(
    vehicle_id, submission_type, message, proposed_values=None, photos=None, video=None
):
    photos = list(photos or [])
    if len(photos) > 3:
        raise ValueError("يمكن إرفاق ثلاث صور كحد أقصى.")
    photos.extend([None] * (3 - len(photos)))
    connection = get_connection()
    try:
        connection.execute(
            """
            INSERT INTO vehicle_public_submissions
                (vehicle_id, submission_type, message, proposed_values,
                 photo_1, photo_2, photo_3, video_1)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                vehicle_id,
                submission_type,
                message,
                json.dumps(proposed_values, ensure_ascii=False) if proposed_values else None,
                photos[0],
                photos[1],
                photos[2],
                video,
            ),
        )
        connection.commit()
    except dbapi.Error:
        connection.rollback()
        if photos or video:
            storage.delete_files(*photos, video)
        raise
    finally:
        connection.close()
