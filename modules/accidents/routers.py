from flask import Blueprint
from modules.accidents.controllers.accidents_controller import AccidentsController

accidents_bp = Blueprint('accidents_bp', __name__, url_prefix='/accidents')

@accidents_bp.route('/', methods=['GET'])
def index():
    return AccidentsController.index()

@accidents_bp.route('/add', methods=['GET'])
def add_get():
    return AccidentsController.add_get()

@accidents_bp.route('/add', methods=['POST'])
def add_post():
    return AccidentsController.add_post()

@accidents_bp.route('/driver-at-time', methods=['GET'])
def driver_at_datetime():
    return AccidentsController.driver_at_datetime()

@accidents_bp.route('/close/<int:accident_id>', methods=['POST'])
def close_accident(accident_id):
    return AccidentsController.close_accident(accident_id)

@accidents_bp.route('/delete/<int:accident_id>', methods=['GET'])
def delete_accident(accident_id):
    return AccidentsController.delete_accident(accident_id)

@accidents_bp.route('/export', methods=['GET'])
def export_excel():
    return AccidentsController.export_excel()