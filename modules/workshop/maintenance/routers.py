from flask import Blueprint
from modules.workshop.maintenance.controller.maintenance_controller import MaintenanceController
# تعريف الـ Blueprint لموديول الصيانة
maintenance_bp = Blueprint(
    'maintenance',
    __name__,
    template_folder='../views'
)


@maintenance_bp.route('/')
def maintenance_index():
    """الصفحة الرئيسية لموديول الصيانة"""
    return MaintenanceController.get_index()


@maintenance_bp.route('/all')
def maintenance_all():
    """عرض موحد لجميع أنواع أوامر الصيانة المفتوحة والمغلقة"""
    return MaintenanceController.get_all_list()


@maintenance_bp.route('/list/<string:m_type>')
def maintenance_list(m_type):
    """عرض قائمة أوامر الصيانة حسب النوع"""
    return MaintenanceController.get_list(m_type)


@maintenance_bp.route('/add/<string:m_type>', methods=['GET', 'POST'])
def maintenance_add(m_type):
    """إضافة أمر صيانة جديد"""
    return MaintenanceController.add_order(m_type)


@maintenance_bp.route('/close/<int:order_id>', methods=['GET', 'POST'])
def maintenance_close(order_id):
    """إقفال أمر الصيانة ونقله للأرشيف"""
    return MaintenanceController.close_order(order_id)


@maintenance_bp.route('/view/<int:order_id>')
def maintenance_view(order_id):
    """عرض تفاصيل أمر الصيانة"""
    return MaintenanceController.view_order(order_id)


@maintenance_bp.route('/delete/<int:order_id>', methods=['POST'])
def maintenance_delete(order_id):
    """حذف أمر الصيانة"""
    return MaintenanceController.delete_order(order_id)


@maintenance_bp.route('/export/<string:m_type>')
def maintenance_export(m_type):
    """تصدير بيانات الصيانة إلى Excel"""
    return MaintenanceController.export_excel(m_type)
