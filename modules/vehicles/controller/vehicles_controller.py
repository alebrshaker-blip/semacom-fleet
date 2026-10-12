import sys
from pathlib import Path
import sqlite3
from core.database import DB_PATH

# 🌟 تحديد المسار الجذري للمشروع وإضافته لـ sys.path لضمان استيراد utils بنجاح
base_dir = Path(__file__).parent.parent.parent.parent
if str(base_dir) not in sys.path:
    sys.path.append(str(base_dir))

try:
    from utils.excel_export import generate_semacom_excel
except ImportError:
    generate_semacom_excel = None
class VehiclesController:
    def __init__(self):
        self.db_path = DB_PATH

    def get_connection(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def get_all(self, search_query=None):
        """جلب جميع المركبات مع دعم البحث الشامل والفلترة"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if search_query:
                query = """
                    SELECT * FROM vehicles 
                    WHERE vehicle_code LIKE ? 
                       OR plate_number LIKE ? 
                       OR vehicle_type LIKE ? 
                       OR model LIKE ? 
                       OR manufacturer LIKE ? 
                       OR color LIKE ? 
                       OR fuel_type LIKE ? 
                       OR engine_number LIKE ? 
                       OR chassis_number LIKE ?
                       OR status LIKE ?
                       OR ownership LIKE ?
                """
                search_term = f"%{search_query}%"
                cursor.execute(query, (
                    search_term, search_term, search_term, 
                    search_term, search_term, search_term, 
                    search_term, search_term, search_term,
                    search_term, search_term
                ))
            else:
                cursor.execute("SELECT * FROM vehicles")

            rows = cursor.fetchall()
            vehicles = [dict(row) for row in rows]
        except sqlite3.OperationalError:
            vehicles = []
        finally:
            conn.close()
        return vehicles

    def get_all_fields(self):
        """جلب الحقول الأساسية ودعم الحقول الديناميكية لضمان عدم اختفاء الأعمدة أبداً"""
        # الحقول الأساسية الثابتة للنظام
        fields = [
            {"name": "vehicle_code", "label": "كود المركبة"},
            {"name": "plate_number", "label": "رقم اللوحة"},
            {"name": "vehicle_type", "label": "النوع"},
            {"name": "model", "label": "الموديل"},
            {"name": "manufacturer", "label": "الشركة المصنعة"},
            {"name": "color", "label": "اللون"},
            {"name": "fuel_type", "label": "نوع الوقود"},
            {"name": "engine_number", "label": "رقم المكينة"},
            {"name": "chassis_number", "label": "رقم الهيكل"},
            {"name": "status", "label": "الحالة"},
            {"name": "ownership", "label": "الملكية"}
        ]

        # جلب أي حقول ديناميكية أضافها المستخدم مسبقاً من قاعدة البيانات
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT name, label FROM vehicle_fields")
            custom_fields = [dict(row) for row in cursor.fetchall()]
            
            # دمج الحقول الديناميكية مع التأكد من عدم تكرارها
            existing_names = {f["name"] for f in fields}
            for cf in custom_fields:
                if cf["name"] not in existing_names:
                    fields.append(cf)
        except sqlite3.OperationalError:
            pass
        finally:
            conn.close()
            
        return fields

    def add(self, data):
        """إضافة مركبة جديدة لقاعدة البيانات"""
        data.setdefault("status", "متاحة")
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            columns = list(data.keys())
            values = list(data.values())
            placeholders = ", ".join(["?"] * len(columns))
            cols_str = ", ".join([f'"{col}"' for col in columns])
            
            query = f"INSERT INTO vehicles ({cols_str}) VALUES ({placeholders})"
            cursor.execute(query, values)
            conn.commit()
        except Exception as e:
            raise e
        finally:
            conn.close()

    def export_excel(self, search_query=None):
        """🌟 دالة تصدير سجل المركبات والأسطول إلى Excel بنفس الآلية والتنسيق الموحد"""
        if not generate_semacom_excel:
            raise ImportError("مكتبة أو دالة توليد الإكسل غير متوفرة في المسار المحدد.")
        
        # 1. جلب العناوين (Headers) ديناميكياً لتشمل الأعمدة الأساسية والمخصصة
        fields = self.get_all_fields()
        headers = ['#'] + [f['label'] for f in fields]
        
        # 2. جلب سجلات المركبات (مع دعم نص البحث إن وجد لتصدير النتائج المصفاة فقط)
        vehicles_records = self.get_all(search_query)
        
        # 3. بناء صفوف البيانات بشكل آمن وتلافي أي قيم فارغة
        data = []
        for idx, r in enumerate(vehicles_records, 1):
            row_dict = dict(r)
            row_data = [idx]
            for f in fields:
                field_name = f['name']
                val = row_dict.get(field_name, '-')
                row_data.append(val if val is not None and val != '' else '-')
            data.append(row_data)
            
        # 4. إرجاع ملف الإكسل الجاهز للتحميل بالهوية البصرية الموحدة
        return generate_semacom_excel("سجل_المركبات_والمعدات", headers, data)