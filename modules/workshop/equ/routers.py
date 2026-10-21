from flask import Blueprint
from modules.workshop.equ.controllers.equ_controller import EquController

# تعريف البلوبرنت الخاص بأصول الورشة
equ_bp = Blueprint('equ_bp', __name__, template_folder='views')

equ_bp.add_url_rule('/', view_func=EquController.index, methods=['GET'])
equ_bp.add_url_rule('/add', view_func=EquController.add_item, methods=['GET', 'POST'])
equ_bp.add_url_rule(
	'/delete/<int:asset_id>', view_func=EquController.delete_item, methods=['POST']
)
equ_bp.add_url_rule('/export/excel', view_func=EquController.export_excel, methods=['GET'])