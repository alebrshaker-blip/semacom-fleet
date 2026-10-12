import sys
import os
from pathlib import Path
from flask import Blueprint, render_template, request, redirect, url_for
import sqlite3
from utils.expiry_status import get_expiry_status
from core.database import DB_PATH

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

def get_db_connection():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn, DB_PATH

# إنشاء الجداول تلقائياً إذا لم تكن موجودة
def init_team_db():
    conn, _ = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS team_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT,
            national_id TEXT,
            nationality TEXT,
            phone TEXT,
            job_title TEXT,
            qualification TEXT,
            specialization TEXT,
            license_number TEXT,
            license_type TEXT,
            license_issue_date TEXT,
            license_expiry_date TEXT,
            license_status TEXT DEFAULT 'غير محدد'
        )
    """)
    columns = {row["name"] for row in cur.execute("PRAGMA table_info(team_members)")}
    for name, column_type in (
        ("license_type", "TEXT"),
        ("license_status", "TEXT DEFAULT 'غير محدد'"),
    ):
        if name not in columns:
            cur.execute(f'ALTER TABLE team_members ADD COLUMN "{name}" {column_type}')
    cur.execute("""
        CREATE TABLE IF NOT EXISTS team_fields (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            label TEXT,
            required INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

init_team_db()

def apply_license_status(members, conn):
    updated_members = []
    for row in members:
        member = dict(row)
        status = get_expiry_status(
            member["license_expiry_date"], "ساري", "قارب على الانتهاء", "منتهية"
        )
        member["license_status"] = status
        conn.execute(
            "UPDATE team_members SET license_status = ? WHERE id = ?",
            (status, member["id"]),
        )
        updated_members.append(member)
    conn.commit()
    return updated_members

@team_bp.route("/")
def team_index():
    conn, _ = get_db_connection()
    cur = conn.cursor()
    
    search_query = request.args.get("q", "").strip()
    
    # جلب الحقول الديناميكية الإضافية إن وجدت
    cur.execute("SELECT * FROM team_fields")
    fields = cur.fetchall()
    
    if search_query:
        like_pattern = f"%{search_query}%"
        cur.execute("""
            SELECT * FROM team_members 
            WHERE full_name LIKE ? OR national_id LIKE ? OR phone LIKE ? OR license_number LIKE ? OR license_type LIKE ? OR specialization LIKE ?
        """, (like_pattern, like_pattern, like_pattern, like_pattern, like_pattern, like_pattern))
    else:
        cur.execute("SELECT * FROM team_members")
        
    members = cur.fetchall()
    members = apply_license_status(members, conn)
    conn.close()
    
    # تم التحديث إلى team_index.html لتفادي التداخل
    return render_template("team_index.html", members=members, fields=fields)

@team_bp.route("/add")
def add_member():
    conn, _ = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM team_fields")
    fields = cur.fetchall()
    conn.close()
    
    # تم التحديث إلى team_add.html لتفادي التداخل
    return render_template("team_add.html", fields=fields)

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
    data["license_status"] = get_expiry_status(
        data.get("license_expiry_date"), "ساري", "قارب على الانتهاء", "منتهية"
    )

    # استقبال الحقول الديناميكية المضافة من المستخدم
    custom_names = request.form.getlist("custom_name[]")
    custom_labels = request.form.getlist("custom_label[]")
    custom_values = request.form.getlist("custom_value[]")
    custom_requireds = request.form.getlist("custom_required[]")

    conn, _ = get_db_connection()
    cur = conn.cursor()

    try:
        for i in range(len(custom_names)):
            c_name = custom_names[i].strip()
            c_label = custom_labels[i].strip()
            c_val = custom_values[i].strip()
            c_req = custom_requireds[i] if i < len(custom_requireds) else 0

            if c_name:
                try:
                    cur.execute(f'ALTER TABLE team_members ADD COLUMN "{c_name}" TEXT')
                except sqlite3.OperationalError:
                    pass

                cur.execute(
                    "INSERT OR IGNORE INTO team_fields (name, label, required) VALUES (?, ?, ?)",
                    (c_name, c_label, c_req),
                )

                data[c_name] = c_val

        # بناء جملة الإدخال الديناميكي
        keys = list(data.keys())
        values = list(data.values())
        columns_str = ", ".join([f'"{k}"' for k in keys])
        placeholders_str = ", ".join(["?" for _ in keys])

        query = f"INSERT INTO team_members ({columns_str}) VALUES ({placeholders_str})"
        cur.execute(query, values)
        conn.commit()

    except Exception as ex:
        print("Error saving team member:", ex)
    finally:
        conn.close()

    return redirect("/workshop/team")

@team_bp.route("/delete/<int:member_id>", methods=["POST"])
def delete_member(member_id):
    conn, _ = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM team_members WHERE id = ?", (member_id,))
        conn.commit()
    except Exception as e:
        print("Error deleting team member:", e)
    finally:
        conn.close()

    return redirect("/workshop/team")

@team_bp.route("/export")
def export_team_excel():
    """🌟 مسار تصدير بيانات فريق الورشة والصيانة إلى ملف Excel مع دعم البحث"""
    search_query = request.args.get("q", "").strip()
    
    conn, _ = get_db_connection()
    cur = conn.cursor()
    
    if search_query:
        like_pattern = f"%{search_query}%"
        cur.execute("""
            SELECT * FROM team_members 
            WHERE full_name LIKE ? OR national_id LIKE ? OR phone LIKE ? OR license_number LIKE ? OR license_type LIKE ? OR specialization LIKE ?
        """, (like_pattern, like_pattern, like_pattern, like_pattern, like_pattern, like_pattern))
    else:
        cur.execute("SELECT * FROM team_members")
        
    members = cur.fetchall()
    members = apply_license_status(members, conn)
    conn.close()
    
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