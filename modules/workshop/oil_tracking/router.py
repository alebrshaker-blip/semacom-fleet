from flask import Blueprint
from .oil_tracking_controller import OilTrackingController

oil_tracking_bp = Blueprint('oil_tracking', __name__, template_folder='views')

@oil_tracking_bp.route('/', methods=['GET'])
def list():
    return OilTrackingController.list_records()

@oil_tracking_bp.route('/add', methods=['GET', 'POST'])
def add():
    return OilTrackingController.add_record()

@oil_tracking_bp.route('/delete/<int:id>', methods=['POST'])
def delete(id):
    return OilTrackingController.delete_record(id)

@oil_tracking_bp.route('/print/<int:id>', methods=['GET'])
def print_report(id):
    return OilTrackingController.print_report(id)

# مسار التصدير إلى إكسل في الخادم
@oil_tracking_bp.route('/export', methods=['GET'])
def export_excel():
    return OilTrackingController.export_excel()