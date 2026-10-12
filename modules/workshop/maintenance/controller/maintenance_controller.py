import datetime
from flask import render_template, request, redirect, url_for, flash
from modules.workshop.maintenance.services.maintenance_services import MaintenanceService
from utils.excel_export import generate_semacom_excel

TYPE_TITLES = {
    'internal': 'الصيانة الداخلية',
    'external': 'الصيانة الخارجية',
    'emergency': 'الصيانة الطارئة',
    'exceptional': 'الصيانة الاستثنائية'
}


class MaintenanceController:

    @staticmethod
    def _resolve_url(endpoint_suffix, **kwargs):
        """دالة مساعدة لحل مسار الصفحة تلقائياً لتجنب أخطاء BuildError وضمان إعادة التوجيه"""
        endpoints = [
            f'workshop.maintenance.{endpoint_suffix}',
            f'maintenance.{endpoint_suffix}',
            endpoint_suffix
        ]
        for ep in endpoints:
            try:
                return url_for(ep, **kwargs)
            except Exception:
                continue
        # مسار افتراضي احتياطي في حال فشل الربط التلقائي
        m_type = kwargs.get('m_type', 'internal')
        status = kwargs.get('status', 'open')
        return f"/workshop/maintenance/list/{m_type}?status={status}"

    @staticmethod
    def _enrich_orders(orders):
        """دالة مساعدة لربط كود المركبة ورقم اللوحة واسم السائق بكل أمر صيانة تلقائياً"""
        if not orders:
            return

        # 1. جلب خريطة المركبات
        try:
            vehicles = MaintenanceService.get_all_vehicles() or []
        except Exception as e:
            print(f"[Maintenance Controller Warning - Vehicles Fetch]: {e}")
            vehicles = []

        vehicles_map = {}
        for v in vehicles:
            if isinstance(v, dict):
                v_id = str(v.get('id', ''))
            else:
                v_id = str(getattr(v, 'id', ''))
            if v_id:
                vehicles_map[v_id] = v

        # 2. جلب خريطة السائقين لربط driver_id بالاسم
        try:
            drivers = MaintenanceService.get_all_drivers() or []
        except Exception as e:
            print(f"[Maintenance Controller Warning - Drivers Fetch]: {e}")
            drivers = []

        drivers_map = {}
        for d in drivers:
            if isinstance(d, dict):
                d_id = str(d.get('id') or d.get('driver_id') or '')
                d_name = d.get('name') or d.get('driver_name') or ''
            else:
                d_id = str(getattr(d, 'id', None) or getattr(d, 'driver_id', None) or '')
                d_name = getattr(d, 'name', None) or getattr(d, 'driver_name', None) or ''
            if d_id and d_name:
                drivers_map[d_id] = d_name

        # 3. إثراء بيانات الأوامر
        for order in orders:
            # --- أ. ربط المركبة ---
            if isinstance(order, dict):
                v_id = str(order.get('vehicle_id', ''))
            else:
                v_id = str(getattr(order, 'vehicle_id', ''))

            v = vehicles_map.get(v_id)

            disp_code = None
            disp_plate = None

            if v:
                if isinstance(v, dict):
                    disp_code = v.get('code') or v.get('vehicle_code') or v.get('id')
                    disp_plate = v.get('plate_number') or v.get('plate_no') or v.get('vehicle_plate')
                else:
                    disp_code = getattr(v, 'code', None) or getattr(v, 'vehicle_code', None) or getattr(v, 'id', None)
                    disp_plate = getattr(v, 'plate_number', None) or getattr(v, 'plate_no', None) or getattr(v, 'vehicle_plate', None)

            if not disp_code:
                if isinstance(order, dict):
                    disp_code = order.get('vehicle_code') or order.get('code') or order.get('vehicle_id') or '—'
                else:
                    disp_code = getattr(order, 'vehicle_code', None) or getattr(order, 'code', None) or getattr(order, 'vehicle_id', '—')

            if not disp_plate:
                if isinstance(order, dict):
                    disp_plate = order.get('plate_number') or order.get('plate_no') or order.get('vehicle_plate') or '—'
                else:
                    disp_plate = getattr(order, 'plate_number', None) or getattr(order, 'plate_no', None) or getattr(order, 'vehicle_plate', '—')

            disp_code_str = str(disp_code) if disp_code is not None else '—'
            disp_plate_str = str(disp_plate) if disp_plate is not None else '—'

            # --- ب. ربط اسم السائق ---
            if isinstance(order, dict):
                d_id = str(order.get('driver_id', ''))
                existing_driver = order.get('driver_name') or order.get('driver')
            else:
                d_id = str(getattr(order, 'driver_id', ''))
                existing_driver = getattr(order, 'driver_name', None) or getattr(order, 'driver', None)

            disp_driver_str = '—'
            if isinstance(existing_driver, str) and existing_driver and not existing_driver.isdigit():
                disp_driver_str = existing_driver
            elif isinstance(existing_driver, dict):
                disp_driver_str = existing_driver.get('name') or existing_driver.get('driver_name') or '—'
            elif hasattr(existing_driver, 'name'):
                disp_driver_str = getattr(existing_driver, 'name', '—')
            elif hasattr(existing_driver, 'driver_name'):
                disp_driver_str = getattr(existing_driver, 'driver_name', '—')

            if disp_driver_str in ['—', ''] and d_id in drivers_map:
                disp_driver_str = drivers_map[d_id]

            # إسناد القيم المجهزة للأمر
            if isinstance(order, dict):
                order['disp_code'] = disp_code_str
                order['disp_plate'] = disp_plate_str
                order['vehicle_code'] = disp_code_str
                order['plate_number'] = disp_plate_str
                order['disp_driver'] = disp_driver_str
                order['driver_name'] = disp_driver_str
            else:
                setattr(order, 'disp_code', disp_code_str)
                setattr(order, 'disp_plate', disp_plate_str)
                setattr(order, 'vehicle_code', disp_code_str)
                setattr(order, 'plate_number', disp_plate_str)
                setattr(order, 'disp_driver', disp_driver_str)
                setattr(order, 'driver_name', disp_driver_str)

    @staticmethod
    def get_index():
        """إحصائيات الواجهة الرئيسية"""
        types = ['internal', 'external', 'emergency', 'exceptional']
        stats = {}
        for t in types:
            open_orders = MaintenanceService.get_orders(t, status='open')
            closed_orders = MaintenanceService.get_orders(t, status='closed')
            stats[t] = {
                'open': len(open_orders),
                'closed': len(closed_orders),
                'total': len(open_orders) + len(closed_orders)
            }
        return render_template('maintenance_index.html', stats=stats, type_titles=TYPE_TITLES)

    @staticmethod
    def get_list(m_type):
        """عرض القائمة مع إرفاق كود المركبة ورقم اللوحة واسم السائق"""
        if m_type not in TYPE_TITLES:
            flash('نوع الصيانة غير صحيح أو غير مدعوم.', 'danger')
            return redirect(MaintenanceController._resolve_url('maintenance_index'))

        status = request.args.get('status', 'open')
        orders = MaintenanceService.get_orders(m_type, status=status)

        # 👈 ربط كود المركبة ورقم اللوحة واسم السائق التلقائي بكل أمر صيانة
        MaintenanceController._enrich_orders(orders)

        return render_template(
            'maintenance_list.html',
            orders=orders,
            m_type=m_type,
            type_title=TYPE_TITLES.get(m_type, 'الصيانة'),
            current_status=status
        )

    @staticmethod
    def get_all_list():
        filters = {
            'type': request.args.get('type', 'all'),
            'status': request.args.get('status', 'all'),
            'date_from': request.args.get('date_from', ''),
            'date_to': request.args.get('date_to', '')
        }
        orders = MaintenanceService.get_all_orders(
            m_type=filters['type'],
            status=filters['status'],
            date_from=filters['date_from'],
            date_to=filters['date_to']
        )
        MaintenanceController._enrich_orders(orders)
        return render_template(
            'maintenance_all.html',
            orders=orders,
            filters=filters,
            type_titles=TYPE_TITLES
        )

    @staticmethod
    def add_order(m_type):
        """إضافة أمر صيانة جديد"""
        if m_type not in TYPE_TITLES:
            flash('نوع الصيانة غير صالح.', 'danger')
            return redirect(MaintenanceController._resolve_url('maintenance_index'))

        if request.method == 'POST':
            try:
                data = request.form.to_dict()
                data['type'] = m_type
                order_no = MaintenanceService.create_order(data)
                flash(f'تم إنشاء أمر الصيانة بنجاح برقم: {order_no}', 'success')
                return redirect(MaintenanceController._resolve_url('maintenance_list', m_type=m_type, status='open'))
            except Exception as e:
                print(f"[Maintenance Controller Error - Add]: {e}")
                flash(f'حدث خطأ أثناء حفظ أمر الصيانة: {str(e)}', 'danger')

        vehicles = MaintenanceService.get_all_vehicles()
        team_members = MaintenanceService.get_all_team_members()
        drivers = MaintenanceService.get_all_drivers()

        template_map = {
            'external': 'external_add.html',
            'emergency': 'emergency_add.html',
            'exceptional': 'exceptional_add.html'
        }
        template_name = template_map.get(m_type, 'maintenance_add.html')

        return render_template(
            template_name,
            m_type=m_type,
            type_title=TYPE_TITLES.get(m_type, 'الصيانة'),
            vehicles=vehicles,
            team_members=team_members,
            drivers=drivers
        )

    @staticmethod
    def close_order(order_id):
        """إقفال أمر الصيانة ونقله للأرشيف"""
        order = MaintenanceService.get_order_by_id(order_id)
        if not order:
            flash('أمر الصيانة المطلوب غير موجود.', 'warning')
            return redirect(MaintenanceController._resolve_url('maintenance_index'))

        m_type = order.get('type', 'internal') if isinstance(order, dict) else getattr(order, 'type', 'internal')

        if request.method == 'POST':
            try:
                close_data = request.form.to_dict()
                files = request.files
                MaintenanceService.close_order(order_id, close_data, files)
                order_no = order.get("order_no") if isinstance(order, dict) else getattr(order, "order_no", order_id)
                flash(f'تم إقفال أمر الصيانة {order_no} بنجاح ونقله للأرشيف.', 'success')
                return redirect(MaintenanceController._resolve_url('maintenance_list', m_type=m_type, status='open'))
            except Exception as e:
                print(f"[Maintenance Controller Error - Close]: {e}")
                flash(f'حدث خطأ أثناء إقفال أمر الصيانة: {str(e)}', 'danger')

        template_map = {
            'external': 'external_close.html',
            'emergency': 'emergency_close.html',
            'exceptional': 'exceptional_close.html'
        }
        template_name = template_map.get(m_type, 'maintenance_close.html')
        current_datetime = datetime.datetime.now().strftime('%Y-%m-%dT%H:%M')

        return render_template(
            template_name,
            order=order,
            m_type=m_type,
            type_title=TYPE_TITLES.get(m_type, 'الصيانة'),
            current_datetime=current_datetime
        )

    @staticmethod
    def view_order(order_id):
        """عرض تفاصيل أمر الصيانة"""
        order = MaintenanceService.get_order_by_id(order_id)
        if not order:
            flash('أمر الصيانة المطلوب غير موجود.', 'warning')
            return redirect(MaintenanceController._resolve_url('maintenance_index'))

        MaintenanceController._enrich_orders([order])

        m_type = order.get('type') if isinstance(order, dict) else getattr(order, 'type', 'internal')
        return render_template(
            'maintenance_view.html',
            order=order,
            type_title=TYPE_TITLES.get(m_type, 'الصيانة')
        )

    @staticmethod
    def delete_order(order_id):
        """حذف أمر الصيانة"""
        m_type = request.form.get('m_type')
        status = request.form.get('status', 'open')
        try:
            if not m_type:
                order = MaintenanceService.get_order_by_id(order_id)
                if order:
                    m_type = order.get('type', 'internal') if isinstance(order, dict) else getattr(order, 'type', 'internal')
                else:
                    m_type = 'internal'

            MaintenanceService.delete_order(order_id)
            flash('تم حذف أمر الصيانة بنجاح.', 'success')
            return redirect(MaintenanceController._resolve_url('maintenance_list', m_type=m_type, status=status))
        except Exception as e:
            print(f"[Maintenance Controller Error - Delete]: {e}")
            flash(f'حدث خطأ أثناء عملية الحذف: {str(e)}', 'danger')
            return redirect(MaintenanceController._resolve_url('maintenance_index'))

    @staticmethod
    def export_excel(m_type):
        """تصدير ملف إكسيل مطابق للحقول المرجعية مع كود المركبة ورقم اللوحة واسم السائق"""
        if m_type not in TYPE_TITLES:
            flash('نوع الصيانة غير صحيح.', 'danger')
            return redirect(MaintenanceController._resolve_url('maintenance_index'))

        status = request.args.get('status', 'open')
        orders = MaintenanceService.get_orders(m_type, status=status)
        
        # إثراء الأوامر ببيانات المركبة والسائق للتصدير
        MaintenanceController._enrich_orders(orders)

        status_label = "الأرشيف (المغلقة)" if status == 'closed' else "الأوامر المفتوحة"
        title = f"{TYPE_TITLES.get(m_type)} - {status_label}"

        type_fields = {
            'internal': [
                ("نوع الصيانة", "maintenance_type"),
                ("وصف العطل", "fault_description"),
                ("سبب العطل", "fault_cause"),
                ("درجة الخطورة", "severity"),
                ("الفني المستلم", "technician_name"),
                ("الوقت المتوقع للإنجاز", "expected_completion_time"),
                ("تاريخ أمر العمل", "order_date")
            ],
            'external': [
                ("نوع الصيانة", "maintenance_type"),
                ("وصف العطل", "fault_description"),
                ("سبب العطل", "fault_cause"),
                ("درجة الخطورة", "severity"),
                ("اسم الورشة", "workshop_name"),
                ("رقم الورشة", "workshop_phone"),
                ("موقع الورشة", "workshop_location"),
                ("سبب الإرسال", "send_reason"),
                ("وقت الإرسال", "send_datetime"),
                ("المسؤول", "responsible_person"),
                ("التكلفة المتوقعة", "expected_cost"),
                ("الوقت المتوقع", "expected_time"),
                ("ملاحظات", "notes")
            ],
            'emergency': [
                ("السائق", "disp_driver"),
                ("درجة الخطورة", "severity"),
                ("التاريخ", "incident_datetime"),
                ("الموقع", "emergency_location"),
                ("هل يوجد إصابة؟", "has_injuries"),
                ("هل المركبة قابلة للحركة؟", "is_drivable"),
                ("الجهة الحكومية المبلغة", "official_notified"),
                ("وصف الحالة", "case_description"),
                ("سبب العطل", "fault_cause")
            ],
            'exceptional': [
                ("التاريخ", "incident_datetime"),
                ("الموضوع", "subject"),
                ("الوصف", "description"),
                ("الأسباب", "causes"),
                ("تفاصيل أخرى", "other_details")
            ]
        }
        close_fields = {
            'internal': [
                ("تاريخ الإقفال", "closure_date"),
                ("سبب الإقفال", "closure_reason"),
                ("قطع الغيار المستخدمة", "spare_parts"),
                ("التكلفة النهائية", "final_cost"),
                ("التوصيات", "recommendation")
            ],
            'external': [
                ("تاريخ الإقفال", "closure_date"),
                ("تاريخ الاستلام", "receipt_datetime"),
                ("سبب الإقفال", "closure_reason"),
                ("قطع الغيار المستخدمة", "spare_parts"),
                ("التوصيات", "recommendation"),
                ("ملاحظات الإقفال", "closing_notes")
            ],
            'emergency': [
                ("الإجراءات الفورية", "action_taken"),
                ("هل تم السحب؟", "is_towed"),
                ("جهة السحب", "towing_party"),
                ("فريق التدخل", "intervention_team"),
                ("التكلفة النهائية", "final_cost"),
                ("قطع الغيار المستخدمة", "spare_parts"),
                ("التوصيات النهائية", "recommendation")
            ],
            'exceptional': [
                ("الإجراءات المتخذة", "action_taken"),
                ("التكلفة", "final_cost"),
                ("التوصيات", "recommendation")
            ]
        }

        fields = type_fields[m_type]
        if status == 'closed':
            fields = fields + close_fields[m_type] + [
                ("صورة قبل المعالجة", "photo_before"),
                ("صورة بعد المعالجة", "photo_after"),
                ("مرفقات أخرى", "other_attachments")
            ]

        headers = ["رقم الأمر", "كود المركبة", "رقم اللوحة"] + [label for label, _ in fields] + ["حالة الطلب"]
        rows = []
        for order in orders:
            def get_val(key, default='—'):
                value = order.get(key) if isinstance(order, dict) else getattr(order, key, None)
                return default if value in (None, '') else value

            values = []
            for _, key in fields:
                if key == "disp_driver":
                    value = get_val(key, default=None) or get_val("driver_name", default=None) or get_val("driver_id")
                elif key == "vehicle_code":
                    value = get_val("disp_code", default=None) or get_val(key)
                elif key == "plate_number":
                    value = get_val("disp_plate", default=None) or get_val(key)
                else:
                    value = get_val(key)
                values.append(value)

            rows.append([
                get_val("order_no"),
                get_val("disp_code", default=None) or get_val("vehicle_code"),
                get_val("disp_plate", default=None) or get_val("plate_number"),
                *values,
                "مغلق" if status == 'closed' else "مفتوح"
            ])

        try:
            return generate_semacom_excel(title=title, headers=headers, data=rows)
        except Exception as e:
            print(f"[Maintenance Controller Export Error]: {e}")
            flash(f'حدث خطأ أثناء تصدير الملف: {str(e)}', 'danger')
            return redirect(MaintenanceController._resolve_url('maintenance_list', m_type=m_type, status=status))