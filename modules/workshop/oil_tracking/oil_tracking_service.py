import sqlite3
from datetime import datetime
from .oil_tracking_models import OilTrackingModel

class OilTrackingService:
    @staticmethod
    def get_all_records():
        OilTrackingModel.init_db()
        conn = OilTrackingModel.get_db_connection()
        records = conn.execute("SELECT * FROM oil_change_tracking ORDER BY id DESC").fetchall()
        conn.close()
        
        processed_records = []
        for rec in records:
            item = dict(rec)
            status_badge, status_msg, is_alert = OilTrackingService.calculate_status(item)
            item['status_badge'] = status_badge
            item['status_msg'] = status_msg
            item['is_alert'] = is_alert
            processed_records.append(item)

        return processed_records

    @staticmethod
    def get_record_by_id(record_id):
        """جلب سجل معين بواسطة المعرف لغرض الطباعة والتقرير"""
        OilTrackingModel.init_db()
        conn = OilTrackingModel.get_db_connection()
        record = conn.execute("SELECT * FROM oil_change_tracking WHERE id = ?", (record_id,)).fetchone()
        conn.close()
        return record

    @staticmethod
    def get_all_vehicles():
        """جلب أرقام لوحات المركبات من جدول المركبات الأساسي"""
        conn = OilTrackingModel.get_db_connection()
        try:
            vehicles = conn.execute("SELECT plate_number FROM vehicles").fetchall()
            vehicle_plates = [v['plate_number'] for v in vehicles]
        except Exception:
            vehicle_plates = []
        conn.close()
        return vehicle_plates

    @staticmethod
    def get_all_team_members():
        """جلب أسماء فريق العمل/الفنيين"""
        conn = OilTrackingModel.get_db_connection()
        team_members = []
        possible_tables = ['team', 'workshop_team', 'team_members']
        for table in possible_tables:
            try:
                res = conn.execute(f"SELECT full_name FROM {table} WHERE full_name IS NOT NULL AND full_name != ''").fetchall()
                if res:
                    team_members = [r['full_name'] for r in res]
                    break
            except Exception:
                continue
        conn.close()
        return team_members

    @staticmethod
    def calculate_status(rec):
        """حساب التنبيهات بناءً على حد الإنذار المخصص من قبل الفني"""
        current = int(rec.get('current_mileage') or 0)
        last = int(rec.get('last_oil_mileage') or 0)
        interval = int(rec.get('distance_interval') or 5000)
        dist_threshold = int(rec.get('distance_alert_threshold') or 1000)
        
        mode = rec.get('tracking_mode', 'distance')
        
        if mode != 'time' and last > 0:
            target = last + interval
            remaining = target - current
            
            if remaining < 0:
                return ('danger', f'🚨 انتهت المهلة! تجاوز الحد بـ {abs(remaining)} كم', True)
            elif remaining <= dist_threshold:
                return ('warning', f'⚠️ اقترب الموعد! متبقي {remaining} كم', True)
            else:
                return ('success', f'✅ سليم (متبقي {remaining} كم)', False)

        if mode == 'time':
            time_months = int(rec.get('time_interval_months') or 3)
            time_threshold = int(rec.get('time_alert_threshold') or 15)
            return ('info', f'📅 تتبع زمني (كل {time_months} أشهر)', False)

        return ('secondary', 'غير محدد', False)

    @staticmethod
    def create_record(form_data):
        OilTrackingModel.init_db()
        conn = OilTrackingModel.get_db_connection()
        cursor = conn.cursor()
        
        doc_num = f"REQ-OIL-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        try:
            distance_interval = int(form_data.get('distance_interval', 5000))
        except ValueError:
            distance_interval = 5000

        try:
            time_interval_months = int(form_data.get('time_interval_months', 3))
        except ValueError:
            time_interval_months = 3

        try:
            dist_threshold = int(form_data.get('distance_alert_threshold', 1000))
        except ValueError:
            dist_threshold = 1000

        try:
            time_threshold = int(form_data.get('time_alert_threshold', 15))
        except ValueError:
            time_threshold = 15

        cursor.execute("""
            INSERT INTO oil_change_tracking 
            (vehicle_plate, technician_name, service_date, current_mileage, last_oil_mileage, 
             distance_interval, time_interval_months, distance_alert_threshold, time_alert_threshold, 
             tracking_mode, notes, document_number)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            form_data.get('vehicle_plate'),
            form_data.get('technician_name'),
            form_data.get('service_date', datetime.now().strftime('%Y-%m-%d')),
            form_data.get('current_mileage'),
            form_data.get('last_oil_mileage'),
            distance_interval,
            time_interval_months,
            dist_threshold,
            time_threshold,
            form_data.get('tracking_mode', 'distance'),
            form_data.get('notes'),
            doc_num
        ))
        
        conn.commit()
        conn.close()
        return True