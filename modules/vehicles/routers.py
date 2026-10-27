from io import BytesIO
import json
import math
from datetime import date
from config import settings
from core import database as dbapi
from core import storage
from flask import Blueprint, jsonify, render_template, request, redirect, url_for, flash, current_app, send_file
from pathlib import Path
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import RequestEntityTooLarge
from modules.vehicles import repository
from modules.vehicles.controller.vehicles_controller import VehiclesController
from modules.vehicles.public_access import (
    IMMUTABLE_PUBLIC_FIELDS,
    MAX_IMAGE_BYTES,
    MAX_PUBLIC_SUBMISSION_BYTES,
    MAX_PUBLIC_ISSUE_JSON_BYTES,
    MAX_AUDIO_BYTES,
    MAX_AUDIO_DURATION_SECONDS,
    MAX_IMAGE_COUNT,
    MAX_VIDEO_BYTES,
    MAX_VIDEO_SOURCE_BYTES,
    MAX_VIDEO_COMPRESSION_THRESHOLD_BYTES,
    MAX_VIDEO_DURATION_SECONDS,
    THANK_YOU_MESSAGE,
    create_public_image_upload_path,
    create_public_audio_upload_path,
    create_public_video_upload_path,
    create_vehicle_qr,
    ensure_public_tables,
    ensure_vehicle_token,
    generate_vehicle_qr_png,
    get_connection,
    get_field_definitions,
    get_public_profile,
    get_vehicle_information,
    is_public_video_upload_path,
    is_public_audio_upload_path,
    is_public_image_upload_path,
    is_public_issue_upload_path,
    read_field_settings,
    save_submission,
    validate_and_save_photos,
    validate_uploaded_video,
)

try:
    from utils.excel_export import generate_semacom_excel
except ImportError:
    generate_semacom_excel = None

from modules.settings.reference_lists import (
    load_reference_lists,
)

vehicles_bp = Blueprint("vehicles", __name__, url_prefix="/vehicles")


@vehicles_bp.route('/check-unique')
def check_vehicle_unique():
    field = request.args.get('field', '')
    value = (request.args.get('value') or '').strip()
    labels = {'vehicle_code': 'كود المركبة', 'plate_number': 'رقم اللوحة'}
    if field not in labels:
        return jsonify({'duplicate': False, 'message': ''}), 400
    if not value:
        return jsonify({'duplicate': False, 'message': ''})

    exists = repository.is_duplicate(field, value)
    return jsonify({
        'duplicate': exists,
        'message': f'{labels[field]} مسجل مسبقًا، يرجى إدخال قيمة مختلفة.' if exists else '',
    })


