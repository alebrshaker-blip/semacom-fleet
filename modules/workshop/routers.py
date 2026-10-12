from flask import Blueprint, render_template, redirect, url_for
from modules.workshop.store.routers import store_bp
from modules.workshop.equ.routers import equ_bp
from modules.workshop.team.routers import team_bp
from modules.workshop.maintenance.routers import maintenance_bp
from .comp_inspection import comp_inspection_bp
# استيراد بلوبرنت متابعة الزيوت
from modules.workshop.oil_tracking.router import oil_tracking_bp

# تسجيل راوتر الزيوت تحت راوتر الورشة الرئيسي

# تعريف الـ Blueprint الخاص بالورشة
workshop_bp = Blueprint('workshop', __name__, url_prefix='/workshop', template_folder='views')

@workshop_bp.route('/')
def index():
    return render_template('work_index.html')

# تسجيل الموديولات الفرعية
workshop_bp.register_blueprint(store_bp, url_prefix='/store')
workshop_bp.register_blueprint(equ_bp, url_prefix='/equ')      
workshop_bp.register_blueprint(team_bp, url_prefix='/team')    
workshop_bp.register_blueprint(maintenance_bp, url_prefix='/maintenance') # تسجيل موديول الصيانة تحت /workshop/maintenance
workshop_bp.register_blueprint(comp_inspection_bp, url_prefix='/comp-inspection')
workshop_bp.register_blueprint(oil_tracking_bp, url_prefix='/oil-tracking')


# حل مؤقت لضمان عدم ظهور 404 لو حدث طلب لـ /workshop/equipment
@workshop_bp.route('/equipment')
def redirect_equipment():
    return redirect(url_for('workshop.equ_bp.index'))