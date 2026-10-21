import os
from flask import render_template, request, redirect, url_for, flash, send_from_directory
from modules.inspection.services.inspection_service import InspectionService
from modules.inspection.models.inspection_model import InspectionModel
from utils.excel_export import generate_semacom_excel
from modules.vehicles import repository as vehicles_repository

class InspectionController:

    @staticmethod
    def get_vehicles_list():
        """جلب قائمة لوحات المركبات من جدول المركبات الرئيسي لربطها بالفحص"""
        try:
            return [
                {'plate_number': v['plate_number'], 'vehicle_type': v.get('vehicle_type'), 'model': v.get('model')}
                for v in vehicles_repository.list_active()
            ]
        except Exception:
            return []

    @classmethod
    def index(cls):
        status_type = request.args.get('status', 'active')
        inspections = InspectionService.get_all_inspections(status_type)
        return render_template('inspection_index.html', inspections=inspections, current_status=status_type)

    @classmethod
    def add_get(cls):
        vehicles = cls.get_vehicles_list()
        return render_template('inspection_add.html', vehicles=vehicles)

    @classmethod
    def add_post(cls):
        try:
            form_data = request.form
            file_attachment = request.files.get('attachment')
            
            InspectionService.create_inspection(form_data, file_attachment)
            flash('تم إضافة سجل الفحص الدوري بنجاح', 'success')
            return redirect(url_for('inspection_bp.index'))
        except Exception as e:
            flash(f'حدث خطأ أثناء الإضافة: {str(e)}', 'danger')
            return redirect(url_for('inspection_bp.add_get'))

    @classmethod
    def expire_inspection(cls, inspection_id):
        try:
            InspectionService.mark_as_expired(inspection_id)
            flash('تم تحديث حالة الفحص إلى منتهي', 'info')
        except Exception as e:
            flash(f'حدث خطأ: {str(e)}', 'danger')
        return redirect(url_for('inspection_bp.index'))

    @classmethod
    def delete_inspection(cls, inspection_id):
        try:
            InspectionService.remove_inspection(inspection_id)
            flash('تم حذف سجل الفحص بنجاح', 'success')
        except Exception as e:
            flash(f'حدث خطأ أثناء الحذف: {str(e)}', 'danger')
        return redirect(url_for('inspection_bp.index'))

    @classmethod
    def view_attachment(cls, filename):
        upload_dir = InspectionService.get_upload_folder()
        return send_from_directory(upload_dir, filename)

    @classmethod
    def export_excel(cls):
        try:
            inspections = InspectionService.get_all_inspections('active')
            headers = [
                'المسلسل', 'رقم اللوحة', 'تاريخ الفحص', 'تاريخ الانتهاء',
                'نتيجة الفحص', 'حالة الفحص', 'اسم الفاحص', 'التكلفة (ر.س)'
            ]
            
            data = []
            for idx, item in enumerate(inspections, 1):
                data.append([
                    idx,
                    item.get('vehicle_plate', '-'),
                    item.get('inspection_date', '-'),
                    item.get('expiry_date', '-'),
                    item.get('result_status', '-'),
                    item.get('status_type', '-'),
                    item.get('inspection_center', '-'),
                    item.get('inspection_cost') or 0
                ])
            
            title = "الفحص_الدوري_للمركبات"
            return generate_semacom_excel(title, headers, data)
            
        except Exception as e:
            flash(f'حدث خطأ أثناء تصدير ملف الإكسل: {str(e)}', 'danger')
            return redirect(url_for('inspection_bp.index'))