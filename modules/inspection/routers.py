from flask import Blueprint
from modules.inspection.controllers.inspection_controller import InspectionController

# إنشاء البلوبرنت مع تحديد مجلد العروض (views) محلياً داخل الموديول
inspection_bp = Blueprint(
    'inspection_bp',
    __name__,
    template_folder='views'
)

# تسجيل المسارات (Routes) الخاصة بالفحص الدوري
inspection_bp.add_url_rule('/', 'index', InspectionController.index, methods=['GET'])
inspection_bp.add_url_rule('/add', 'add_get', InspectionController.add_get, methods=['GET'])
inspection_bp.add_url_rule('/add', 'add_post', InspectionController.add_post, methods=['POST'])
inspection_bp.add_url_rule('/expire/<int:inspection_id>', 'expire', InspectionController.expire_inspection, methods=['POST'])
inspection_bp.add_url_rule('/delete/<int:inspection_id>', 'delete', InspectionController.delete_inspection, methods=['POST'])
inspection_bp.add_url_rule('/view-attachment/<filename>', 'view_attachment', InspectionController.view_attachment, methods=['GET'])
inspection_bp.add_url_rule('/export-excel', 'export_excel', InspectionController.export_excel, methods=['GET'])