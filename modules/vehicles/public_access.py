import json
import os
import sqlite3
import uuid
from io import BytesIO
from pathlib import Path

import qrcode
from PIL import Image, UnidentifiedImageError
from flask import current_app, request, url_for
from werkzeug.utils import secure_filename

from utils.expiry_status import get_expiry_status
from core.database import DB_PATH as DATABASE_PATH


BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = DATABASE_PATH

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

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024
THANK_YOU_MESSAGE = "شكراً لكم، سيتم النظر في طلبكم وإبلاغكم بالرد في أقرب وقت."


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(DB_PATH))
    connection.row_factory = sqlite3.Row
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
                status TEXT NOT NULL DEFAULT 'جديد',
                submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TIMESTAMP
            );
            """
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
        except sqlite3.IntegrityError:
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
        SELECT a.vehicle_id, a.token, a.field_settings, v.*
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
        custom_fields = connection.execute(
            "SELECT name, label FROM vehicle_fields ORDER BY id"
        ).fetchall()
        for field in custom_fields:
            name = field["name"]
            if name in vehicle.keys() and name not in known_vehicle_fields:
                values[f"custom:{name}"] = vehicle[name] or "غير مسجل"
    return values


def get_field_definitions(connection, vehicle):
    definitions = [
        {"key": key, "label": label, "value_source": source}
        for key, label, source in PUBLIC_FIELDS
    ]
    if _table_exists(connection, "vehicle_fields"):
        for field in connection.execute(
            "SELECT name, label FROM vehicle_fields ORDER BY id"
        ).fetchall():
            if field["name"] in vehicle.keys() and all(
                item["key"] != field["name"] for item in definitions
            ):
                definitions.append({
                    "key": f"custom:{field['name']}",
                    "label": field["label"] or field["name"],
                    "value_source": "vehicle",
                })
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
            "editable": bool(current.get("editable", False)),
        }
    return settings


def create_vehicle_qr(token):
    base_url = (
        current_app.config.get("PUBLIC_BASE_URL")
        or os.environ.get("PUBLIC_BASE_URL")
        or request.host_url
    ).rstrip("/")
    public_path = url_for("vehicles.public_landing", token=token)
    public_url = f"{base_url}{public_path}"
    relative_path = Path("uploads") / "vehicle_qr" / f"{token}.png"
    qr_path = Path(current_app.static_folder) / relative_path
    qr_path.parent.mkdir(parents=True, exist_ok=True)
    qrcode.make(public_url).save(qr_path)
    return url_for("static", filename=relative_path.as_posix()), public_url


def validate_and_save_photos(files):
    upload_dir = Path(current_app.static_folder) / "uploads" / "vehicle_qr_reports"
    upload_dir.mkdir(parents=True, exist_ok=True)
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
        filename = f"{uuid.uuid4().hex}{extension}"
        file_path = upload_dir / filename
        try:
            file_path.write_bytes(payload)
        except OSError:
            for saved_name in saved_names:
                if saved_name:
                    (upload_dir / saved_name).unlink(missing_ok=True)
            raise
        saved_names.append(filename)
    return saved_names


def save_submission(vehicle_id, submission_type, message, proposed_values=None, photos=None):
    photos = photos or [None, None]
    connection = get_connection()
    try:
        connection.execute(
            """
            INSERT INTO vehicle_public_submissions
                (vehicle_id, submission_type, message, proposed_values, photo_1, photo_2)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                vehicle_id,
                submission_type,
                message,
                json.dumps(proposed_values, ensure_ascii=False) if proposed_values else None,
                photos[0],
                photos[1],
            ),
        )
        connection.commit()
    except sqlite3.Error:
        connection.rollback()
        if photos:
            upload_dir = Path(current_app.static_folder) / "uploads" / "vehicle_qr_reports"
            for filename in photos:
                if filename:
                    (upload_dir / filename).unlink(missing_ok=True)
        raise
    finally:
        connection.close()
