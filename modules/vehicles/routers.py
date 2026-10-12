import json
import sqlite3
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from pathlib import Path

from core.database import DB_PATH
from modules.vehicles.controller.vehicles_controller import VehiclesController
from modules.vehicles.public_access import (
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
)

vehicles_bp = Blueprint("vehicles", __name__, url_prefix="/vehicles")


@vehicles_bp.route("/")
def vehicles_index():
    controller = VehiclesController()

    search_query = request.args.get("q", "").strip()
    data = controller.get_all(search_query if search_query else None)
    fields = controller.get_all_fields()

    return render_template("vehicles/views/index.html", vehicles=data, fields=fields)


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
            "SELECT field_settings FROM vehicle_public_access WHERE vehicle_id = ?",
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
                    "editable": editable and visible,
                }
            connection.execute(
                "UPDATE vehicle_public_access SET field_settings = ? WHERE vehicle_id = ?",
                (json.dumps(submitted_settings, ensure_ascii=False), vehicle_id),
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
        return render_template(
            "vehicles/views/public_portal.html",
            mode="issue",
            token=token,
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
        if request.content_length and request.content_length > 11 * 1024 * 1024:
            return render_template(
                "vehicles/views/public_portal.html",
                mode="issue",
                token=token,
                vehicle_label=vehicle_label,
                error="إجمالي حجم الصور والبلاغ يتجاوز الحد المسموح.",
            ), 413
        message = (request.form.get("message") or "").strip()
        if not message:
            return render_template(
                "vehicles/views/public_portal.html",
                mode="issue",
                token=token,
                vehicle_label=vehicle_label,
                error="يرجى كتابة وصف المشكلة أو الاستفسار.",
            ), 400
        uploads = request.files.getlist("photos")
        if len(uploads) > 2:
            return render_template(
                "vehicles/views/public_portal.html",
                mode="issue",
                token=token,
                vehicle_label=vehicle_label,
                error="يمكن إرفاق صورتين كحد أقصى.",
            ), 400
        photos = validate_and_save_photos(uploads + [None] * (2 - len(uploads)))
        try:
            save_submission(
                profile["vehicle_id"],
                "استفسار أو بلاغ مشكلة",
                message[:4000],
                photos=photos,
            )
        except sqlite3.Error:
            current_app.logger.exception("Failed to save a vehicle QR submission")
            raise
        return render_template(
            "vehicles/views/public_portal.html",
            mode="thanks",
            token=token,
            message=THANK_YOU_MESSAGE,
            vehicle_label=vehicle_label,
        )
    except ValueError as error:
        return render_template(
            "vehicles/views/public_portal.html",
            mode="issue",
            token=token,
            vehicle_label=vehicle_label,
            error=str(error),
        ), 400
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
            submissions.append(submission)
        return render_template(
            "vehicles/views/public_submissions.html",
            submissions=submissions,
        )
    finally:
        connection.close()


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

    custom_names = request.form.getlist("custom_name[]")
    custom_labels = request.form.getlist("custom_label[]")
    custom_values = request.form.getlist("custom_value[]")
    custom_requireds = request.form.getlist("custom_required[]")

    try:
        conn = sqlite3.connect(str(DB_PATH))
        cur = conn.cursor()

        for i in range(len(custom_names)):
            c_name = custom_names[i].strip()
            c_label = custom_labels[i].strip()
            c_val = custom_values[i].strip()
            c_req = custom_requireds[i] if i < len(custom_requireds) else 0

            if c_name:
                try:
                    cur.execute(f'ALTER TABLE vehicles ADD COLUMN "{c_name}" TEXT')
                except sqlite3.OperationalError:
                    pass

                cur.execute(
                    "INSERT OR IGNORE INTO vehicle_fields (name, label, required) VALUES (?, ?, ?)",
                    (c_name, c_label, c_req),
                )

                data[c_name] = c_val

        conn.commit()
        conn.close()

        controller.add(data)

    except Exception as ex:
        return render_template("vehicles/views/add.html", error=str(ex), form_data=data)

    return redirect("/vehicles")


@vehicles_bp.route("/delete/<int:vehicle_id>", methods=["POST"])
def delete_vehicle(vehicle_id):
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    try:
        cur.execute("DELETE FROM vehicles WHERE id = ?", (vehicle_id,))
        conn.commit()
    except Exception as e:
        print("Error deleting vehicle:", e)
    finally:
        conn.close()

    return redirect("/vehicles")


@vehicles_bp.route("/export")
def export_vehicles_excel():
    """🌟 مسار تصدير سجل المركبات والأسطول إلى Excel مع دعم البحث"""
    controller = VehiclesController()
    search_query = request.args.get("q", "").strip()
    return controller.export_excel(search_query if search_query else None)