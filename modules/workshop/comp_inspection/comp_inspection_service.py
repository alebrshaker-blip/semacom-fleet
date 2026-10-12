from .comp_inspection_models import CompInspectionModel
from datetime import datetime

class CompInspectionService:
    @staticmethod
    def get_all_inspections():
        CompInspectionModel.init_db()
        conn = CompInspectionModel.get_db_connection()
        inspections = conn.execute("SELECT * FROM comprehensive_inspections ORDER BY id DESC").fetchall()
        conn.close()
        return inspections

    @staticmethod
    def get_all_vehicles():
        """جلب أرقام لوحات المركبات المسجلة في النظام"""
        conn = CompInspectionModel.get_db_connection()
        try:
            vehicles = conn.execute("SELECT plate_number FROM vehicles").fetchall()
            vehicle_plates = [v['plate_number'] for v in vehicles]
        except Exception:
            vehicle_plates = []
        conn.close()
        return vehicle_plates

    @staticmethod
    def get_all_team_members():
        """جلب أسماء أعضاء فريق العمل باستخدام العمود الصحيح full_name"""
        conn = CompInspectionModel.get_db_connection()
        team_members = []
        
        # فحص الجداول المحتملة مع حقل full_name
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
    def get_inspection_by_id(inspection_id):
        conn = CompInspectionModel.get_db_connection()
        inspection = conn.execute("SELECT * FROM comprehensive_inspections WHERE id = ?", (inspection_id,)).fetchone()
        items = conn.execute("SELECT * FROM comprehensive_inspection_items WHERE inspection_id = ?", (inspection_id,)).fetchall()
        conn.close()
        return inspection, items

    @staticmethod
    def create_inspection(form_data, items_data):
        CompInspectionModel.init_db()
        conn = CompInspectionModel.get_db_connection()
        cursor = conn.cursor()
        
        doc_num = f"REQ-CINS-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        cursor.execute("""
            INSERT INTO comprehensive_inspections 
            (vehicle_plate, inspector_name, inspection_date, current_mileage, oil_change_mileage, overall_status, notes, document_number)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            form_data.get('vehicle_plate'),
            form_data.get('inspector_name'),
            form_data.get('inspection_date', datetime.now().strftime('%Y-%m-%d')),
            form_data.get('current_mileage'),
            form_data.get('oil_change_mileage'),
            form_data.get('overall_status', 'سليم'),
            form_data.get('notes'),
            doc_num
        ))
        
        inspection_id = cursor.lastrowid

        for cat, name, stat, in_note in items_data:
            cursor.execute("""
                INSERT INTO comprehensive_inspection_items (inspection_id, category, item_name, status, item_notes)
                VALUES (?, ?, ?, ?, ?)
            """, (inspection_id, cat, name, stat, in_note))

        conn.commit()
        conn.close()
        return True