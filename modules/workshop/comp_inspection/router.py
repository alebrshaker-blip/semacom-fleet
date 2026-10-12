from flask import Blueprint
from .comp_inspection_controller import CompInspectionController

comp_inspection_bp = Blueprint('comp_inspection', __name__, template_folder='views')

@comp_inspection_bp.route('/', methods=['GET'])
def list():
    return CompInspectionController.list_inspections()

@comp_inspection_bp.route('/add', methods=['GET', 'POST'])
def add():
    return CompInspectionController.add_inspection()

@comp_inspection_bp.route('/print/<int:id>', methods=['GET'])
def print_report(id):
    return CompInspectionController.print_inspection(id)