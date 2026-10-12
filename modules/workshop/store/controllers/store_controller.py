from flask import render_template, request, redirect, url_for, flash
from modules.workshop.store.services.store_service import StoreService

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
        if request.method == 'POST':
            item_code = request.form.get('item_code', '').strip()
            name = request.form.get('name', '').strip()
            category = request.form.get('category', '').strip()
            unit = request.form.get('unit', 'قطعة').strip()
            
            try:
                quantity = int(request.form.get('quantity', 0))
            except ValueError:
                quantity = 0

            try:
                min_limit = int(request.form.get('min_limit', 5))
            except ValueError:
                min_limit = 5

            location = request.form.get('location', '').strip()
            
            try:
                unit_price = float(request.form.get('unit_price', 0.0))
            except ValueError:
                unit_price = 0.0

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