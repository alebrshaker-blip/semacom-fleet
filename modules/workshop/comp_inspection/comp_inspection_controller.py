from flask import render_template, request, redirect, url_for, flash
from datetime import datetime
from itertools import zip_longest
from .comp_inspection_service import CompInspectionService

class CompInspectionController:
    @staticmethod
    def list_inspections():
        inspections = CompInspectionService.get_all_inspections()
        return render_template('comp_inspection_list.html', inspections=inspections, active_tab='comp_inspection')

    @staticmethod
    def add_inspection():
        if request.method == 'POST':
            form_data = request.form
            vehicle_plate = (form_data.get('vehicle_plate') or '').strip()
            if not vehicle_plate:
                flash('يرجى اختيار المركبة المراد إجراء الفحص عليها.', 'danger')
                return redirect(url_for('workshop.comp_inspection.add'))

            inspector_ids = list(dict.fromkeys(
                member_id.strip() for member_id in request.form.getlist('inspector_ids')
                if member_id and member_id.strip()
            ))
            if len(inspector_ids) < 2:
                flash('يرجى اختيار فنيين اثنين على الأقل لإجراء الفحص.', 'danger')
                return redirect(url_for('workshop.comp_inspection.add'))

            categories = request.form.getlist('category[]')
            item_names = request.form.getlist('item_name[]')
            statuses = request.form.getlist('status[]')
            item_notes = request.form.getlist('item_notes[]')

            items_data = []
            for category, item_name, status, item_note in zip_longest(categories, item_names, statuses, item_notes, fillvalue=''):
                category = (category or '').strip()
                item_name = (item_name or '').strip()
                status = (status or '').strip()
                item_note = (item_note or '').strip()
                if category or item_name or status or item_note:
                    items_data.append((category, item_name, status, item_note))

            if not items_data:
                flash('يرجى إضافة بند واحد على الأقل للفحص الشامل.', 'danger')
                return redirect(url_for('workshop.comp_inspection.add'))

            try:
                form_data = form_data.to_dict()
                form_data['vehicle_plate'] = vehicle_plate
                CompInspectionService.create_inspection(form_data, items_data, inspector_ids)
                flash('تم حفظ واعتماد الفحص الشامل بنجاح', 'success')
                return redirect(url_for('workshop.comp_inspection.list'))
            except Exception as error:
                flash(f'تعذر حفظ الفحص الشامل: {error}', 'danger')
                return redirect(url_for('workshop.comp_inspection.add'))

        # جلب القوائم المنسدلة من قاعدة البيانات
        vehicles = CompInspectionService.get_all_vehicles()
        team_members = CompInspectionService.get_all_team_members()

        return render_template(
            'comp_inspection_add.html', 
            vehicles=vehicles, 
            team_members=team_members, 
            latest_oil_mileages=CompInspectionService.get_latest_oil_mileages(),
            active_tab='comp_inspection'
        )

    @staticmethod
    def delete_inspection(id):
        try:
            if CompInspectionService.delete_inspection(id):
                flash('تم حذف سجل الفحص الشامل بنجاح.', 'success')
            else:
                flash('سجل الفحص الشامل المطلوب غير موجود.', 'warning')
        except Exception as error:
            flash(f'تعذر حذف سجل الفحص الشامل: {error}', 'danger')
        return redirect(url_for('workshop.comp_inspection.list'))

    @staticmethod
    def print_inspection(id):
        inspection, items = CompInspectionService.get_inspection_by_id(id)
        if not inspection:
            return "سجل الفحص الشامل غير موجود", 404

        return render_template(
            'comp_inspection_print.html',
            inspection=inspection,
            items=items,
            document_number=inspection['document_number'],
            report_date_gregorian=datetime.now().strftime('%Y/%m/%d'),
            orientation='landscape'
        )