from datetime import datetime

from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError

from core.database import get_session
from modules.vehicles import repository as vehicles_repository
from modules.workshop.oil_tracking.oil_orm import OilChangeRecord
from utils.data_types import parse_non_negative_integer
from .oil_tracking_models import OilTrackingModel

class OilTrackingService:
    @staticmethod
    def get_all_records():
        OilTrackingModel.init_db()
        with get_session() as session:
            records = [r.to_dict() for r in session.scalars(
                select(OilChangeRecord).order_by(OilChangeRecord.id.desc())
            )]

        processed_records = []
        for item in records:
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
        with get_session() as session:
            record = session.get(OilChangeRecord, record_id)
            return record.to_dict() if record else None

    @staticmethod
    def delete_record(record_id):
        OilTrackingModel.init_db()
        with get_session() as session:
            result = session.execute(delete(OilChangeRecord).where(OilChangeRecord.id == record_id))
            return result.rowcount > 0

    @staticmethod
    def get_all_vehicles():
        """جلب أرقام لوحات المركبات من جدول المركبات الأساسي"""
        try:
            return [v['plate_number'] for v in vehicles_repository.list_active()]
        except Exception:
            return []

    @staticmethod
    def get_all_team_members():
        """جلب أسماء فريق العمل/الفنيين"""
        with get_session() as session:
            for table in ('team', 'workshop_team', 'team_members'):
                has_column = session.execute(text(
                    "SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() "
                    "AND table_name = :t AND column_name = 'full_name'"
                ), {'t': table}).first()
                if not has_column:
                    continue
                names = session.execute(text(
                    f"SELECT full_name FROM {table} WHERE full_name IS NOT NULL AND full_name != ''"
                )).scalars().all()
                if names:
                    return list(names)
        return []

    @staticmethod
    def calculate_status(rec):
        """حساب التنبيهات بناءً على حد الإنذار المخصص من قبل الفني"""
        try:
            current = parse_non_negative_integer(rec.get('current_mileage'), 'قراءة العداد')
            last = parse_non_negative_integer(rec.get('last_oil_mileage'), 'عداد آخر تغيير زيت')
            interval = parse_non_negative_integer(
                rec.get('distance_interval') or 5000, 'فاصل المسافة', minimum=1
            )
            dist_threshold = parse_non_negative_integer(
                1000 if rec.get('distance_alert_threshold') in (None, '')
                else rec.get('distance_alert_threshold'),
                'حد تنبيه المسافة',
            )
            time_months = parse_non_negative_integer(
                rec.get('time_interval_months') or 3, 'الفاصل الزمني', minimum=1
            )
            time_threshold = parse_non_negative_integer(
                15 if rec.get('time_alert_threshold') in (None, '')
                else rec.get('time_alert_threshold'),
                'حد تنبيه الوقت',
            )
        except ValueError:
            return ('danger', 'بيانات العداد أو فواصل الصيانة غير صالحة؛ يلزم تصحيح السجل.', True)

        mode = rec.get('tracking_mode', 'distance')
        
        if mode != 'time' and last is not None:
            if current is None:
                return ('secondary', 'سجّل قراءة العداد الحالية لتفعيل تنبيه المسافة', False)
            target = last + interval
            remaining = target - current
            
            if remaining < 0:
                return ('danger', f'🚨 انتهت المهلة! تجاوز الحد بـ {abs(remaining)} كم', True)
            elif remaining <= dist_threshold:
                return ('warning', f'⚠️ اقترب الموعد! متبقي {remaining} كم', True)
            else:
                return ('success', f'✅ سليم (متبقي {remaining} كم)', False)

        if mode == 'time':
            return ('info', f'📅 تتبع زمني (كل {time_months} أشهر)', False)

        return ('secondary', 'غير محدد', False)

    @staticmethod
    def create_record(form_data):
        OilTrackingModel.init_db()
        doc_num = f"REQ-OIL-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        try:
            tracking_mode = form_data.get('tracking_mode', 'distance')
            if tracking_mode not in {'distance', 'time', 'both'}:
                raise ValueError('نمط تتبع تغيير الزيت غير صالح.')
            service_date = form_data.get('service_date') or datetime.now().strftime('%Y-%m-%d')
            try:
                datetime.strptime(service_date, '%Y-%m-%d')
            except ValueError:
                raise ValueError('تاريخ خدمة تغيير الزيت غير صالح.') from None

            current_mileage = parse_non_negative_integer(
                form_data.get('current_mileage'), 'قراءة العداد'
            )
            last_oil_mileage = parse_non_negative_integer(
                form_data.get('last_oil_mileage'),
                'عداد آخر تغيير زيت',
                required=tracking_mode in {'distance', 'both'},
            )
            distance_interval = parse_non_negative_integer(
                form_data.get('distance_interval') or 5000, 'فاصل المسافة', minimum=1
            )
            time_interval_months = parse_non_negative_integer(
                form_data.get('time_interval_months') or 3, 'الفاصل الزمني', minimum=1
            )
            dist_threshold = parse_non_negative_integer(
                form_data.get('distance_alert_threshold') or 1000, 'حد تنبيه المسافة'
            )
            time_threshold = parse_non_negative_integer(
                form_data.get('time_alert_threshold') or 15, 'حد تنبيه الوقت'
            )

            with get_session() as session:
                session.add(OilChangeRecord(
                    vehicle_plate=form_data.get('vehicle_plate'),
                    technician_name=form_data.get('technician_name'),
                    service_date=service_date,
                    current_mileage=current_mileage,
                    last_oil_mileage=last_oil_mileage,
                    distance_interval=distance_interval,
                    time_interval_months=time_interval_months,
                    distance_alert_threshold=dist_threshold,
                    time_alert_threshold=time_threshold,
                    tracking_mode=tracking_mode,
                    notes=form_data.get('notes'),
                    document_number=doc_num,
                ))
            return True
        except IntegrityError as error:
            raise ValueError('بيانات سجل تغيير الزيت غير صالحة أو غير مكتملة.') from error