from datetime import datetime
from flask import jsonify, render_template, request, redirect, url_for, flash
from modules.violations.services.violations_service import ViolationsService
from modules.vehicles import repository as vehicles_repository
from utils.excel_export import generate_semacom_excel  # استيراد الدالة الموحدة الصحيحة من مجلد utils
from modules.handover.services.handover_service import get_driver_at_datetime

class ViolationsController:
    
    @staticmethod
    def index():
        tab = request.args.get('tab', 'active')
        violations = ViolationsService.get_all_violations(tab)
        return render_template('violation_index.html', violations=violations, active_tab=tab)

    @staticmethod
    def add():
        if request.method == 'POST':
            file_att = request.files.get('violation_attachment')
            ViolationsService.add_violation(request.form, file_att)
            flash('تم تسجيل المخالفة واختيار السائق بنجاح', 'success')
            return redirect(url_for('violations.index'))
        vehicles = vehicles_repository.list_active_summaries()
        return render_template('violation_add.html', vehicles=vehicles)

    @staticmethod
    def driver_at_datetime():
        driver = get_driver_at_datetime(
            request.args.get('vehicle_plate'), request.args.get('event_datetime')
        )
        return jsonify({"driver_name": driver})

    @staticmethod
    def close(violation_id):
        if request.method == 'POST':
            payment_att = request.files.get('payment_attachment')
            ViolationsService.close_violation(violation_id, request.form, payment_att)
            flash('تم تقفيل وتسوية المخالفة بنجاح', 'success')
        return redirect(url_for('violations.index'))

    @staticmethod
    def delete(violation_id):
        try:
            ViolationsService.delete_violation(violation_id)
            flash('تم حذف المخالفة بنجاح', 'success')
        except Exception as e:
            flash(f'حدث خطأ أثناء الحذف: {str(e)}', 'danger')
        return redirect(url_for('violations.index'))

    @staticmethod
    def export_excel():
        tab = request.args.get('tab', 'active')
        violations = ViolationsService.get_all_violations(tab)
        
        headers = [
            "رقم المخالفة", 
            "المركبة", 
            "السائق", 
            "نوع المخالفة", 
            "جهة الإصدار", 
            "الموقع", 
            "التاريخ والوقت", 
            "قيمة الغرامة", 
            "الحالة", 
            "الوصف"
        ]
        
        data = []
        for v in violations:
            data.append([
                v.get('violation_number'),
                v.get('vehicle_plate'),
                v.get('driver_name'),
                v.get('violation_type'),
                v.get('issuer'),
                v.get('location'),
                v.get('violation_datetime'),
                v.get('fine_amount'),
                v.get('status_type'),
                v.get('description')
            ])
            
        title = "سجل المخالفات المرورية النشطة" if tab == 'active' else "سجل المخالفات المؤرشفة والمسددة"
        
        return generate_semacom_excel(title, headers, data)