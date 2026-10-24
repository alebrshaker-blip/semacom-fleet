from flask import jsonify, render_template, request, redirect, url_for, flash
from modules.accidents.services.accidents_service import AccidentsService
from modules.handover.services.handover_service import get_driver_at_datetime
from utils.excel_export import generate_semacom_excel

class AccidentsController:

    @staticmethod
    def index():
        tab = request.args.get('tab', 'active')
        accidents = AccidentsService.get_all_accidents(tab=tab)
        return render_template('accidents_index.html', accidents=accidents, active_tab=tab)

    @staticmethod
    def add_get():
        # استدعاء المركبات وربط السائق بتاريخ العهدة عند اختيار المركبة والتاريخ
        from modules.vehicles import repository as vehicles_repository
        vehicles = vehicles_repository.list_active_summaries()
        return render_template('accidents_add.html', vehicles=vehicles)

    @staticmethod
    def driver_at_datetime():
        driver = get_driver_at_datetime(
            request.args.get('vehicle_plate'), request.args.get('event_datetime')
        )
        return jsonify({"driver_name": driver})

    @staticmethod
    def add_post():
        try:
            file_att = request.files.get('accident_attachment')
            file_att_2 = request.files.get('accident_attachment_2')
            AccidentsService.add_accident(request.form, file_att, file_att_2)
            flash('تم تسجيل الحادث بنجاح', 'success')
        except Exception as e:
            flash(f'حدث خطأ أثناء تسجيل الحادث: {str(e)}', 'danger')
        return redirect(url_for('accidents_bp.index'))

    @staticmethod
    def close_accident(accident_id):
        try:
            payment_att = request.files.get('payment_attachment')
            AccidentsService.close_accident(accident_id, request.form, payment_att)
            flash('تم تقفيل وتسوية الحادث بنجاح وتوجيهه للأرشيف', 'success')
        except Exception as e:
            flash(f'حدث خطأ أثناء تقفيل الحادث: {str(e)}', 'danger')
        return redirect(url_for('accidents_bp.index'))

    @staticmethod
    def delete_accident(accident_id):
        try:
            AccidentsService.delete_accident(accident_id)
            flash('تم حذف سجل الحادث بنجاح', 'success')
        except Exception as e:
            flash(f'حدث خطأ أثناء حذف السجل: {str(e)}', 'danger')
        return redirect(url_for('accidents_bp.index'))

    @staticmethod
    def export_excel():
        tab = request.args.get('tab', 'active')
        accidents = AccidentsService.get_all_accidents(tab=tab)
        
        # عناوين أعمدة التقرير الموحدة
        headers = [
            'م', 'رقم الحادث', 'رقم اللوحة', 'اسم السائق', 
            'نوع الحادث', 'جهة البلاغ/المرور', 'الموقع',
            'تاريخ ووقت الحادث', 'تكلفة الإصلاح (ر.س)', 'الحالة', 'الوصف',
            'صورة الحادث الأولى', 'صورة الحادث الثانية', 'سبب التقفيل'
        ]
        
        # تجهيز البيانات كقوائم (Lists) لتتوافق مع الدالة المركزية
        data = []
        for index, acc in enumerate(accidents, 1):
            row = [
                index,
                acc.get('accident_number') or '-',
                acc.get('vehicle_plate') or '-',
                acc.get('driver_name') or '-',
                acc.get('accident_type') or '-',
                acc.get('issuer') or '-',
                acc.get('location') or '-',
                acc.get('accident_datetime') or '-',
                acc.get('repair_cost') or 0.0,
                acc.get('status_type') or '-',
                acc.get('description') or '-',
                acc.get('accident_attachment') or '-',
                acc.get('accident_attachment_2') or '-',
                acc.get('closure_reason') or '-'
            ]
            data.append(row)
            
        # عنوان التقرير الذي سيظهر في الترويسة العليا والملف
        report_title = "الحوادث المرورية السارية" if tab == 'active' else "الحوادث المرورية المؤرشفة"
        
        # استدعاء الدالة الموحدة من utils لإضافة الترويسة، الشعار، وتنسيق الجدول بالكامل
        return generate_semacom_excel(report_title, headers, data)