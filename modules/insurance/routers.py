from flask import Blueprint
from modules.insurance.controllers.insurance_controller import InsuranceController

insurance_bp = Blueprint(
    'insurance_bp', 
    __name__, 
    template_folder='views',
    url_prefix='/insurance'
)

insurance_bp.route('/', methods=['GET'])(InsuranceController.index)
insurance_bp.route('/add', methods=['GET'])(InsuranceController.add_get)
insurance_bp.route('/add', methods=['POST'])(InsuranceController.add_post)
insurance_bp.route('/expire/<int:policy_id>', methods=['POST'])(InsuranceController.expire_policy)
insurance_bp.route('/delete/<int:policy_id>', methods=['POST'])(InsuranceController.delete_policy)
insurance_bp.route('/export', methods=['GET'])(InsuranceController.export_excel)

# المسار الآمن الجديد لعرض وتحميل المرفقات مع التحقق التلقائي وإنشاء المجلدات عند الحاجة
insurance_bp.route('/view-attachment/<path:filename>', methods=['GET'])(InsuranceController.view_attachment)