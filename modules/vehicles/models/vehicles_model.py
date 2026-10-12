from pathlib import Path
import sqlite3
from core.database import DB_PATH

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
    self.db_path = DB_PATH

  def get_connection(self):
    conn = sqlite3.connect(str(self.db_path))
    conn.row_factory = sqlite3.Row
    return conn

  def get_all(self):
    conn = self.get_connection()
    cursor = conn.cursor()
    try:
      cursor.execute("SELECT * FROM vehicles")
      rows = cursor.fetchall()
      vehicles = [dict(row) for row in rows]
    except sqlite3.OperationalError:
      vehicles = []
    finally:
      conn.close()
    return vehicles

  def get_core_fields(self):
    return CORE_FIELDS

  def get_custom_fields(self):
    """جلب الحقول الديناميكية المضافة مسبقاً من قاعدة البيانات"""
    conn = self.get_connection()
    cursor = conn.cursor()
    try:
      cursor.execute("SELECT name, label, required FROM vehicle_fields")
      rows = cursor.fetchall()
      fields = [dict(row) for row in rows]
    except sqlite3.OperationalError:
      fields = []
    finally:
      conn.close()
    return fields

  def get_all_fields(self):
    """دمج الحقول الأساسية مع الحقول الديناميكية لعرضها في صفحة الإضافة والجدول"""
    return self.get_core_fields() + self.get_custom_fields()

  def add(self, data):
    """حفظ البيانات مع فحص التكرار والتحقق من الحقول الإلزامية (أساسية وديناميكية)"""

    # 1. التحقق من الحقول الإلزامية (الأساسية والديناميكية)
    all_fields = self.get_all_fields()
    for field in all_fields:
      if field.get("required") == 1 or field.get("required") == "1":
        val = data.get(field["name"])
        if not val or str(val).strip() == "":
          raise ValueError(
              f"تنبيه: الحقل '{field['label']}' إلزامي ولا يمكن تركه فارغاً!"
          )

    conn = self.get_connection()
    cursor = conn.cursor()

    v_code = data.get("vehicle_code")
    plate = data.get("plate_number")

    # 2. التحقق من عدم تكرار كود المركبة أو رقم اللوحة
    if v_code or plate:
      cursor.execute(
          "SELECT id FROM vehicles WHERE vehicle_code = ? OR plate_number = ?",
          (v_code, plate),
      )
      if cursor.fetchone():
        conn.close()
        raise ValueError(
            "تنبيه: كود المركبة أو رقم اللوحة موجود مسبقاً في النظام ولا يمكن"
            " تكراره!"
        )

    data.setdefault("status", "متاحة")
    keys = [k for k, v in data.items() if v is not None and v != ""]
    values = [data[k] for k in keys]

    if keys:
      columns = ", ".join([f'"{k}"' for k in keys])
      placeholders = ", ".join(["?"] * len(keys))
      query = f"INSERT INTO vehicles ({columns}) VALUES ({placeholders})"
      cursor.execute(query, values)
      conn.commit()

    conn.close()
    return True