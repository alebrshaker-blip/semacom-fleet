import sys
import os
from pathlib import Path
from flask import Blueprint, jsonify, render_template, request, redirect, url_for
from modules.drivers.models.drivers_model import is_driver_value_duplicate
from modules.drivers.services.drivers_service import fetch_drivers, create_driver, remove_driver

# 🌟 تحديد المسار الجذري للمشروع لاستيراد أداة التصدير الموحدة لسيماكم
base_dir_path = Path(__file__).parent.parent.parent
if str(base_dir_path) not in sys.path:
    sys.path.append(str(base_dir_path))

try:
    from utils.excel_export import generate_semacom_excel
except ImportError:
    generate_semacom_excel = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, 'views')

drivers_bp = Blueprint(
    'drivers', 
    __name__, 
    template_folder=TEMPLATE_DIR,
    url_prefix='/drivers'
)

@drivers_bp.route('/')
def index():
    search_query = request.args.get('q', '')
    drivers = fetch_drivers(search_query)
    return render_template('driver_index.html', drivers=drivers)

@drivers_bp.route('/add', methods=['GET', 'POST'])
def add():
    if request.method == 'POST':
        success, message = create_driver(request.form)
        if success:
            return redirect(url_for('drivers.index'))
        else:
            return render_template(
                'driver_add.html', error=message, form_data=request.form.to_dict()
            )
    return render_template('driver_add.html')

@drivers_bp.route('/check-duplicate')
def check_duplicate():
    field = request.args.get('field', '')
    value = request.args.get('value', '')
    labels = {'name': 'اسم الموظف', 'national_id': 'رقم الهوية'}
    if field not in labels:
        return jsonify({'duplicate': False, 'message': ''}), 400
    duplicate = is_driver_value_duplicate(field, value)
    return jsonify({
        'duplicate': duplicate,
        'message': f'{labels[field]} مسجل مسبقًا، يرجى إدخال قيمة مختلفة.' if duplicate else '',
    })

@drivers_bp.route('/delete/<int:driver_id>', methods=['POST'])
def delete(driver_id):
    remove_driver(driver_id)
    return redirect(url_for('drivers.index'))

@drivers_bp.route('/export')
def export_drivers_excel():
    """🌟 مسار تصدير سجل السائقين إلى Excel مع دعم البحث والفلترة"""
    if not generate_semacom_excel:
        return "مكتبة توليد الإكسل غير متوفرة", 500
        
    search_query = request.args.get('q', '')
    drivers = fetch_drivers(search_query)
    
    # العناوين المطابقة لجدول السائقين بالكامل
    headers = [
        "#", "اسم الموظف", "رقم الهوية", "رقم الجوال", "الجنسية", 
        "الصفة الوظيفية", "القسم التابع له", "رقم الرخصة", "نوع الرخصة",
        "عدد القيود", "تاريخ اصدار الرخصة", "تاريخ انتهاء الرخصة"
    ]
    data = []
    
    for idx, d in enumerate(drivers, start=1):
        row = dict(d) if hasattr(d, 'keys') else d
        data.append([
            idx,
            row.get('name', '-'),
            row.get('national_id', '-'),
            row.get('phone', '-'),
            row.get('nationality', '-'),
            row.get('job_title', '-'),
            row.get('department', '-'),
            row.get('license_number', '-'),
            row.get('license_type', '-'),
            row.get('restrictions_count', 0),
            row.get('license_issue_date', '-'),
            row.get('license_expiry_date', '-')
        ])
        
    return generate_semacom_excel("سجل_السائقين_والموظفين", headers, data)