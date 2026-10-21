from flask import render_template, request, redirect, url_for, flash
from modules.workshop.equ.services.equ_service import EquService
from utils.excel_export import generate_semacom_excel

class EquController:

    @staticmethod
    def index():
        """عرض قائمة أصول وعدّ الورشة"""
        try:
            assets = EquService.get_all_assets()
            assets_dict = [asset.to_dict() for asset in assets]
            return render_template('equ_index.html', assets=assets_dict)
        except Exception as e:
            flash(f"حدث خطأ أثناء تحميل أصول الورشة: {str(e)}", "danger")
            return render_template('equ_index.html', assets=[])

    @staticmethod
    def add_item():
        """معالجة إضافة أصل جديد"""
        if request.method == 'POST':
            asset_code = request.form.get('asset_code', '').strip()
            name = request.form.get('name', '').strip()
            category = request.form.get('category', '').strip()
            status = request.form.get('status', 'متاح').strip()
            location = request.form.get('location', '').strip()
            purchase_date = request.form.get('purchase_date', '').strip()
            condition_status = request.form.get('condition_status', 'جيد').strip()
            notes = request.form.get('notes', '').strip()

            if not asset_code or not name or not category:
                flash("الرجاء تعبئة الحقول الإجبارية (كود الأصل، اسم العدة، التصنيف).", "warning")
                return render_template('equ_add.html')

            success, message = EquService.add_asset(
                asset_code=asset_code,
                name=name,
                category=category,
                status=status,
                location=location,
                purchase_date=purchase_date,
                condition_status=condition_status,
                notes=notes
            )

            if success:
                flash(message, "success")
                return redirect(url_for('workshop.equ_bp.index'))
            else:
                flash(message, "danger")
                return render_template('equ_add.html')

        return render_template('equ_add.html')

    @staticmethod
    def delete_item(asset_id):
        success, message = EquService.delete_asset(asset_id)
        flash(message, 'success' if success else 'danger')
        return redirect(url_for('workshop.equ_bp.index'))

    @staticmethod
    def export_excel():
        assets = EquService.get_all_assets()
        headers = [
            'كود الأصل', 'اسم المعدة / العدة', 'التصنيف', 'الحالة التشغيلية',
            'الموقع داخل الورشة', 'تاريخ الشراء', 'الحالة الفنية', 'ملاحظات',
        ]
        data = [
            [
                asset.asset_code, asset.name, asset.category, asset.status,
                asset.location or '-', asset.purchase_date or '-',
                asset.condition_status or '-', asset.notes or '-',
            ]
            for asset in assets
        ]
        return generate_semacom_excel('أصول ومعدات الورشة', headers, data)