from flask import render_template, request, redirect, url_for, flash
from datetime import datetime
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
            categories = request.form.getlist('category[]')
            item_names = request.form.getlist('item_name[]')
            statuses = request.form.getlist('status[]')
            item_notes = request.form.getlist('item_notes[]')
            
            items_data = list(zip(categories, item_names, statuses, item_notes))
            
            CompInspectionService.create_inspection(form_data, items_data)
            flash('تم حفظ واعتماد الفحص الشامل بنجاح', 'success')
            return redirect(url_for('workshop.comp_inspection.list'))

        # جلب القوائم المنسدلة من قاعدة البيانات
        vehicles = CompInspectionService.get_all_vehicles()
        team_members = CompInspectionService.get_all_team_members()

        return render_template(
            'comp_inspection_add.html', 
            vehicles=vehicles, 
            team_members=team_members, 
            active_tab='comp_inspection'
        )

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
            report_date_gregorian=datetime.now().strftime('%Y/%m/%d')
        )