@vehicles_bp.route("/")
def vehicles_index():
    controller = VehiclesController()

    search_query = request.args.get("q", "").strip()
    page_size = 50
    total_vehicles = repository.count_active(search_query or None)
    page_count = max(1, (total_vehicles + page_size - 1) // page_size)
    page = min(page_count, max(1, request.args.get("page", 1, type=int) or 1))
    data = controller.get_all(search_query if search_query else None, page, page_size)
    fields = controller.get_all_fields()

    return render_template(
        "vehicles/views/index.html",
        vehicles=data,
        fields=fields,
        page=page,
        page_count=page_count,
        page_size=page_size,
        total_vehicles=total_vehicles,
    )


@vehicles_bp.route("/archive")
def vehicle_archive_index():
    search_query = request.args.get("q", "").strip()
    page_size = 50
    total_archived = repository.count_archived(search_query)
    page_count = max(1, (total_archived + page_size - 1) // page_size)
    page = min(page_count, max(1, request.args.get("page", 1, type=int) or 1))
    archived_vehicles = repository.list_archived(search_query, page=page, page_size=page_size)
    return render_template(
        "vehicles/views/archive.html",
        archived_vehicles=archived_vehicles,
        search_query=search_query,
        page=page,
        page_count=page_count,
        total_archived=total_archived,
    )


def get_archived_vehicles(search_query=""):
    return repository.list_archived(search_query)


@vehicles_bp.route("/archive/export")
def export_vehicle_archive():
    if not generate_semacom_excel:
        current_app.logger.error("Excel export helper is unavailable for vehicle archive.")
        return "خدمة تصدير Excel غير متاحة حاليًا.", 500

    archived_vehicles = get_archived_vehicles(request.args.get("q", "").strip())
    headers = [
        "#", "كود المركبة", "رقم اللوحة", "النوع", "الموديل", "سبب الإخراج",
        "اسم المشتري", "قيمة البيع", "تاريخ التسليم", "تاريخ الأرشفة", "الملاحظات",
    ]
    rows = []
    for index, vehicle in enumerate(archived_vehicles, start=1):
        rows.append([
            index,
            vehicle["vehicle_code"] or "-",
            vehicle["plate_number"] or "-",
            vehicle["vehicle_type"] or "-",
            vehicle["model"] or "-",
            vehicle["reason"] or "-",
            vehicle["buyer_name"] or "-",
            vehicle["sale_value"] if vehicle["sale_value"] is not None else "-",
            vehicle["handover_date"] or "-",
            vehicle["archived_at"] or "-",
            vehicle["notes"] or "-",
        ])
    return generate_semacom_excel("أرشيف_المركبات_الخارجة_عن_الخدمة", headers, rows)


@vehicles_bp.route("/archive/<int:vehicle_id>", methods=["GET", "POST"])
def archive_vehicle(vehicle_id):
    connection = dbapi.connect()  # only used for the reference-lists helper
    try:
        vehicle = repository.get_vehicle(vehicle_id)
        if not vehicle:
            flash("المركبة غير موجودة.", "danger")
            return redirect(url_for("vehicles.vehicles_index"))
        if repository.is_archived(vehicle_id):
            flash("هذه المركبة مؤرشفة بالفعل.", "warning")
            return redirect(url_for("vehicles.vehicle_archive_index"))

        if request.method == "GET":
            archive_reasons = load_reference_lists(connection)["vehicle_archive_reasons"]
            return render_template(
                "vehicles/views/archive_form.html",
                vehicle=vehicle,
                archive_reasons=archive_reasons,
            )

        reason = (request.form.get("reason") or "").strip()
        archive_reasons = load_reference_lists(connection)["vehicle_archive_reasons"]
        buyer_name = (request.form.get("buyer_name") or "").strip()
        sale_value_raw = (request.form.get("sale_value") or "").strip()
        handover_date = (request.form.get("handover_date") or "").strip()
        notes = (request.form.get("notes") or "").strip()

        if reason not in archive_reasons:
            return render_template(
                "vehicles/views/archive_form.html",
                vehicle=vehicle,
                archive_reasons=archive_reasons,
                form_data=request.form,
                error="يرجى اختيار سبب صحيح لإخراج المركبة من الخدمة.",
            ), 400

        sale_value = None
        if reason == "بيع":
            if not buyer_name or not sale_value_raw or len(buyer_name) > 200:
                return render_template(
                    "vehicles/views/archive_form.html",
                    vehicle=vehicle,
                    archive_reasons=archive_reasons,
                    form_data=request.form,
                    error="اسم المشتري (بحد أقصى 200 حرف) وقيمة البيع مطلوبان عند اختيار سبب البيع.",
                ), 400
            try:
                sale_value = float(sale_value_raw)
                if not math.isfinite(sale_value) or sale_value < 0:
                    raise ValueError
            except ValueError:
                return render_template(
                    "vehicles/views/archive_form.html",
                    vehicle=vehicle,
                    archive_reasons=archive_reasons,
                    form_data=request.form,
                    error="يرجى إدخال قيمة بيع صحيحة لا تقل عن صفر.",
                ), 400
        else:
            buyer_name = ""
        if handover_date:
            try:
                date.fromisoformat(handover_date)
            except ValueError:
                return render_template(
                    "vehicles/views/archive_form.html",
                    vehicle=vehicle,
                    archive_reasons=archive_reasons,
                    form_data=request.form,
                    error="يرجى إدخال تاريخ تسليم صحيح.",
                ), 400
        if len(notes) > 2000:
            return render_template(
                "vehicles/views/archive_form.html",
                vehicle=vehicle,
                archive_reasons=archive_reasons,
                form_data=request.form,
                error="يجب ألا تتجاوز الملاحظات 2000 حرف.",
            ), 400

        outcome = repository.archive_vehicle(
            vehicle_id, reason, buyer_name, sale_value, handover_date, notes
        )
        if outcome == "active_handover":
            flash(
                "لا يمكن أرشفة المركبة قبل إرجاع عهدتها النشطة.",
                "warning",
            )
            return redirect(url_for("vehicles.vehicles_index"))
        if outcome == "not_found":
            flash("المركبة غير موجودة.", "danger")
            return redirect(url_for("vehicles.vehicles_index"))
        if outcome == "conflict":
            flash("تعذر أرشفة المركبة؛ قد تكون مؤرشفة مسبقًا.", "warning")
            return redirect(url_for("vehicles.vehicle_archive_index"))
        flash("تم إخراج المركبة من الخدمة وأرشفتها بنجاح.", "success")
        return redirect(url_for("vehicles.vehicle_archive_index"))
    finally:
        connection.close()


@vehicles_bp.route("/archive/<int:vehicle_id>/restore", methods=["POST"])
def restore_archived_vehicle(vehicle_id):
    try:
        outcome = repository.restore_vehicle(vehicle_id)
    except SQLAlchemyError:
        current_app.logger.exception("Failed to restore archived vehicle %s", vehicle_id)
        flash("تعذر استعادة المركبة الآن. يرجى مراجعة سجل النظام.", "danger")
        return redirect(url_for("vehicles.vehicle_archive_index"))
    if outcome == "no_archive":
        flash("سجل الأرشفة غير موجود.", "warning")
        return redirect(url_for("vehicles.vehicle_archive_index"))
    if outcome == "no_vehicle":
        flash("تعذر استعادة المركبة لأن سجلها غير موجود.", "danger")
        return redirect(url_for("vehicles.vehicle_archive_index"))

    flash("تمت استعادة المركبة إلى سجل المركبات النشطة.", "success")
    return redirect(url_for("vehicles.vehicles_index"))


@vehicles_bp.route("/archive/<int:vehicle_id>/delete", methods=["POST"])
def delete_vehicle_archive(vehicle_id):
    try:
        deleted = repository.delete_archive_record(vehicle_id)
    except SQLAlchemyError:
        current_app.logger.exception(
            "Failed to delete archive record for vehicle %s", vehicle_id
        )
        flash("تعذر حذف سجل الأرشفة. يرجى مراجعة سجل النظام.", "danger")
        return redirect(url_for("vehicles.vehicle_archive_index"))
    if not deleted:
        flash("سجل الأرشفة غير موجود أو تمت إزالته مسبقًا.", "warning")
        return redirect(url_for("vehicles.vehicle_archive_index"))

    flash(
        "تم حذف سجل الأرشفة فقط؛ بقي سجل المركبة وبياناتها بحالة خارج الخدمة.",
        "success",
    )
    return redirect(url_for("vehicles.vehicle_archive_index"))


@vehicles_bp.route("/info/<int:vehicle_id>", methods=["GET", "POST"])
def vehicle_information(vehicle_id):
    connection = get_connection()
    try:
        ensure_public_tables(connection)
        vehicle = connection.execute(
            "SELECT * FROM vehicles WHERE id = ?", (vehicle_id,)
        ).fetchone()
        if not vehicle:
            return "المركبة غير موجودة.", 404

        token = ensure_vehicle_token(connection, vehicle_id)
        access = connection.execute(
            "SELECT field_settings, inquiries_enabled FROM vehicle_public_access WHERE vehicle_id = ?",
            (vehicle_id,),
        ).fetchone()
        definitions = get_field_definitions(connection, vehicle)

        if request.method == "POST":
            submitted_settings = {}
            for field in definitions:
                key = field["key"]
                visible = request.form.get(f"visible:{key}") == "on"
                editable = request.form.get(f"editable:{key}") == "on"
                submitted_settings[key] = {
                    "visible": visible,
                    "editable": (
                        editable and visible and key not in IMMUTABLE_PUBLIC_FIELDS
                    ),
                }
            connection.execute(
                """
                UPDATE vehicle_public_access
                SET field_settings = ?, inquiries_enabled = ?
                WHERE vehicle_id = ?
                """,
                (
                    json.dumps(submitted_settings, ensure_ascii=False),
                    int(request.form.get("inquiries_enabled") == "on"),
                    vehicle_id,
                ),
            )
            connection.commit()
            flash("تم حفظ إعدادات المعلومات العامة للمركبة.", "success")
            return redirect(url_for("vehicles.vehicle_information", vehicle_id=vehicle_id))

        settings = read_field_settings(access["field_settings"], definitions)
        information = get_vehicle_information(connection, vehicle)
        qr_path, public_url = create_vehicle_qr(token)
        return render_template(
            "vehicles/views/information.html",
            vehicle=dict(vehicle),
            fields=[
                {**field, "value": information.get(field["key"], "غير مسجل")}
                for field in definitions
            ],
            settings=settings,
            inquiries_enabled=bool(access["inquiries_enabled"]),
            qr_path=qr_path,
            qr_image_url=url_for(
                "vehicles.vehicle_information_qr_image", vehicle_id=vehicle_id
            ),
            public_url=public_url,
        )
    finally:
        connection.close()


@vehicles_bp.route("/info/<int:vehicle_id>/qr.png", methods=["GET"])
def vehicle_information_qr_image(vehicle_id):
    connection = get_connection()
    try:
        ensure_public_tables(connection)
        vehicle = connection.execute(
            "SELECT vehicle_code FROM vehicles WHERE id = ?", (vehicle_id,)
        ).fetchone()
        if not vehicle:
            return jsonify(success=False, error="المركبة غير موجودة."), 404

        token = ensure_vehicle_token(connection, vehicle_id)
        base_url = (
            current_app.config.get("PUBLIC_BASE_URL")
            or settings.PUBLIC_BASE_URL
            or request.host_url
        ).rstrip("/")
        public_url = f"{base_url}{url_for('vehicles.public_landing', token=token)}"
        image = BytesIO(generate_vehicle_qr_png(public_url))
        filename = f"{vehicle['vehicle_code'] or vehicle_id}-qr.png"
        return send_file(
            image,
            mimetype="image/png",
            as_attachment=False,
            download_name=filename,
            max_age=0,
        )
    except Exception:
        current_app.logger.exception("Failed to generate vehicle information QR image")
        return jsonify(success=False, error="تعذر تجهيز صورة رمز المركبة."), 500
    finally:
        connection.close()


@vehicles_bp.route("/public/<token>")
def public_landing(token):
    connection = get_connection()
    try:
        ensure_public_tables(connection)
        profile = get_public_profile(connection, token)
        if not profile:
            return render_template("vehicles/views/public_not_found.html"), 404
        return render_template(
            "vehicles/views/public_portal.html",
            mode="welcome",
            token=token,
            inquiries_enabled=bool(profile["inquiries_enabled"]),
            vehicle_label=f"{profile['vehicle_code'] or ''} - {profile['plate_number'] or ''}".strip(" -"),
        )
    finally:
        connection.close()


@vehicles_bp.route("/public/<token>/information")
def public_information(token):
    connection = get_connection()
    try:
        ensure_public_tables(connection)
        profile = get_public_profile(connection, token)
        if not profile:
            return render_template("vehicles/views/public_not_found.html"), 404
        definitions = get_field_definitions(connection, profile)
        information = get_vehicle_information(connection, profile)
        settings = read_field_settings(profile["field_settings"], definitions)
        fields = [
            {
                **field,
                "value": information.get(field["key"], "غير مسجل"),
                **settings[field["key"]],
            }
            for field in definitions
            if settings[field["key"]]["visible"]
        ]
        return render_template(
            "vehicles/views/public_portal.html",
            mode="information",
            token=token,
            fields=fields,
            inquiries_enabled=bool(profile["inquiries_enabled"]),
            vehicle_label=f"{profile['vehicle_code'] or ''} - {profile['plate_number'] or ''}".strip(" -"),
        )
    finally:
        connection.close()


@vehicles_bp.route("/public/<token>/request-update", methods=["POST"])
def public_request_update(token):
    connection = get_connection()
    try:
        ensure_public_tables(connection)
        profile = get_public_profile(connection, token)
        if not profile:
            return render_template("vehicles/views/public_not_found.html"), 404
        if request.content_length and request.content_length > 64 * 1024:
            return "حجم طلب تحديث البيانات أكبر من المسموح.", 413
        definitions = get_field_definitions(connection, profile)
        settings = read_field_settings(profile["field_settings"], definitions)
        proposed_values = {}
        for field in definitions:
            if not settings[field["key"]]["editable"]:
                continue
            value = (request.form.get(f"field_{field['key']}") or "").strip()
            if value:
                proposed_values[field["key"]] = {
                    "label": field["label"],
                    "value": value[:1000],
                }
        if not proposed_values:
            return redirect(url_for("vehicles.public_information", token=token))
        save_submission(
            profile["vehicle_id"],
            "طلب تحديث بيانات",
            "طلب تحديث بيانات المركبة من صفحة QR.",
            proposed_values=proposed_values,
        )
        return render_template(
            "vehicles/views/public_portal.html",
            mode="thanks",
            token=token,
            message=THANK_YOU_MESSAGE,
            vehicle_label=f"{profile['vehicle_code'] or ''} - {profile['plate_number'] or ''}".strip(" -"),
        )
    finally:
        connection.close()


@vehicles_bp.route("/public/<token>/issue")
def public_issue_form(token):
    connection = get_connection()
    try:
        ensure_public_tables(connection)
        profile = get_public_profile(connection, token)
        if not profile:
            return render_template("vehicles/views/public_not_found.html"), 404
        if not profile["inquiries_enabled"]:
            return "إرسال الاستفسارات والبلاغات غير متاح لهذه المركبة حالياً.", 403
        return render_template(
            "vehicles/views/public_portal.html",
            mode="issue",
            token=token,
            inquiries_enabled=True,
            supabase_anon_key=settings.SUPABASE_PUBLIC_KEY,
            max_video_upload_bytes=MAX_VIDEO_BYTES,
            max_video_source_bytes=MAX_VIDEO_SOURCE_BYTES,
            max_video_compression_threshold_bytes=MAX_VIDEO_COMPRESSION_THRESHOLD_BYTES,
            vehicle_label=f"{profile['vehicle_code'] or ''} - {profile['plate_number'] or ''}".strip(" -"),
        )
    finally:
        connection.close()


@vehicles_bp.route(
    "/public/<token>/video-upload", methods=["POST"],
    endpoint="public_video_upload_url",
)
@vehicles_bp.route(
    "/public/<token>/issue-media-upload", methods=["POST"],
    endpoint="public_issue_media_upload_url",
)
def public_issue_media_upload_url(token):
    connection = None
    try:
        connection = get_connection()
        ensure_public_tables(connection)
        profile = get_public_profile(connection, token)
        if not profile:
            return jsonify(success=False, error="رابط المركبة غير صالح أو منتهي الصلاحية."), 404
        if not profile["inquiries_enabled"]:
            return jsonify(success=False, error="إرسال الاستفسارات والبلاغات غير متاح لهذه المركبة حالياً."), 403
        if not settings.SUPABASE_PUBLIC_KEY:
            return jsonify(
                success=False,
                error="رفع الملفات غير مهيأ؛ يرجى ضبط مفتاح Supabase العام."
            ), 503
        payload = request.get_json(silent=True)
        kind = payload.get("kind", "video") if isinstance(payload, dict) else "video"
        extension = payload.get("extension") if isinstance(payload, dict) else None
        if kind == "image":
            path = create_public_image_upload_path(profile["vehicle_id"], extension)
            max_bytes = MAX_IMAGE_BYTES
            max_duration_seconds = None
            content_type = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".webp": "image/webp",
            }[extension.lower()]
        elif kind == "audio":
            path = create_public_audio_upload_path(profile["vehicle_id"], extension)
            max_bytes = MAX_AUDIO_BYTES
            max_duration_seconds = MAX_AUDIO_DURATION_SECONDS
            content_type = {
                ".webm": "audio/webm",
                ".m4a": "audio/mp4",
                ".ogg": "audio/ogg",
            }[extension.lower()]
        elif kind == "video":
            path = create_public_video_upload_path(profile["vehicle_id"], extension)
            max_bytes = MAX_VIDEO_BYTES
            max_duration_seconds = MAX_VIDEO_DURATION_SECONDS
            content_type = {
                ".mp4": "video/mp4",
                ".mov": "video/quicktime",
                ".webm": "video/webm",
            }[extension.lower()]
        else:
            raise ValueError("نوع الملف المطلوب رفعه غير صالح.")
        signed_upload = storage.create_signed_upload_url(path)
        return jsonify(
            success=True,
            signed_url=signed_upload["signed_url"],
            path=signed_upload["path"],
            public_url=storage.get_public_url(path),
            api_key=settings.SUPABASE_PUBLIC_KEY,
            kind=kind,
            content_type=content_type,
            max_bytes=max_bytes,
            max_source_bytes=MAX_VIDEO_SOURCE_BYTES if kind == "video" else max_bytes,
            max_duration_seconds=max_duration_seconds,
        )
    except RequestEntityTooLarge:
        return jsonify(
            success=False,
            error="تجاوز طلب بدء رفع الملف الحد الأقصى المسموح به.",
        ), 413
    except ValueError as error:
        return jsonify(success=False, error=str(error)), 400
    except storage.StorageError:
        current_app.logger.exception("Failed to create a vehicle QR media upload URL")
        return jsonify(
            success=False,
            error="تعذر بدء رفع الملف حالياً؛ حاول مرة أخرى لاحقاً.",
        ), 503
    except Exception:
        current_app.logger.exception("Unexpected error while preparing a vehicle media upload")
        return jsonify(
            success=False,
            error="حدث خطأ غير متوقع أثناء تجهيز رفع الملف.",
        ), 500
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                current_app.logger.exception("Failed to close vehicle video upload connection")


@vehicles_bp.route("/public/<token>/video-upload/cancel", methods=["POST"])
def public_cancel_video_upload(token):
    connection = None
    try:
        connection = get_connection()
        ensure_public_tables(connection)
        profile = get_public_profile(connection, token)
        if not profile:
            return jsonify(success=False, error="رابط المركبة غير صالح أو منتهي الصلاحية."), 404
        payload = request.get_json(silent=True)
        path = payload.get("path") if isinstance(payload, dict) else None
        if not is_public_issue_upload_path(path, profile["vehicle_id"]):
            return jsonify(success=False, error="مسار الملف غير صالح."), 400
        if not storage.delete_object(path):
            return jsonify(success=False, error="تعذر حذف الملف المؤقت."), 503
        return jsonify(success=True, deleted=True)
    except RequestEntityTooLarge:
        return jsonify(success=False, error="تجاوز طلب تنظيف الملف الحد الأقصى المسموح به."), 413
    except Exception:
        current_app.logger.exception("Failed to cancel a staged vehicle issue upload")
        return jsonify(success=False, error="تعذر حذف الملف المؤقت."), 500
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                current_app.logger.exception("Failed to close vehicle issue upload cleanup connection")


@vehicles_bp.route("/public/<token>/submit-issue", methods=["POST"])
def public_submit_issue(token):
    connection = None
    profile = None
    photos = []
    video_path = None
    audio_path = None
    is_json_submission = False
    request_limit = MAX_PUBLIC_SUBMISSION_BYTES
    try:
        is_json_submission = request.is_json
        connection = get_connection()
        ensure_public_tables(connection)
        profile = get_public_profile(connection, token)
        if not profile:
            return jsonify(success=False, error="رابط المركبة غير صالح أو منتهي الصلاحية."), 404
        if not profile["inquiries_enabled"]:
            return jsonify(
                success=False,
                error="إرسال الاستفسارات والبلاغات غير متاح لهذه المركبة حالياً.",
            ), 403
        app_request_limit = current_app.config.get(
            "MAX_CONTENT_LENGTH", settings.MAX_CONTENT_LENGTH
        )
        default_request_limit = (
            MAX_PUBLIC_ISSUE_JSON_BYTES
            if is_json_submission
            else MAX_PUBLIC_SUBMISSION_BYTES + MAX_AUDIO_BYTES
        )
        request_limit = min(
            default_request_limit,
            app_request_limit if app_request_limit is not None else default_request_limit,
        )
        if request.content_length and request.content_length > request_limit:
            return jsonify(
                success=False,
                error="تجاوز طلب البلاغ الحد الأقصى المسموح به.",
                max_bytes=request_limit,
            ), 413
        if is_json_submission:
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict):
                raise ValueError("بيانات البلاغ غير صالحة.")
            message = str(payload.get("message") or "").strip()
            photo_urls = payload.get("photo_urls") or []
            video_url = str(payload.get("video_url") or "").strip() or None
            audio_url = str(payload.get("audio_url") or "").strip() or None
            if not isinstance(photo_urls, list) or len(photo_urls) > MAX_IMAGE_COUNT:
                raise ValueError(f"يمكن إرفاق {MAX_IMAGE_COUNT} صور كحد أقصى.")
            if any(not isinstance(url, str) for url in photo_urls):
                raise ValueError("روابط الصور المرفقة غير صالحة.")
            for photo_url in photo_urls:
                path = storage.object_path_from_url(photo_url)
                if not path or not is_public_image_upload_path(path, profile["vehicle_id"]):
                    raise ValueError("رابط إحدى الصور المرفقة غير صالح.")
                photos.append(storage.get_public_url(path))
                size = storage.get_object_size(path)
                if size <= 0 or size > MAX_IMAGE_BYTES:
                    raise ValueError("يجب ألا يتجاوز حجم كل صورة 5 ميجابايت.")
            video = None
            if video_url:
                video_path = storage.object_path_from_url(video_url)
                if not video_path or not is_public_video_upload_path(
                    video_path, profile["vehicle_id"]
                ):
                    raise ValueError("رابط الفيديو المرفق غير صالح.")
                video = validate_uploaded_video(video_path, profile["vehicle_id"])
            audio = None
            if audio_url:
                audio_path = storage.object_path_from_url(audio_url)
                if not audio_path or not is_public_audio_upload_path(
                    audio_path, profile["vehicle_id"]
                ):
                    raise ValueError("رابط التسجيل الصوتي غير صالح.")
                audio_size = storage.get_object_size(audio_path)
                if audio_size <= 0 or audio_size > MAX_AUDIO_BYTES:
                    raise ValueError("يجب ألا يتجاوز حجم التسجيل الصوتي 5 ميجابايت.")
                audio = storage.get_public_url(audio_path)
        else:
            message = (request.form.get("message") or "").strip()
            video_path = (request.form.get("video_path") or "").strip() or None
            uploads = request.files.getlist("photos")
            uploads = [upload for upload in uploads if upload and upload.filename]
            if len(uploads) > MAX_IMAGE_COUNT:
                raise ValueError(f"يمكن إرفاق {MAX_IMAGE_COUNT} صور كحد أقصى.")
            photos = validate_and_save_photos(uploads)
            video = None
            audio = None
            audio_uploads = [
                upload for upload in request.files.getlist("audio")
                if upload and upload.filename
            ]
            if len(audio_uploads) > 1:
                raise ValueError("يمكن إرفاق تسجيل صوتي واحد فقط.")
            if audio_uploads:
                audio_upload = audio_uploads[0]
                extension = Path(audio_upload.filename).suffix.lower()
                audio_payload = audio_upload.read(MAX_AUDIO_BYTES + 1)
                if not audio_payload:
                    raise ValueError("ملف التسجيل الصوتي فارغ أو غير صالح.")
                if len(audio_payload) > MAX_AUDIO_BYTES:
                    raise ValueError("يجب ألا يتجاوز حجم التسجيل الصوتي 5 ميجابايت.")
                audio_path = create_public_audio_upload_path(
                    profile["vehicle_id"], extension
                )
                content_type = {
                    ".webm": "audio/webm",
                    ".m4a": "audio/mp4",
                    ".ogg": "audio/ogg",
                }[extension]
                audio = storage.upload_bytes(
                    audio_payload,
                    audio_path.rsplit("/", 1)[0],
                    content_type=content_type,
                    path=audio_path,
                )
            if video_path:
                if not is_public_video_upload_path(video_path, profile["vehicle_id"]):
                    raise ValueError("مسار الفيديو المرفوع غير صالح.")
                video = validate_uploaded_video(video_path, profile["vehicle_id"])
        if not message:
            raise ValueError("يرجى كتابة وصف المشكلة أو الاستفسار.")
        save_submission(
            profile["vehicle_id"],
            "استفسار أو بلاغ مشكلة",
            message[:4000],
            photos=photos,
            video=video,
            audio=audio,
        )
        return jsonify(
            success=True,
            message=THANK_YOU_MESSAGE,
            redirect_url=url_for("vehicles.public_vehicle_submissions", token=token),
        )
    except RequestEntityTooLarge:
        current_app.logger.info("Rejected oversized vehicle QR issue submission")
        _cleanup_failed_issue_uploads(
            photos, video_path, profile.get("vehicle_id") if profile else None,
            audio_path,
        )
        return jsonify(
            success=False,
            error="تجاوز طلب البلاغ الحد الأقصى المسموح به.",
            max_bytes=request_limit,
        ), 413
    except ValueError as error:
        _cleanup_failed_issue_uploads(
            photos, video_path, profile.get("vehicle_id") if profile else None,
            audio_path,
        )
        return jsonify(success=False, error=str(error)), 400
    except storage.StorageError:
        current_app.logger.exception("Vehicle QR report upload failed")
        _cleanup_failed_issue_uploads(
            photos, video_path, profile.get("vehicle_id") if profile else None,
            audio_path,
        )
        return jsonify(
            success=False,
            error="تعذر رفع المرفقات حالياً؛ حاول مرة أخرى لاحقاً.",
        ), 503
    except Exception:
        current_app.logger.exception("Unexpected error while processing a vehicle QR issue submission")
        _cleanup_failed_issue_uploads(
            photos, video_path, profile.get("vehicle_id") if profile else None,
            audio_path,
        )
        return jsonify(
            success=False,
            error="حدث خطأ غير متوقع أثناء معالجة البلاغ.",
        ), 500
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                current_app.logger.exception("Failed to close vehicle issue submission connection")


