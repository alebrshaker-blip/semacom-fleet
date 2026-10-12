import sys
import os
from pathlib import Path
from flask import Blueprint, render_template, request, redirect, url_for
from modules.drivers.services.drivers_service import fetch_drivers, create_driver, remove_driver

# 🌟 إضافة المسار الجذري لاستيراد مكتبة التصدير الموحدة لسيماكم
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
    # تصحيح اسم القالب ليتطابق مع الملف الموجود driver_index.html
    return render_template('driver_index.html', drivers=drivers)

@drivers_bp.route('/add', methods=['GET', 'POST'])
def add():
    if request.method == 'POST':
        success, message = create_driver(request.form)
        if success:
            return redirect(url_for('drivers.index'))
        else:
            # تصحيح اسم القالب ليتطابق مع driver_add.html
            return render_template('driver_add.html', error=message)
    # تصحيح اسم القالب ليتطابق مع driver_add.html
    return render_template('driver_add.html')

@drivers_bp.route('/delete/<int:driver_id>', methods=['POST'])
def delete(driver_id):
    """🌟 مسار حذف آمن وعملي لا يسبب مشاكل مستقبلية"""
    remove_driver(driver_id)
    return redirect(url_for('drivers.index'))

@drivers_bp.route('/export')
def export_drivers_excel():
    """🌟 مسار تصدير بيانات السائقين إلى Excel مع دعم البحث"""
    search_query = request.args.get('q', '')
    drivers = fetch_drivers(search_query)
    
    if not generate_semacom_excel:
        return "مكتبة توليد الإكسل غير متوفرة", 500
        
    headers = ["#", "اسم السائق", "رقم الهوية", "رقم الجوال", "الحالة"]
    data = []
    
    for i, driver in enumerate(drivers, start=1):
        data.append([
            i,
            driver.get('name', '-'),
            driver.get('national_id', '-'),
            driver.get('phone', '-'),
            driver.get('status', '-')
        ])
        
    return generate_semacom_excel("drivers_report", headers, data)