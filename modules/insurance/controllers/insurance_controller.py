import os
from flask import render_template, request, redirect, url_for, flash, send_from_directory, current_app
from modules.insurance.services.insurance_service import InsuranceService
from utils.excel_export import generate_semacom_excel

class InsuranceController:

    @staticmethod
    def index():
        tab = request.args.get('tab', 'active')
        policies = InsuranceService.get_all_policies(tab=tab)
        return render_template('insurance/views/insurance_index.html', policies=policies, active_tab=tab)

    @staticmethod
    def add_get():
        from modules.vehicles import repository as vehicles_repository
        vehicles = vehicles_repository.list_active_summaries()
        return render_template('insurance/views/insurance_add.html', vehicles=vehicles)

    @staticmethod
    def add_post():
        try:
            file_att = request.files.get('policy_attachment')
            InsuranceService.add_policy(request.form, file_att)
            flash('تم تسجيل وثيقة التأمين بنجاح', 'success')
        except Exception as e:
            flash(f'حدث خطأ أثناء تسجيل الوثيقة: {str(e)}', 'danger')
        return redirect(url_for('insurance_bp.index'))

    @staticmethod
    def expire_policy(policy_id):
        try:
            InsuranceService.expire_policy(policy_id)
            flash('تم تحويل وثيقة التأمين إلى الأرشيف (منتهية)', 'success')
        except Exception as e:
            flash(f'حدث خطأ: {str(e)}', 'danger')
        return redirect(url_for('insurance_bp.index'))

    @staticmethod
    def delete_policy(policy_id):
        try:
            InsuranceService.delete_policy(policy_id)
            flash('تم حذف سجل التأمين بنجاح', 'success')
        except Exception as e:
            flash(f'حدث خطأ أثناء الحذف: {str(e)}', 'danger')
        return redirect(url_for('insurance_bp.index'))

    @staticmethod
    def view_attachment(filename):
        """الحل النهائي السليم المعتمد على مسار الستاتيك الفعلي لتطبيق Flask داخل مجلد app"""
        base_dir = current_app.static_folder  # يشير مباشرة إلى مجلد app/static
        directory = os.path.join(base_dir, 'uploads', 'insurance')
        
        # التأكد من وجود مجلد uploads/insurance داخل app/static فقط
        if not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
            
        file_path = os.path.join(directory, filename)
        
        # إذا لم يتم العثور على الملف، يتم تنبيه المستخدم دون إعادة توجيه خاطئة تعطل النظام
        if not os.path.exists(file_path):
            return f"""
            <!DOCTYPE html>
            <html lang="ar" dir="rtl">
            <head>
                <meta charset="UTF-8">
                <title>خطأ - الملف غير موجود</title>
                <style>
                    body {{ font-family: 'Cairo', sans-serif; background-color: #f8f9fa; text-align: center; padding-top: 100px; }}
                    .alert-box {{ background: white; padding: 30px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); display: inline-block; }}
                    h3 {{ color: #dc3545; }}
                    p {{ color: #495057; }}
                    a {{ display: inline-block; margin-top: 15px; padding: 8px 20px; background: #1F4E78; color: white; text-decoration: none; border-radius: 4px; }}
                </style>
            </head>
            <body>
                <div class="alert-box">
                    <h3><i class="fa-solid fa-triangle-exclamation"></i> عذراً، الملف غير موجود</h3>
                    <p>الملف المطلوب غير متوفر على الخادم أو تم حذفه من المسار المخصص.</p>
                    <a href="javascript:window.close();">إغلاق النافذة</a>
                </div>
            </body>
            </html>
            """
            
        return send_from_directory(directory, filename)

    @staticmethod
    def export_excel():
        tab = request.args.get('tab', 'active')
        policies = InsuranceService.get_all_policies(tab=tab)
        
        headers = [
            'م', 'رقم البوليصة', 'رقم اللوحة', 'شركة التأمين', 
            'نوع التأمين', 'تاريخ البدء', 'تاريخ الانتهاء', 
            'تكلفة التأمين (ر.س)', 'الحالة'
        ]
        
        data = []
        for index, p in enumerate(policies, 1):
            row = [
                index,
                p.get('policy_number') or '-',
                p.get('vehicle_plate') or '-',
                p.get('insurance_company') or '-',
                p.get('insurance_type') or '-',
                p.get('start_date') or '-',
                p.get('end_date') or '-',
                p.get('policy_cost') or 0.0,
                p.get('status_type') or 'ساري'
            ]
            data.append(row)
            
        report_title = "وثائق التأمين السارية للمركبات والمعدات" if tab == 'active' else "وثائق التأمين المنتهية والأرشيف"
        return generate_semacom_excel(report_title, headers, data)