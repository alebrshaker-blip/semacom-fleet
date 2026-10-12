import sqlite3
from pathlib import Path
from core.database import DB_PATH

def get_db_connection():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS handovers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            handover_type TEXT,
            vehicle_id INTEGER,
            handover_date TEXT,
            vehicle_info TEXT,
            driver_info TEXT,
            purpose TEXT,
            department TEXT,
            description TEXT,
            odometer TEXT,
            fuel_level TEXT,
            body_condition TEXT,
            interior_condition TEXT,
            tires_condition TEXT,
            mechanical_condition TEXT,
            electrical_condition TEXT,
            electrical_technician TEXT,
            mechanical_technician TEXT,
            notes TEXT,
            status TEXT
        )
    """)
    columns = {row['name'] for row in conn.execute("PRAGMA table_info(handovers)")}
    for column_name, column_type in (
        ('vehicle_id', 'INTEGER'),
        ('purpose', 'TEXT'),
        ('department', 'TEXT'),
        ('description', 'TEXT'),
    ):
        if column_name not in columns:
            conn.execute(f'ALTER TABLE handovers ADD COLUMN "{column_name}" {column_type}')
    conn.commit()
    return conn

def get_active_handovers(search_query=None):
    conn = get_db_connection()
    if search_query:
        query = """SELECT * FROM handovers WHERE status = 'نشط' AND 
                   (vehicle_info LIKE ? OR driver_info LIKE ? OR electrical_technician LIKE ?)
                   ORDER BY id DESC"""
        param = f"%{search_query}%"
        records = conn.execute(query, (param, param, param)).fetchall()
    else:
        records = conn.execute("SELECT * FROM handovers WHERE status = 'نشط' ORDER BY id DESC").fetchall()
    conn.close()
    return records

def get_archived_handovers(search_query=None):
    conn = get_db_connection()
    if search_query:
        query = """SELECT * FROM handovers WHERE status = 'مؤرشف' AND 
                   (vehicle_info LIKE ? OR driver_info LIKE ? OR electrical_technician LIKE ?)
                   ORDER BY id DESC"""
        param = f"%{search_query}%"
        records = conn.execute(query, (param, param, param)).fetchall()
    else:
        records = conn.execute("SELECT * FROM handovers WHERE status = 'مؤرشف' ORDER BY id DESC").fetchall()
    conn.close()
    return records

def get_form_entities():
    conn = get_db_connection()
    try:
        vehicles = [dict(row) for row in conn.execute("SELECT * FROM vehicles").fetchall()]
        active_handovers = [
            dict(row) for row in conn.execute(
                "SELECT * FROM handovers WHERE status = 'نشط' ORDER BY id DESC"
            ).fetchall()
        ]

        def vehicle_for_handover(handover):
            vehicle_id = handover.get('vehicle_id')
            if vehicle_id is not None:
                match = next((v for v in vehicles if str(v['id']) == str(vehicle_id)), None)
                if match:
                    return match
            info = (handover.get('vehicle_info') or '').strip()
            return next(
                (
                    vehicle for vehicle in vehicles
                    if info in {
                        str(vehicle.get('plate_number') or '').strip(),
                        str(vehicle.get('vehicle_code') or '').strip(),
                        f"{vehicle.get('vehicle_code') or ''} - {vehicle.get('plate_number') or ''}".strip()
                    }
                ),
                None
            )

        assigned_vehicles = []
        assigned_ids = set()
        for handover in active_handovers:
            vehicle = vehicle_for_handover(handover)
            if vehicle:
                assigned_ids.add(str(vehicle['id']))
                assigned_vehicles.append({
                    'vehicle_id': vehicle['id'],
                    'vehicle_info': f"{vehicle.get('vehicle_code') or ''} - {vehicle.get('plate_number') or ''}".strip(' -'),
                    'driver_info': handover.get('driver_info') or ''
                })

        available_vehicles = [
            vehicle for vehicle in vehicles
            if vehicle.get('status') not in ('مسلمة', 'تحت الصيانة')
            and vehicle.get('workshop_status') != 'تحت الصيانة'
            and str(vehicle['id']) not in assigned_ids
        ]
        try:
            drivers = conn.execute("SELECT * FROM drivers").fetchall()
        except sqlite3.OperationalError:
            drivers = conn.execute("SELECT * FROM team_members").fetchall()
        try:
            technicians = conn.execute("SELECT * FROM team_members").fetchall()
        except sqlite3.OperationalError:
            technicians = []
    finally:
        conn.close()
    return available_vehicles, assigned_vehicles, drivers, technicians

def save_handover_process(data):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        handover_type = data.get('handover_type')
        if handover_type not in ('تسليم عهدة', 'إرجاع عهدة'):
            raise ValueError("نوع عملية الاستلام أو التسليم غير صحيح.")
        if data.get('purpose') not in ('صرف', 'مهمة عمل', 'أخرى'):
            raise ValueError("يرجى اختيار غرض صحيح للعملية.")
        if not (data.get('department') or '').strip():
            raise ValueError("يرجى إدخال القسم التابع له.")
        if not (data.get('description') or '').strip():
            raise ValueError("يرجى إدخال وصف العملية.")

        conn.execute("BEGIN IMMEDIATE")
        selected_vehicle = (data.get('vehicle_info') or '').strip()
        vehicle = cur.execute(
            "SELECT * FROM vehicles WHERE CAST(id AS TEXT) = ? OR plate_number = ? OR vehicle_code = ?",
            (selected_vehicle, selected_vehicle, selected_vehicle)
        ).fetchone()
        if not vehicle:
            raise ValueError("المركبة المحددة غير موجودة.")

        vehicle_id = vehicle['id']
        vehicle_info = f"{vehicle['vehicle_code'] or ''} - {vehicle['plate_number'] or ''}".strip(' -')
        driver_info = data.get('driver_info')
        active_record = cur.execute(
            "SELECT id FROM handovers WHERE (vehicle_id = ? OR vehicle_info = ?) AND status = 'نشط' ORDER BY id DESC LIMIT 1",
            (vehicle_id, vehicle_info)
        ).fetchone()

        if handover_type == 'تسليم عهدة':
            if vehicle['status'] == 'مسلمة' or active_record:
                raise ValueError("المركبة مسلمة بالفعل ولا يمكن تسليمها مرة أخرى.")
            if vehicle.get('workshop_status') == 'تحت الصيانة' or vehicle['status'] == 'تحت الصيانة':
                raise ValueError("لا يمكن تسليم مركبة حالتها تحت الصيانة.")
            record_status = 'نشط'
            vehicle_status = 'مسلمة'
        else:
            if not active_record:
                raise ValueError("لا توجد عهدة نشطة للمركبة المحددة لإرجاعها.")
            cur.execute("UPDATE handovers SET status = 'مؤرشف' WHERE id = ?", (active_record['id'],))
            record_status = 'مؤرشف'
            vehicle_status = 'متاحة'

        cur.execute("""
            INSERT INTO handovers (
                handover_type, vehicle_id, handover_date, vehicle_info, driver_info,
                purpose, department, description, odometer, fuel_level,
                body_condition, interior_condition, tires_condition, mechanical_condition,
                electrical_condition, electrical_technician, mechanical_technician, notes, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            handover_type, vehicle_id, data.get('handover_date'), vehicle_info, driver_info,
            data.get('purpose'), data.get('department'), data.get('description'),
            data.get('odometer'), data.get('fuel_level'), data.get('body_condition'),
            data.get('interior_condition'), data.get('tires_condition'),
            data.get('mechanical_condition'), data.get('electrical_condition'),
            data.get('electrical_technician'), data.get('mechanical_technician'),
            data.get('notes'), record_status
        ))
        cur.execute("UPDATE vehicles SET status = ? WHERE id = ?", (vehicle_status, vehicle_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_driver_at_datetime(vehicle_plate, event_datetime):
    management_custody = "عهدة إدارة المعدات"
    plate = str(vehicle_plate or '').strip()
    target = str(event_datetime or '').replace('T', ' ').strip()
    if not plate or not target:
        return management_custody

    conn = get_db_connection()
    try:
        vehicle = conn.execute(
            "SELECT id FROM vehicles WHERE plate_number = ? LIMIT 1", (plate,)
        ).fetchone()
        if vehicle:
            records = conn.execute(
                """SELECT * FROM handovers
                   WHERE vehicle_id = ? OR vehicle_info LIKE ?
                   ORDER BY handover_date ASC, id ASC""",
                (vehicle['id'], f"%{plate}%")
            ).fetchall()
        else:
            records = conn.execute(
                """SELECT * FROM handovers WHERE vehicle_info LIKE ?
                   ORDER BY handover_date ASC, id ASC""",
                (f"%{plate}%",)
            ).fetchall()

        driver = management_custody
        for record in records:
            recorded_at = str(record['handover_date'] or '').replace('T', ' ').strip()
            if not recorded_at or recorded_at[:16] > target[:16]:
                continue
            if record['handover_type'] == 'تسليم عهدة':
                driver = record['driver_info'] or management_custody
            elif record['handover_type'] == 'إرجاع عهدة':
                driver = management_custody
        return driver
    finally:
        conn.close()