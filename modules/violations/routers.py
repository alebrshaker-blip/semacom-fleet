from flask import Blueprint
from modules.violations.controllers.violations_controller import ViolationsController

# تحديد مسار القوالب (template_folder) ليشير إلى مجلد views داخل الموديول
violations_bp = Blueprint(
    'violations', 
    __name__, 
    url_prefix='/violations', 
    template_folder='views'
)

@violations_bp.route('/')
def index():
    return ViolationsController.index()

@violations_bp.route('/add', methods=['GET', 'POST'])
def add():
    return ViolationsController.add()

@violations_bp.route('/driver-at-time', methods=['GET'])
def driver_at_datetime():
    return ViolationsController.driver_at_datetime()

@violations_bp.route('/close/<int:violation_id>', methods=['POST'])
def close(violation_id):
    return ViolationsController.close(violation_id)

@violations_bp.route('/delete/<int:violation_id>', methods=['POST', 'GET'])
def delete(violation_id):
    return ViolationsController.delete(violation_id)

@violations_bp.route('/export')
def export():
    return ViolationsController.export_excel()