from flask import Blueprint
from modules.handover.controllers.handover_controller import (
    handover_index,
    add_handover_form,
    save_handover,
    delete_handover,
    export_active_excel,  # دالة تصدير الحركات النشطة
    export_archive_excel  # دالة تصدير الأرشيف
)

# تحديد مجلد القوالب template_folder='views' ليتمكن Flask من إيجاد الملفات بدقة
handover_bp = Blueprint('handover', __name__, url_prefix='/handover', template_folder='views')

# ربط المسارات بالدوال الصحيحة في المتحكم
handover_bp.add_url_rule('/', view_func=handover_index, methods=['GET'])
handover_bp.add_url_rule('/add', view_func=add_handover_form, methods=['GET'])
handover_bp.add_url_rule('/save', view_func=save_handover, methods=['POST'])
handover_bp.add_url_rule('/delete/<int:record_id>', view_func=delete_handover, methods=['POST', 'GET'])

# مسارات التصدير المستقلة للجدولين
handover_bp.add_url_rule('/export/active', view_func=export_active_excel, methods=['GET'])
handover_bp.add_url_rule('/export/archive', view_func=export_archive_excel, methods=['GET'])