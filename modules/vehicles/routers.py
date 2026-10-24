import json
import math
from datetime import date
from core import database as dbapi
from core import storage
from flask import Blueprint, jsonify, render_template, request, redirect, url_for, flash, current_app
from pathlib import Path
from sqlalchemy.exc import SQLAlchemyError
from modules.vehicles import repository
from modules.vehicles.controller.vehicles_controller import VehiclesController
from modules.vehicles.public_access import (
    IMMUTABLE_PUBLIC_FIELDS,
    THANK_YOU_MESSAGE,
    create_vehicle_qr,
    ensure_public_tables,
    ensure_vehicle_token,
    get_connection,
    get_field_definitions,
    get_public_profile,
    get_vehicle_information,
    read_field_settings,
    save_submission,
    validate_and_save_photos,
    validate_and_save_video,
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
            public_url=public_url,
        )
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
            vehicle_label=f"{profile['vehicle_code'] or ''} - {profile['plate_number'] or ''}".strip(" -"),
        )
    finally:
        connection.close()


@vehicles_bp.route("/public/<token>/submit-issue", methods=["POST"])
def public_submit_issue(token):
    connection = get_connection()
    try:
        ensure_public_tables(connection)
        profile = get_public_profile(connection, token)
        if not profile:
            return render_template("vehicles/views/public_not_found.html"), 404
        vehicle_label = f"{profile['vehicle_code'] or ''} - {profile['plate_number'] or ''}".strip(" -")
        if not profile["inquiries_enabled"]:
            return "إرسال الاستفسارات والبلاغات غير متاح لهذه المركبة حالياً.", 403
        request.max_content_length = 41 * 1024 * 1024
        if request.content_length and request.content_length > request.max_content_length:
            return render_template(
                "vehicles/views/public_portal.html",
                mode="issue",
                token=token,
                vehicle_label=vehicle_label,
                inquiries_enabled=True,
                error="إجمالي حجم المرفقات والبلاغ يتجاوز الحد المسموح.",
            ), 413
        message = (request.form.get("message") or "").strip()
        if not message:
            return render_template(
                "vehicles/views/public_portal.html",
                mode="issue",
                token=token,
                vehicle_label=vehicle_label,
                inquiries_enabled=True,
                error="يرجى كتابة وصف المشكلة أو الاستفسار.",
            ), 400
        uploads = request.files.getlist("photos")
        uploads = [upload for upload in uploads if upload and upload.filename]
        if len(uploads) > 3:
            return render_template(
                "vehicles/views/public_portal.html",
                mode="issue",
                token=token,
                vehicle_label=vehicle_label,
                inquiries_enabled=True,
                error="يمكن إرفاق ثلاث صور كحد أقصى.",
            ), 400
        photos = validate_and_save_photos(uploads)
        video = None
        try:
            video = validate_and_save_video(request.files.get("video"))
            save_submission(
                profile["vehicle_id"],
                "استفسار أو بلاغ مشكلة",
                message[:4000],
                photos=photos,
                video=video,
            )
        except (OSError, ValueError, storage.StorageError):
            storage.delete_files(*photos, video)
            raise
        except dbapi.Error:
            current_app.logger.exception("Failed to save a vehicle QR submission")
            raise
        return render_template(
            "vehicles/views/public_portal.html",
            mode="thanks",
            token=token,
            message=THANK_YOU_MESSAGE,
            inquiries_enabled=True,
            vehicle_label=vehicle_label,
        )
    except ValueError as error:
        return render_template(
            "vehicles/views/public_portal.html",
            mode="issue",
            token=token,
            vehicle_label=vehicle_label,
            inquiries_enabled=True,
            error=str(error),
        ), 400
    except storage.StorageError:
        current_app.logger.exception("Vehicle QR report upload failed")
        return render_template(
            "vehicles/views/public_portal.html",
            mode="issue",
            token=token,
            vehicle_label=vehicle_label,
            inquiries_enabled=True,
            error="تعذر رفع المرفقات حالياً؛ حاول مرة أخرى لاحقاً.",
        ), 503
    finally:
        connection.close()


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
                   photo_1, photo_2, photo_3, video_1
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
    for field in ("photo_1", "photo_2", "photo_3", "video_1"):
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
            SELECT photo_1, photo_2, photo_3, video_1
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
        for i, raw_label in enumerate(custom_labels):
            c_label = raw_label.strip()
            c_val = custom_values[i].strip() if i < len(custom_values) else ""
            c_req = 1 if i < len(custom_requireds) and custom_requireds[i] == "1" else 0

            if not c_label:
                raise ValueError("يرجى إدخال عنوان عربي لكل حقل إضافي.")
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