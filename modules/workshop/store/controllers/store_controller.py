from flask import render_template, request, redirect, url_for, flash
from modules.workshop.store.services.store_service import StoreService
from utils.excel_export import generate_semacom_excel

class StoreController:

    @staticmethod
    def index():
        """عرض صفحة المستودع الرئيسية وقائمة الأصناف مع رصد الأصناف المنخفضة"""
        try:
            items = StoreService.get_all_items()
            # تحويل الأصناف لقواميس لسهولة العرض في الواجهة
            items_dict = [item.to_dict() for item in items]
            return render_template('store_index.html', items=items_dict)
        except Exception as e:
            flash(f"حدث خطأ أثناء تحميل بيانات المستودع: {str(e)}", "danger")
            return render_template('store_index.html', items=[])

    @staticmethod
    def add_item():
        """معالجة عملية إضافة صنف جديد للمستودع (عرض النموذج واستقبال بيانات POST)"""
        import math

        if request.method == 'POST':
            item_code = request.form.get('item_code', '').strip()
            name = request.form.get('name', '').strip()
            category = request.form.get('category', '').strip()
            unit = request.form.get('unit', 'قطعة').strip()
            
            try:
                quantity = int(request.form.get('quantity', 0) or 0)
            except ValueError:
                flash("أدخل كمية صحيحة غير سالبة.", "warning")
                return render_template('store_add.html')
            if quantity < 0:
                flash("لا يمكن أن تكون كمية الصنف سالبة.", "warning")
                return render_template('store_add.html')

            try:
                min_limit = int(request.form.get('min_limit', 5) or 5)
            except ValueError:
                flash("أدخل حدًا أدنى صحيحًا غير سالب للمخزون.", "warning")
                return render_template('store_add.html')
            if min_limit < 0:
                flash("لا يمكن أن يكون حد المخزون الأدنى سالبًا.", "warning")
                return render_template('store_add.html')

            location = request.form.get('location', '').strip()
            
            try:
                unit_price = float(request.form.get('unit_price', 0.0))
            except ValueError:
                flash("أدخل سعر وحدة صحيحًا.", "warning")
                return render_template('store_add.html')
            if not math.isfinite(unit_price) or unit_price < 0:
                flash("يجب أن يكون سعر الوحدة رقمًا موجبًا أو صفرًا.", "warning")
                return render_template('store_add.html')

            notes = request.form.get('notes', '').strip()

            # التحقق من الحقول الأساسية
            if not item_code or not name or not category:
                flash("الرجاء تعبئة الحقول الإجبارية (كود الصنف، الاسم، التصنيف).", "warning")
                return render_template('store_add.html')

            # استدعاء طبقة الخدمة للحفظ
            success, message = StoreService.add_item(
                item_code=item_code,
                name=name,
                category=category,
                unit=unit,
                quantity=quantity,
                min_limit=min_limit,
                location=location,
                unit_price=unit_price,
                notes=notes
            )

            if success:
                flash(message, "success")
                return redirect(url_for('workshop.store_bp.index'))
            else:
                flash(message, "danger")
                return render_template('store_add.html')

        return render_template('store_add.html')

    @staticmethod
    def delete_item(item_id):
        success, message = StoreService.delete_item(item_id)
        flash(message, 'success' if success else 'danger')
        return redirect(url_for('workshop.store_bp.index'))

    @staticmethod
    def export_excel():
        items = StoreService.get_all_items()
        headers = [
            'كود الصنف', 'اسم القطعة / الأداة', 'التصنيف', 'الوحدة',
            'الكمية المتاحة', 'الحد الأدنى', 'الموقع', 'سعر الوحدة', 'ملاحظات', 'حالة المخزون',
        ]
        data = [
            [
                item.item_code, item.name, item.category, item.unit,
                item.quantity, item.min_limit, item.location or '-',
                item.unit_price, item.notes or '-',
                'منخفض' if item.quantity <= item.min_limit else 'متوفر',
            ]
            for item in items
        ]
        return generate_semacom_excel('أصناف المستودع', headers, data)