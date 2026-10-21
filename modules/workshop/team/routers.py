import sys
from pathlib import Path
from flask import Blueprint, flash, jsonify, render_template, request, redirect
import logging
from utils.expiry_status import get_expiry_status
from modules.workshop.team import team_service

# 🌟 إضافة المسار الجذري لاستيراد مكتبة التصدير الموحدة لسيماكم
base_dir_path = Path(__file__).parent.parent.parent.parent
if str(base_dir_path) not in sys.path:
    sys.path.append(str(base_dir_path))

try:
    from utils.excel_export import generate_semacom_excel
except ImportError:
    generate_semacom_excel = None

# تحديد مسار مجلد القوالب الخاص بموديول فريق العمل مباشرة
module_dir = Path(__file__).parent
template_dir = module_dir / "views"

team_bp = Blueprint(
    "team", 
    __name__, 
    url_prefix="/workshop/team",
    template_folder=str(template_dir)
)


def apply_license_status(members):
    updated_members = []
    for row in members:
        member = dict(row)
        status = get_expiry_status(
            member["license_expiry_date"], "ساري", "قارب على الانتهاء", "منتهية"
        )
        member["license_status"] = status
        updated_members.append(member)
    return updated_members

@team_bp.route("/")
def team_index():
    search_query = request.args.get("q", "").strip()
    fields = team_service.list_fields()
    members = apply_license_status(team_service.list_members(search_query))

    # تم التحديث إلى team_index.html لتفادي التداخل
    return render_template("team_index.html", members=members, fields=fields)

@team_bp.route("/add")
def add_member():
    # تم التحديث إلى team_add.html لتفادي التداخل
    return render_template("team_add.html", fields=team_service.list_fields())


@team_bp.route('/check-duplicate')
def check_duplicate_member():
    field = request.args.get('field', '')
    value = (request.args.get('value') or '').strip()
    labels = {'full_name': 'الاسم الكامل', 'national_id': 'رقم الهوية'}
    if field not in labels:
        return jsonify({'duplicate': False, 'message': ''}), 400
    if not value:
        return jsonify({'duplicate': False, 'message': ''})
    duplicate = team_service.is_duplicate(field, value)
    return jsonify({
        'duplicate': duplicate,
        'message': f'{labels[field]} مسجل مسبقًا.' if duplicate else '',
    })

@team_bp.route("/save", methods=["POST"])
def save_member():
    base_fields = [
        "full_name",
        "national_id",
        "nationality",
        "phone",
        "job_title",
        "qualification",
        "specialization",
        "license_number",
        "license_type",
        "license_issue_date",
        "license_expiry_date",
    ]

    data = {bf: request.form.get(bf) for bf in base_fields}
    data['full_name'] = str(data.get('full_name') or '').strip()
    data['national_id'] = str(data.get('national_id') or '').strip()
    data["license_status"] = get_expiry_status(
        data.get("license_expiry_date"), "ساري", "قارب على الانتهاء", "منتهية"
    )

    # استقبال الحقول الديناميكية المضافة من المستخدم
    custom_names = request.form.getlist("custom_name[]")
    custom_labels = request.form.getlist("custom_label[]")
    custom_values = request.form.getlist("custom_value[]")
    custom_requireds = request.form.getlist("custom_required[]")

    if not data['full_name'] or not data['national_id']:
        return render_template(
            'team_add.html', fields=team_service.list_fields(),
            error='الاسم الكامل ورقم الهوية مطلوبان.', form_data=data
        )

    custom_fields = []
    for i in range(len(custom_names)):
        c_name = custom_names[i].strip()
        if not c_name:
            continue
        c_label = custom_labels[i].strip() if i < len(custom_labels) else c_name
        c_val = custom_values[i].strip() if i < len(custom_values) else ''
        c_req = custom_requireds[i] if i < len(custom_requireds) else 0
        custom_fields.append((c_name, c_label, c_val, c_req))

    try:
        team_service.add_member(data, custom_fields)
    except team_service.DuplicateMemberError as ex:
        message = 'الاسم الكامل مسجل مسبقًا.' if ex.field == 'full_name' else 'رقم الهوية مسجل مسبقًا.'
        return render_template(
            'team_add.html', fields=team_service.list_fields(), error=message, form_data=data
        )
    except Exception:
        logging.exception("Unable to save team member")
        flash('تعذر حفظ بيانات عضو فريق العمل. تحقق من البيانات وحاول مجددًا.', 'danger')

    return redirect("/workshop/team")

@team_bp.route("/delete/<int:member_id>", methods=["POST"])
def delete_member(member_id):
    try:
        if not team_service.delete_member(member_id):
            flash('عضو فريق العمل المطلوب غير موجود.', 'warning')
    except Exception:
        logging.exception("Unable to delete team member %s", member_id)
        flash('تعذر حذف عضو فريق العمل. حاول مجددًا.', 'danger')

    return redirect("/workshop/team")

@team_bp.route("/export")
def export_team_excel():
    """🌟 مسار تصدير بيانات فريق الورشة والصيانة إلى ملف Excel مع دعم البحث"""
    search_query = request.args.get("q", "").strip()
    members = apply_license_status(team_service.list_members(search_query))

    if not generate_semacom_excel:
        return "مكتبة توليد الإكسل غير متوفرة", 500
        
    headers = [
        "#", "الاسم الكامل", "رقم الهوية", "الجنسية", "رقم الجوال",
        "المسمى الوظيفي", "التخصص", "رقم الرخصة", "نوع الرخصة",
        "تاريخ الإصدار", "تاريخ الانتهاء", "حالة الرخصة"
    ]
    data = []
    
    for i, member in enumerate(members, start=1):
        data.append([
            i,
            member["full_name"] or "-",
            member["national_id"] or "-",
            member["nationality"] or "-",
            member["phone"] or "-",
            member["job_title"] or "-",
            member["specialization"] or "-",
            member["license_number"] or "-",
            member["license_type"] or "-",
            member["license_issue_date"] or "-",
            member["license_expiry_date"] or "-",
            member["license_status"] or "غير محدد"
        ])
        
    return generate_semacom_excel("workshop_team_report", headers, data)