def _cleanup_failed_issue_uploads(photos, video_path, vehicle_id, audio_path=None):
    try:
        storage.delete_files(*photos)
    except Exception:
        current_app.logger.exception("Failed to clean up vehicle issue photos")
    if video_path and vehicle_id and is_public_video_upload_path(video_path, vehicle_id):
        try:
            storage.delete_object(video_path)
        except Exception:
            current_app.logger.exception("Failed to clean up staged vehicle issue video")
    if audio_path and vehicle_id and is_public_audio_upload_path(audio_path, vehicle_id):
        try:
            storage.delete_object(audio_path)
        except Exception:
            current_app.logger.exception("Failed to clean up staged vehicle issue audio")


@vehicles_bp.route("/public-submissions")
def public_submissions():
    connection = get_connection()
    try:
        ensure_public_tables(connection)
        rows = connection.execute(
            """
            SELECT s.*, v.vehicle_code, v.plate_number
            FROM vehicle_public_submissions s
            JOIN vehicles v ON v.id = s.vehicle_id
            ORDER BY CASE s.status WHEN 'جديد' THEN 0 ELSE 1 END,
                     s.submitted_at DESC, s.id DESC
            """
        ).fetchall()
        submissions = []
        for row in rows:
            submission = dict(row)
            submission["proposed_values"] = (
                json.loads(submission["proposed_values"])
                if submission["proposed_values"] else {}
            )
            submissions.append(_resolve_submission_attachments(submission))
        return render_template(
            "vehicles/views/public_submissions.html",
            submissions=submissions,
        )
    finally:
        connection.close()


