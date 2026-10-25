import sys
from pathlib import Path

from modules.vehicles import repository
from modules.vehicles.models.vehicle_orm import CORE_COLUMNS  # noqa: F401

# 🌟 تحديد المسار الجذري للمشروع وإضافته لـ sys.path لضمان استيراد utils بنجاح
base_dir = Path(__file__).parent.parent.parent.parent
if str(base_dir) not in sys.path:
    sys.path.append(str(base_dir))

try:
    from utils.excel_export import generate_semacom_excel
except ImportError:
    generate_semacom_excel = None

CORE_FIELD_LABELS = [
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
    {"name": "ownership", "label": "الملكية"},
]


class VehiclesController:
    def __init__(self):
        pass

    def get_all(self, search_query=None, page=None, page_size=50):
        """جلب جميع المركبات النشطة مع دعم البحث الشامل"""
        return repository.list_active(search_query, page=page, page_size=page_size)

    def get_all_fields(self):
        """الحقول الأساسية مضافًا إليها الحقول الديناميكية المسجلة"""
        fields = [dict(field) for field in CORE_FIELD_LABELS]
        existing_names = {field["name"] for field in fields}
        existing_labels = {" ".join(field["label"].split()).casefold() for field in fields}
        for custom in repository.list_custom_fields():
            normalized_label = " ".join(custom["label"].split()).casefold()
            if custom["name"] not in existing_names and normalized_label not in existing_labels:
                fields.append(
                    {
                        "name": custom["name"],
                        "label": custom["label"],
                        "is_custom": True,
                    }
                )
                existing_labels.add(normalized_label)
        return fields

    def add(self, data):
        """إضافة مركبة جديدة (يرفع ValueError عند تكرار الكود أو اللوحة)"""
        repository.create_vehicle(data)

    def export_excel(self, search_query=None):
        """🌟 دالة تصدير سجل المركبات والمعدات إلى Excel بنفس الآلية والتنسيق الموحد"""
        if not generate_semacom_excel:
            raise ImportError("مكتبة أو دالة توليد الإكسل غير متوفرة في المسار المحدد.")

        fields = self.get_all_fields()
        headers = ['#'] + [f['label'] for f in fields]
        vehicles_records = self.get_all(search_query)

        data = []
        for idx, record in enumerate(vehicles_records, 1):
            row_data = [idx]
            for field in fields:
                val = record.get(field['name'], '-')
                row_data.append(val if val is not None and val != '' else '-')
            data.append(row_data)

        return generate_semacom_excel("سجل_المركبات_والمعدات", headers, data)
