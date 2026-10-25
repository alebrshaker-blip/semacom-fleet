from modules.vehicles import repository
from modules.vehicles.models.vehicle_orm import CORE_COLUMNS  # noqa: F401

# الحقول الأساسية الثابتة بترتيبها الصحيح
CORE_FIELDS = [
    {"name": "vehicle_code", "label": "كود المركبة", "required": 1},
    {"name": "plate_number", "label": "رقم اللوحة", "required": 1},
    {"name": "vehicle_type", "label": "النوع", "required": 0},
    {"name": "model", "label": "الموديل", "required": 0},
    {"name": "manufacturer", "label": "الشركة المصنعة", "required": 0},
    {"name": "color", "label": "اللون", "required": 0},
    {"name": "fuel_type", "label": "نوع الوقود", "required": 0},
    {"name": "engine_number", "label": "رقم المكينة", "required": 0},
    {"name": "chassis_number", "label": "رقم الهيكل", "required": 0},
    {"name": "status", "label": "الحالة", "required": 0},
    {"name": "ownership", "label": "الملكية", "required": 0},
]


class VehiclesModel:

  def __init__(self):
    pass

  def get_all(self):
    return repository.list_active()

  def get_core_fields(self):
    return CORE_FIELDS

  def get_custom_fields(self):
    """جلب الحقول الديناميكية المضافة مسبقاً من قاعدة البيانات"""
    return repository.list_custom_fields()

  def get_all_fields(self):
    """دمج الحقول الأساسية مع الحقول الديناميكية لعرضها في صفحة الإضافة والجدول"""
    fields = self.get_core_fields()
    names = {field["name"] for field in fields}
    labels = {" ".join(field["label"].split()).casefold() for field in fields}
    for field in self.get_custom_fields():
      normalized_label = " ".join(field["label"].split()).casefold()
      if field["name"] not in names and normalized_label not in labels:
        fields.append(field)
        names.add(field["name"])
        labels.add(normalized_label)
    return fields

  def add(self, data):
    """حفظ البيانات مع التحقق من الحقول الإلزامية (أساسية وديناميكية) وفحص التكرار"""
    for field in self.get_all_fields():
      if field.get("required") == 1 or field.get("required") == "1":
        val = data.get(field["name"])
        if not val or str(val).strip() == "":
          raise ValueError(
              f"تنبيه: الحقل '{field['label']}' إلزامي ولا يمكن تركه فارغاً!"
          )

    data = {k: v for k, v in data.items() if v is not None and v != ""}
    repository.create_vehicle(data)
    return True
