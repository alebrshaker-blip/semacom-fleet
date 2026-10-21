import json
from core import database as dbapi
from pathlib import Path
from modules.reports.models.reports_model import ReportsModel
from modules.reports.services.reports_service import ReportsService
from datetime import datetime

class ReportsController:
    """المتحكم الرئيسي لموديول التقارير - يربط الراوتر بالنماذج والخدمات"""

    def __init__(self):
        self.model = ReportsModel()
        self.service = ReportsService()

    def get_active_templates(self):
        """جلب قائمة قوالب التقارير المتاحة والمفعلة"""
        try:
            return self.model.get_active_templates()
        except Exception as e:
            print(f"خطأ أثناء جلب القوالب: {e}")
            return []

    def generate_report_context(self, template_key: str, params: dict) -> dict:
        """تجميع كافة البيانات وتحديد مسار القالب بناءً على القالب المختار"""
        # جلب تفاصيل القالب من قاعدة البيانات
        template_info = self.model.get_template_by_key(template_key)
        
        # تجميع البيانات الخاصة بالتقرير بناءً على نوع القالب
        context_data = self.service.fetch_report_data_by_type(template_key, params)

        template_path = template_info.get('template_path', 'vehicle_report.html') if template_info else 'vehicle_report.html'

        return {
            "template_path": template_path,
            "context": context_data
        }

    def create_and_save_report(self, template_key: str, params: dict) -> dict:
        """توليد التقرير وإنشاء كود الـ QR ورقم المستند وحفظهما"""
        return self.service.process_and_archive_report(template_key, params)

    def get_report_archive(self):
        """استرجاع سجل وأرشيف التقارير المصدورة سابقاً"""
        try:
            return self.model.get_all_generated_reports()
        except Exception as e:
            print(f"خطأ أثناء جلب أرشيف التقارير: {e}")
            return []

        from datetime import datetime
from flask import render_template, request, redirect, url_for, flash

class ReportsController:
    # ... الدوال الأخرى للتقارير ...

    @staticmethod
    def workshop_request_form():
        """عرض نموذج مذكرة طلبات الورشة"""
        # يمكن جلب بيانات المركبات والفنيين لتعبئة القوائم المنسدلة
        doc_number = f"REQ-WS-{datetime.now().strftime('%Y%m%d%H%M')}"
        current_date = datetime.now().strftime('%Y-%m-%d')
        
        return render_template(
            'workshop_request_form.html',
            document_number=doc_number,
            current_date=current_date,
            active_tab='reports'
        )

    @staticmethod
    def save_workshop_request():
        """حفظ مذكرة طلبات الورشة"""
        if request.method == 'POST':
            # استقبال بيانات الفورم وحفظها في قاعدة البيانات
            # form_data = request.form
            flash('تم حفظ مذكرة طلبات الورشة بنجاح', 'success')
            return redirect(url_for('reports.workshop_request_form'))

    @staticmethod
    def get_active_templates():
        """إرجاع القوالب أو التقارير النشطة"""
        # يمكنك إرجاع قائمة فارغة أو القوالب المطلوبة حسب هيكل مشروعك
        return []

    @staticmethod
    def workshop_request_form():
        """عرض وحفظ نموذج مذكرة طلبات الورشة"""
        if request.method == 'POST':
            # يمكنك إضافة منطق حفظ البيانات هنا لاحقاً
            flash('تم حفظ مذكرة طلبات الورشة بنجاح', 'success')
            return redirect(url_for('reports.workshop_request_form'))

        doc_number = f"REQ-WS-{datetime.now().strftime('%Y%m%d%H%M')}"
        current_date = datetime.now().strftime('%Y-%m-%d')
        
        return render_template(
            'workshop_request_form.html',
            document_number=doc_number,
            current_date=current_date,
            active_tab='reports'
        )