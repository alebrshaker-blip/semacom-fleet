from flask import flash, render_template, request, redirect, url_for
from modules.handover.services.handover_service import (
    get_active_handovers,
    get_archived_handovers,
    get_form_entities,
    save_handover_process,
    get_db_connection,
    get_driver_at_datetime
)
from utils.excel_export import generate_semacom_excel

def handover_index():
    search_q = request.args.get('q', '').strip()
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    
    active_records = get_active_handovers(search_q)
    archived_records = get_archived_handovers(search_q)
    
    # تصفية إضافية بالتاريخ للسجلات الأرشيفية إن وجدت
    if date_from:
        archived_records = [r for r in archived_records if r.get('handover_date', '') >= date_from]
    if date_to:
        archived_records = [r for r in archived_records if r.get('handover_date', '') <= date_to]
        
    return render_template('handover_index.html', 
                           active_records=active_records, 
                           archived_records=archived_records,
                           search_q=search_q,
                           date_from=date_from,
                           date_to=date_to)

def add_handover_form():
    try:
        available_vehicles, assigned_vehicles, drivers, technicians = get_form_entities()
    except Exception as e:
        flash(f"حدث خطأ أثناء تحميل بيانات نموذج العهدة: {e}", "danger")
        available_vehicles, assigned_vehicles, drivers, technicians = [], [], [], []
        
    return render_template('handover_add.html', 
                           available_vehicles=available_vehicles, 
                           assigned_vehicles=assigned_vehicles, 
                           drivers=drivers, 
                           technicians=technicians)

def save_handover():
    if request.method == 'POST':
        try:
            data = request.form.to_dict()
            save_handover_process(data)
            flash("تم تسجيل حركة العهدة وتحديث حالة المركبة بنجاح.", "success")
        except Exception as e:
            flash(f"تعذر تسجيل حركة العهدة: {e}", "danger")
        return redirect(url_for('handover.handover_index'))

def delete_handover(record_id):
    conn = get_db_connection()
    try:
        record = conn.execute(
            "SELECT vehicle_id, vehicle_info, status FROM handovers WHERE id = ?",
            (record_id,)
        ).fetchone()
        if not record:
            flash("سجل حركة العهدة المطلوب غير موجود.", "warning")
            return redirect(url_for('handover.handover_index'))

        vehicle_id = record['vehicle_id']
        if vehicle_id is None and record['vehicle_info']:
            vehicle = conn.execute(
                """SELECT id FROM vehicles
                   WHERE vehicle_code || ' - ' || plate_number = ?
                      OR vehicle_code = ? OR plate_number = ?
                   LIMIT 1""",
                (record['vehicle_info'], record['vehicle_info'], record['vehicle_info'])
            ).fetchone()
            vehicle_id = vehicle['id'] if vehicle else None

        conn.execute("DELETE FROM handovers WHERE id = ?", (record_id,))
        if record['status'] == 'نشط':
            active_handover = conn.execute(
                """SELECT id FROM handovers
                   WHERE status = 'نشط' AND (vehicle_id = ? OR vehicle_info = ?)
                   LIMIT 1""",
                (vehicle_id, record['vehicle_info'])
            ).fetchone()
            if not active_handover and vehicle_id is not None:
                conn.execute(
                    "UPDATE vehicles SET status = 'متاحة' WHERE id = ?",
                    (vehicle_id,)
                )
        conn.commit()
        flash("تم حذف سجل حركة العهدة.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"تعذر حذف سجل حركة العهدة: {e}", "danger")
    finally:
        conn.close()
    return redirect(url_for('handover.handover_index'))

# دالة تصدير الحركات النشطة وحدها (بشكل آمن 100%)
def export_active_excel():
    active_records = get_active_handovers()
    headers = ['#', 'المركبة / المعدة', 'السائق المسؤول', 'الغرض', 'القسم التابع له', 'الوصف', 'العداد', 'الوقود', 'فني كهرباء', 'فني ميكانيكا', 'تاريخ التسليم', 'الحالة']
    data = []
    for idx, r in enumerate(active_records, 1):
        # 🌟 تحويل الصف إلى قاموس عادي لتجنب خطأ sqlite3.Row نهائياً
        row = dict(r)
        data.append([
            idx,
            row.get('vehicle_info', '-'),
            row.get('driver_info', '-'),
            row.get('purpose', '-'),
            row.get('department', '-'),
            row.get('description', '-'),
            f"{row.get('odometer', 0)} كم",
            row.get('fuel_level', '-'),
            row.get('electrical_technician', '-'),
            row.get('mechanical_technician', '-'),
            row.get('handover_date', '-'),
            row.get('status', '-')
        ])
    return generate_semacom_excel("الحركات_النشطة", headers, data)

# دالة تصدير الأرشيف وحدها (بشكل آمن 100%)
def export_archive_excel():
    archived_records = get_archived_handovers()
    headers = ['#', 'نوع العملية', 'المركبة / المعدة', 'السائق', 'الغرض', 'القسم التابع له', 'الوصف', 'العداد', 'تاريخ ووقت الحركة', 'ملاحظات']
    data = []
    for idx, r in enumerate(archived_records, 1):
        # 🌟 تحويل الصف إلى قاموس عادي لتجنب خطأ sqlite3.Row نهائياً
        row = dict(r)
        data.append([
            idx,
            row.get('handover_type', '-'),
            row.get('vehicle_info', '-'),
            row.get('driver_info', '-'),
            row.get('purpose', '-'),
            row.get('department', '-'),
            row.get('description', '-'),
            f"{row.get('odometer', 0)} كم",
            row.get('handover_date', '-'),
            row.get('notes', '-') or '-'
        ])
    return generate_semacom_excel("أرشيف_حركات_الاستلام", headers, data)