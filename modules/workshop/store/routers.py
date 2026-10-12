from flask import Blueprint
from modules.workshop.store.controllers.store_controller import StoreController

# تعريف الـ Blueprint باسم 'store_bp' ليتطابق مع الـ url_for في القوالب
store_bp = Blueprint('store_bp', __name__, template_folder='views')

# مسار عرض قائمة الأصناف الرئيسية في المستودع
store_bp.add_url_rule('/', view_func=StoreController.index, methods=['GET'])

# مسار إضافة صنف جديد (يدعم عرض النموذج GET واستقبال البيانات POST)
store_bp.add_url_rule('/add', view_func=StoreController.add_item, methods=['GET', 'POST'])