from flask import flash, render_template, request, redirect, url_for
from modules.handover.services.handover_service import (
    get_active_handovers,
    get_archived_handovers,
    get_pending_handovers,
    get_form_entities,
    save_handover_process,
    delete_archived_handover_record,
    get_driver_at_datetime
)
from sqlalchemy.exc import SQLAlchemyError
from utils.excel_export import generate_semacom_excel

def handover_index():
    search_q = request.args.get('q', '').strip()
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    
    active_records = get_active_handovers(search_q)
    pending_records = get_pending_handovers(search_q)
    archived_records = [dict(record) for record in get_archived_handovers(search_q)]
    
    # تصفية إضافية بالتاريخ للسجلات الأرشيفية إن وجدت
    if date_from:
        archived_records = [r for r in archived_records if r.get('handover_date', '') >= date_from]
    if date_to:
        archived_records = [r for r in archived_records if r.get('handover_date', '') <= date_to]
        
    return render_template('handover_index.html', 
                           active_records=active_records, 
                           pending_records=pending_records,
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

def delete_archived_handover(record_id):
    try:
        outcome = delete_archived_handover_record(record_id)
    except SQLAlchemyError as e:
        flash(f"تعذر حذف سجل الحركة المؤرشفة: {e}", "danger")
        return redirect(url_for('handover.handover_index'))
    if outcome == 'missing':
        flash("سجل حركة العهدة المطلوب غير موجود.", "warning")
    elif outcome == 'not_archived':
        flash("يمكن حذف الحركات المؤرشفة فقط.", "warning")
    else:
        flash("تم حذف سجل الحركة المؤرشفة.", "success")
    return redirect(url_for('handover.handover_index'))

# دالة تصدير الحركات النشطة وحدها (بشكل آمن 100%)
def export_active_excel():
    active_records = get_active_handovers()
    headers = ['#', 'المركبة / المعدة', 'السائق المسؤول', 'الغرض', 'القسم التابع له', 'الوصف', 'العداد', 'الوقود', 'فني كهرباء', 'فني ميكانيكا', 'تاريخ التسليم', 'الحالة']
    data = []
    for idx, r in enumerate(active_records, 1):
        # 🌟 تحويل الصف إلى قاموس عادي لتجنب خطأ dbapi.Row نهائياً
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
        # 🌟 تحويل الصف إلى قاموس عادي لتجنب خطأ dbapi.Row نهائياً
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