@vehicles_bp.route("/public/<token>/submissions")
def public_vehicle_submissions(token):
    connection = get_connection()
    try:
        ensure_public_tables(connection)
        profile = get_public_profile(connection, token)
        if not profile:
            return render_template("vehicles/views/public_not_found.html"), 404
        rows = connection.execute(
            """
            SELECT id, submission_type, message, response, status, submitted_at,
                   photo_1, photo_2, photo_3, photo_4, photo_5, video_1, audio_1
            FROM vehicle_public_submissions
            WHERE vehicle_id = ? AND submission_type = 'استفسار أو بلاغ مشكلة'
            ORDER BY submitted_at DESC, id DESC
            """,
            (profile["vehicle_id"],),
        ).fetchall()
        return render_template(
            "vehicles/views/public_portal.html",
            mode="submissions",
            token=token,
            inquiries_enabled=bool(profile["inquiries_enabled"]),
            submissions=[
                _resolve_submission_attachments(dict(row)) for row in rows
            ],
            vehicle_label=f"{profile['vehicle_code'] or ''} - {profile['plate_number'] or ''}".strip(" -"),
        )
    finally:
        connection.close()


def _resolve_submission_attachments(submission):
    for field in (
        "photo_1", "photo_2", "photo_3", "photo_4", "photo_5", "video_1", "audio_1"
    ):
        submission[field] = storage.resolve_url(
            submission.get(field), "uploads/vehicle_qr_reports"
        )
    return submission


