from datetime import datetime
from flask import render_template, request, redirect, url_for, flash
from .oil_tracking_service import OilTrackingService
from utils.excel_export import generate_semacom_excel

class OilTrackingController:
    @staticmethod
    def list_records():
        records = OilTrackingService.get_all_records()
        return render_template('oil_tracking_list.html', records=records, active_tab='oil_tracking')

    @staticmethod
    def add_record():
        if request.method == 'POST':
            OilTrackingService.create_record(request.form)
            flash('تم حفظ سجل تغيير الزيت بنجاح', 'success')
            return redirect(url_for('workshop.oil_tracking.list'))

        vehicles = OilTrackingService.get_all_vehicles()
        team_members = OilTrackingService.get_all_team_members()
        return render_template('oil_tracking_add.html', vehicles=vehicles, team_members=team_members, active_tab='oil_tracking')

    @staticmethod
    def print_report(id):
        """عرض وطباعة تقرير تغيير الزيت والفلتر"""
        record = OilTrackingService.get_record_by_id(id)
        if not record:
            return "سجل تغيير الزيت غير موجود", 404

        return render_template(
            'oil_tracking_print.html',
            record=record,
            document_number=record['document_number'] or f"REQ-OIL-{record['id']}",
            report_date_gregorian=datetime.now().strftime('%Y/%m/%d')
        )

    @staticmethod
    def export_excel():
        """تصدير سجلات الزيوت باستخدام قالب Excel الموحد للنظام."""
        records = OilTrackingService.get_all_records()
        headers = [
            "م",
            "رقم اللوحة",
            "الفني المسؤول",
            "تاريخ الخدمة",
            "نمط التتبع",
            "قراءة العداد الحالية (كم)",
            "قراءة العداد عند آخر تغيير زيت (كم)",
            "الفاصل المحدد",
            "حد الإنذار",
            "حالة الزيت والتنبيه",
            "ملاحظات",
        ]
        data = []
        for index, rec in enumerate(records, start=1):
            mode = rec.get('tracking_mode', 'distance')
            if mode == 'distance':
                tracking_text = f"مسافة ({rec.get('distance_interval', 5000)} كم)"
            elif mode == 'time':
                tracking_text = f"وقت ({rec.get('time_interval_months', 3)} أشهر)"
            else:
                tracking_text = "مسافة أو وقت"

            if mode == 'time':
                threshold_text = f"{rec.get('time_alert_threshold', 15)} يوم"
            else:
                threshold_text = f"{rec.get('distance_alert_threshold', 1000)} كم"

            data.append([
                index,
                rec.get('vehicle_plate', ''),
                rec.get('technician_name', ''),
                rec.get('service_date', ''),
                tracking_text,
                rec.get('current_mileage', ''),
                rec.get('last_oil_mileage', ''),
                (
                    f"{rec.get('time_interval_months', 3)} أشهر"
                    if mode == 'time'
                    else f"{rec.get('distance_interval', 5000)} كم"
                ),
                threshold_text,
                rec.get('status_msg', 'سليم'),
                rec.get('notes', '-') or '-'
            ])
        return generate_semacom_excel("سجلات تغيير الزيوت", headers, data)