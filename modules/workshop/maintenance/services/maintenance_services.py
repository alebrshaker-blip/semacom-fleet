import os
import sqlite3
import time
import datetime
from pathlib import Path
from utils.generators import generate_work_order_no
from core.database import DB_PATH


class MaintenanceService:

    @staticmethod
    def get_db_connection():
        """جلب اتصال موثوق بقاعدة البيانات"""
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        return conn

    @classmethod
    def get_all_vehicles(cls):
        """جلب بيانات المركبات للنموذج"""
        vehicles = []
        conn = None
        try:
            conn = cls.get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM vehicles")
            rows = cur.fetchall()

            for r in rows:
                row_dict = dict(r)
                code = row_dict.get('vehicle_code') or row_dict.get('code') or ''
                plate = row_dict.get('plate_number') or row_dict.get('plate') or ''
                
                vehicles.append({
                    'id': row_dict.get('id'),
                    'vehicle_code': str(code).strip(),
                    'plate_number': str(plate).strip()
                })
        except Exception as e:
            print(f"[ERROR - get_all_vehicles]: {e}")
        finally:
            if conn:
                conn.close()
        return vehicles

    @classmethod
    def get_all_drivers(cls):
        """جلب قائمة السائقين"""
        drivers = []
        conn = None
        try:
            conn = cls.get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM drivers")
            rows = cur.fetchall()

            for r in rows:
                row_dict = dict(r)
                name = row_dict.get('name') or row_dict.get('full_name') or ''
                drivers.append({
                    'id': row_dict.get('id'),
                    'name': str(name).strip()
                })
        except Exception as e:
            print(f"[ERROR - get_all_drivers]: {e}")
        finally:
            if conn:
                conn.close()
        return drivers

    @classmethod
    def get_all_team_members(cls):
        """جلب قائمة الفنيين وأعضاء الفريق"""
        members = []
        conn = None
        try:
            conn = cls.get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='team_members'")
            
            if cur.fetchone():
                cur.execute("SELECT * FROM team_members")
                rows = cur.fetchall()
                for r in rows:
                    rd = dict(r)
                    m_name = rd.get('full_name') or rd.get('name') or ''
                    if m_name:
                        members.append({
                            'id': rd.get('id'),
                            'name': str(m_name).strip(),
                            'job_title': rd.get('job_title', '')
                        })
            if not members:
                cur.execute("SELECT * FROM drivers")
                rows = cur.fetchall()
                for r in rows:
                    rd = dict(r)
                    d_name = rd.get('name') or rd.get('full_name') or ''
                    if d_name:
                        members.append({
                            'id': rd.get('id'),
                            'name': str(d_name).strip(),
                            'job_title': rd.get('job_title', 'فني')
                        })
        except Exception as e:
            print(f"[ERROR - get_all_team_members]: {e}")
        finally:
            if conn:
                conn.close()
        return members

    @classmethod
    def create_order(cls, data):
        """إنشاء أمر الصيانة وحفظ بيانات الفتح بحقولها المعتمدة"""
        conn = cls.get_db_connection()
        cur = conn.cursor()
        
        try:
            m_type = data.get('type', 'internal')
            order_no = generate_work_order_no(m_type)

            vehicle = None
            vehicle_id = data.get('vehicle_id')
            if vehicle_id:
                vehicle = cur.execute(
                    "SELECT vehicle_code, plate_number FROM vehicles WHERE id = ?",
                    (vehicle_id,)
                ).fetchone()

            query = """
                INSERT INTO maintenance_orders (
                    order_no, type, status,
                    vehicle_id, vehicle_code, plate_number,
                    maintenance_type, fault_description, fault_cause, severity,
                    technician_name, expected_completion_time, order_date,
                    workshop_name, workshop_phone, workshop_location, send_reason,
                    send_datetime, responsible_person, expected_cost, expected_time, notes,
                    driver_id, reporter_name, case_description, has_injuries,
                    is_drivable, official_notified, emergency_location,
                    incident_datetime, subject, description, causes, other_details
                ) VALUES (?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """

            cur.execute(query, (
                order_no,
                m_type,
                vehicle_id,
                vehicle['vehicle_code'] if vehicle else data.get('vehicle_code'),
                vehicle['plate_number'] if vehicle else data.get('plate_number'),
                data.get('maintenance_type'),
                data.get('fault_description'),
                data.get('fault_cause'),
                data.get('severity'),
                data.get('technician_name'),
                data.get('expected_completion_time'),
                data.get('order_date') or datetime.date.today().strftime('%Y-%m-%d'),
                data.get('workshop_name'),
                data.get('workshop_phone'),
                data.get('workshop_location'),
                data.get('send_reason'),
                data.get('send_datetime'),
                data.get('responsible_person'),
                float(data.get('expected_cost') or 0.0),
                data.get('expected_time'),
                data.get('notes'),
                data.get('driver_id'),
                data.get('reporter_name'),
                data.get('case_description'),
                data.get('has_injuries'),
                data.get('is_drivable'),
                data.get('official_notified'),
                data.get('emergency_location'),
                data.get('incident_datetime'),
                data.get('subject'),
                data.get('description'),
                data.get('causes'),
                data.get('other_details')
            ))
            conn.commit()
            return order_no
            
        except Exception as e:
            print(f"[ERROR - create_order]: {e}")
            conn.rollback()
            raise e
        finally:
            conn.close()

    @classmethod
    def get_orders(cls, m_type, status='open'):
        """جلب أوامر الصيانة حسب النوع والحالة"""
        rows = []
        conn = None
        try:
            conn = cls.get_db_connection()
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM maintenance_orders WHERE type = ? AND status = ? ORDER BY id DESC", 
                (m_type, status)
            )
            rows = [dict(r) for r in cur.fetchall()]
        except Exception as e:
            print(f"[ERROR - get_orders]: {e}")
        finally:
            if conn:
                conn.close()
        return rows

    @classmethod
    def get_all_orders(cls, m_type='all', status='all', date_from=None, date_to=None):
        """جلب جميع أوامر الصيانة مع فلاتر النوع والحالة والفترة الزمنية"""
        conditions = []
        params = []
        valid_types = {'internal', 'external', 'emergency', 'exceptional'}

        if m_type in valid_types:
            conditions.append('type = ?')
            params.append(m_type)
        if status in {'open', 'closed'}:
            conditions.append('status = ?')
            params.append(status)

        order_date = "COALESCE(NULLIF(order_date, ''), NULLIF(send_datetime, ''), NULLIF(incident_datetime, ''), NULLIF(closure_date, ''), NULLIF(closure_datetime, ''), '')"
        if date_from:
            conditions.append(f"substr({order_date}, 1, 10) >= ?")
            params.append(date_from)
        if date_to:
            conditions.append(f"substr({order_date}, 1, 10) <= ?")
            params.append(date_to)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ''
        query = f"""
            SELECT * FROM maintenance_orders
            {where_clause}
            ORDER BY CASE status WHEN 'open' THEN 0 ELSE 1 END, id DESC
        """

        conn = None
        try:
            conn = cls.get_db_connection()
            rows = conn.execute(query, tuple(params)).fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            print(f"[ERROR - get_all_orders]: {e}")
            return []
        finally:
            if conn:
                conn.close()

    @classmethod
    def get_order_by_id(cls, order_id):
        """جلب أمر صيانة محدد برقم ID"""
        order = None
        conn = None
        try:
            conn = cls.get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM maintenance_orders WHERE id = ?", (order_id,))
            row = cur.fetchone()
            if row:
                order = dict(row)
        except Exception as e:
            print(f"[ERROR - get_order_by_id]: {e}")
        finally:
            if conn:
                conn.close()
        return order

    @classmethod
    def delete_order(cls, order_id):
        """حذف أمر الصيانة"""
        conn = None
        try:
            conn = cls.get_db_connection()
            cur = conn.cursor()
            cur.execute("DELETE FROM maintenance_orders WHERE id = ?", (order_id,))
            conn.commit()
        except Exception as e:
            print(f"[ERROR - delete_order]: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()

    @classmethod
    def close_order(cls, order_id, close_data, files=None):
        """إقفال أمر الصيانة وحفظ بيانات الإقفال والملفات المرفقة"""
        conn = cls.get_db_connection()
        cur = conn.cursor()

        try:
            current_file = Path(__file__).resolve()
            base_dir = current_file.parent
            while base_dir != base_dir.parent:
                if (base_dir / "static").exists() or (base_dir.name == "app" and (base_dir / "static").exists()):
                    break
                if (base_dir / "app" / "static").exists():
                    base_dir = base_dir / "app"
                    break
                base_dir = base_dir.parent

            upload_dir = base_dir / "static" / "uploads" / "maintenance"
            if not upload_dir.exists() and (Path(os.getcwd()) / "app" / "static").exists():
                upload_dir = Path(os.getcwd()) / "app" / "static" / "uploads" / "maintenance"
            elif not upload_dir.exists():
                upload_dir = Path(os.getcwd()) / "static" / "uploads" / "maintenance"

            upload_dir.mkdir(parents=True, exist_ok=True)

            file_paths = {}
            if files:
                file_keys = ['photo_before', 'photo_after', 'other_attachments']
                for f_key in file_keys:
                    file_item = files.get(f_key)
                    if file_item and file_item.filename:
                        file_name = f"{order_id}_{int(time.time())}_{file_item.filename}"
                        save_path = upload_dir / file_name
                        file_item.save(str(save_path))
                        file_paths[f_key] = f"uploads/maintenance/{file_name}"
                    else:
                        file_paths[f_key] = None

            current_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
            closure_date = close_data.get('closure_date') or datetime.date.today().strftime('%Y-%m-%d')
            receipt_datetime = close_data.get('receipt_datetime') or current_time
            closure_datetime = close_data.get('closure_datetime') or current_time

            final_cost = float(close_data.get('final_cost') or 0.0)

            query = """
                UPDATE maintenance_orders 
                SET status = 'closed',
                    closure_date = ?,
                    receipt_datetime = ?,
                    closure_datetime = ?,
                    closure_reason = ?,
                    spare_parts = ?,
                    final_cost = ?,
                    recommendation = ?,
                    closing_notes = ?,
                    action_taken = ?,
                    is_towed = ?,
                    towing_party = ?,
                    intervention_team = ?,
                    treatment_details = ?,
                    photo_before = COALESCE(?, photo_before),
                    photo_after = COALESCE(?, photo_after),
                    other_attachments = COALESCE(?, other_attachments)
                WHERE id = ?
            """

            cur.execute(query, (
                closure_date,
                receipt_datetime,
                closure_datetime,
                close_data.get('closure_reason'),
                close_data.get('spare_parts'),
                final_cost,
                close_data.get('recommendation'),
                close_data.get('closing_notes'),
                close_data.get('action_taken'),
                close_data.get('is_towed'),
                close_data.get('towing_party'),
                close_data.get('intervention_team'),
                close_data.get('treatment_details'),
                file_paths.get('photo_before'),
                file_paths.get('photo_after'),
                file_paths.get('other_attachments'),
                order_id
            ))

            conn.commit()
            
        except Exception as e:
            print(f"[ERROR - close_order]: {e}")
            conn.rollback()
            raise e
        finally:
            conn.close()