@vehicles_bp.route("/public-submissions/<int:submission_id>/review", methods=["POST"])
def review_public_submission(submission_id):
    connection = get_connection()
    try:
        ensure_public_tables(connection)
        cursor = connection.execute(
            """
            UPDATE vehicle_public_submissions
            SET status = 'تمت المراجعة', reviewed_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (submission_id,),
        )
        if cursor.rowcount == 0:
            return "البلاغ غير موجود.", 404
        connection.commit()
        flash("تم تحديث حالة البلاغ إلى تمت المراجعة.", "success")
        return redirect(url_for("vehicles.public_submissions"))
    finally:
        connection.close()


@vehicles_bp.route("/public-submissions/<int:submission_id>/reply", methods=["POST"])
def reply_public_submission(submission_id):
    response = (request.form.get("response") or "").strip()
    if not response:
        flash("يرجى كتابة الرد قبل إرساله.", "error")
        return redirect(url_for("vehicles.public_submissions"))
    connection = get_connection()
    try:
        ensure_public_tables(connection)
        cursor = connection.execute(
            """
            UPDATE vehicle_public_submissions
            SET response = ?, status = 'تمت المراجعة', reviewed_at = CURRENT_TIMESTAMP
            WHERE id = ? AND submission_type = 'استفسار أو بلاغ مشكلة'
            """,
            (response[:4000], submission_id),
        )
        if cursor.rowcount == 0:
            return "البلاغ غير موجود.", 404
        connection.commit()
        flash("تم حفظ الرد وإتاحته للزائر.", "success")
        return redirect(url_for("vehicles.public_submissions"))
    finally:
        connection.close()


@vehicles_bp.route("/public-submissions/<int:submission_id>/delete", methods=["POST"])
def delete_public_submission(submission_id):
    connection = get_connection()
    try:
        ensure_public_tables(connection)
        submission = connection.execute(
            """
            SELECT photo_1, photo_2, photo_3, photo_4, photo_5, video_1, audio_1
            FROM vehicle_public_submissions WHERE id = ?
            """,
            (submission_id,),
        ).fetchone()
        if not submission:
            return "البلاغ غير موجود.", 404
        connection.execute(
            "DELETE FROM vehicle_public_submissions WHERE id = ?", (submission_id,)
        )
        connection.commit()
        storage.delete_files(*submission)
        flash("تم حذف البلاغ والرد والمرفقات المرتبطة به.", "success")
        return redirect(url_for("vehicles.public_submissions"))
    finally:
        connection.close()


@vehicles_bp.route("/add")
def add_vehicle():
    return render_template("vehicles/views/add.html")


@vehicles_bp.route("/save", methods=["POST"])
def save_vehicle():
    controller = VehiclesController()

    base_fields = [
        "vehicle_code",
        "plate_number",
        "vehicle_type",
        "model",
        "manufacturer",
        "color",
        "fuel_type",
        "engine_number",
        "chassis_number",
        "ownership",
    ]

    data = {bf: request.form.get(bf) for bf in base_fields}
    data["status"] = "متاحة"

    custom_labels = request.form.getlist("custom_label[]")
    custom_values = request.form.getlist("custom_value[]")
    custom_requireds = request.form.getlist("custom_required[]")

    try:
        seen_custom_labels = set()
        for i, raw_label in enumerate(custom_labels):
            c_label = " ".join(raw_label.split())
            c_val = custom_values[i].strip() if i < len(custom_values) else ""
            c_req = 1 if i < len(custom_requireds) and custom_requireds[i] == "1" else 0

            if not c_label:
                raise ValueError("يرجى إدخال عنوان عربي لكل حقل إضافي.")
            normalized_label = c_label.casefold()
            if normalized_label in seen_custom_labels:
                raise ValueError(f"الحقل «{c_label}» مكرر في النموذج.")
            seen_custom_labels.add(normalized_label)
            if c_req and not c_val:
                raise ValueError(f"الحقل الإضافي «{c_label}» إلزامي.")

            custom_field = repository.add_custom_field(c_label, c_req)
            data[custom_field["name"]] = c_val or None

        controller.add(data)

    except Exception as ex:
        return render_template("vehicles/views/add.html", error=str(ex), form_data=data)

    return redirect("/vehicles")


@vehicles_bp.route("/delete/<int:vehicle_id>", methods=["POST"])
def delete_vehicle(vehicle_id):
    flash("تم إيقاف الحذف الدائم حفاظًا على السجلات. استخدم أرشفة المركبة لإخراجها من الخدمة.", "warning")
    return redirect(url_for("vehicles.vehicles_index"))


@vehicles_bp.route("/export")
def export_vehicles_excel():
    """🌟 مسار تصدير سجل المركبات والمعدات إلى Excel مع دعم البحث"""
    controller = VehiclesController()
    search_query = request.args.get("q", "").strip()
    return controller.export_excel(search_query if search_query else None)