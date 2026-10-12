import io
import os
from datetime import datetime
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.drawing.image import Image
from flask import send_file

def generate_semacom_excel(title, headers, data):
    """
    دالة موحدة لتوليد ملفات Excel بتصميم احترافي يتماشى مع هوية شركة SEMACOM
    يدعم اللغة العربية، اتجاه RTL، الترووسة الرسمية، شعار الشركة (بحجم مضاعف)، والألوان.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = title[:30]
    
    # تفعيل اتجاه الكتابة من اليمين لليسار (RTL)
    ws.sheet_view.rightToLeft = True
    
    # تنسيقات الألوان والخطوط الرسمية (هوية SEMACOM)
    primary_color = "1F4E78"
    header_fill = PatternFill(start_color=primary_color, end_color=primary_color, fill_type="solid")
    header_font = Font(name="Cairo", size=11, bold=True, color="FFFFFF")
    
    main_title_font = Font(name="Cairo", size=11, bold=True, color="1F4E78")
    sub_title_font = Font(name="Cairo", size=9, bold=True, color="333333")
    eng_title_font = Font(name="Arial", size=9, bold=True, color="333333")
    meta_font = Font(name="Cairo", size=9, italic=True, color="595959")
    
    border_thin = Border(
        left=Side(style='thin', color='D9D9D9'),
        right=Side(style='thin', color='D9D9D9'),
        top=Side(style='thin', color='D9D9D9'),
        bottom=Side(style='thin', color='D9D9D9')
    )
    
    zebra_fill = PatternFill(start_color="F9FBFD", end_color="F9FBFD", fill_type="solid")
    
    max_col_letter = get_column_letter(len(headers)) if headers else 'E'
    
    # 1. ترويسة الشركة الرسمية (الصفوف من 1 إلى 4)
    ws.merge_cells(f'A1:{max_col_letter}1')
    ws['A1'] = "الشركة السعودية للكهرباء والتبريد للاستثمار (سيماكم)"
    ws['A1'].font = main_title_font
    ws['A1'].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 22
    
    ws.merge_cells(f'A2:{max_col_letter}2')
    ws['A2'] = "شركة ذات مسئولية محدودة رأس مالها 4,000,000 ريال مدفوعة بالكامل"
    ws['A2'].font = sub_title_font
    ws['A2'].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[2].height = 18
    
    ws.merge_cells(f'A3:{max_col_letter}3')
    ws['A3'] = "Saudi Electricity & Cooling Investment Company (SEMACOM)."
    ws['A3'].font = eng_title_font
    ws['A3'].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[3].height = 18
    
    ws.merge_cells(f'A4:{max_col_letter}4')
    ws['A4'] = "س.ب 4031029523 رقم العضوية: 20200118234"
    ws['A4'].font = meta_font
    ws['A4'].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[4].height = 18
    
    # 2. عنوان التقرير وتاريخ التصدير (الصف الخامس)
    ws.merge_cells(f'A5:{max_col_letter}5')
    export_date = datetime.now().strftime('%Y-%m-%d %H:%M')
    ws['A5'] = f"تقرير: {title} | تاريخ التصدير: {export_date}"
    ws['A5'].font = meta_font
    ws['A5'].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[5].height = 20
    ws.row_dimensions[6].height = 10  # مسافة فارغة لتنسيق المظهر
    
    # محاولة إضافة شعار الشركة بحجم مضاعف (ضعف الحجم السابق)
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        parent_dir = os.path.dirname(current_dir)
        
        logo_paths = [
            os.path.join(current_dir, "logo.jpg"),
            os.path.join(parent_dir, "logo.jpg"),
            "logo.jpg",
            "assets/logo.jpg"
        ]
        
        logo_path = None
        for path in logo_paths:
            if os.path.exists(path):
                logo_path = path
                break
                
        if logo_path:
            img = Image(logo_path)
            # مضاعفة الارتفاع للضعف (164 بكسل) مع الحفاظ على التناسب الطردي للأبعاد
            original_width = img.width
            original_height = img.height
            target_height = 100  
            img.height = target_height
            img.width = int(target_height * (original_width / original_height))
            
            ws.add_image(img, 'A1')
        else:
            print("تحذير: لم يتم العثور على ملف الشعار logo.jpg في المسارات المحتملة.")
    except Exception as e:
        print(f"خطأ أثناء إدراج الشعار: {e}")
    
    # 3. ترويسة أعمدة الجدول (الصف السابع)
    header_row = 7
    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=header_row, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border_thin
    ws.row_dimensions[header_row].height = 26
    
    # 4. تعبئة بيانات الجدول
    start_row = 8
    for row_idx, row_data in enumerate(data, start=start_row):
        is_even = (row_idx % 2 == 0)
        for col_idx, val in enumerate(row_data, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=val if val is not None else "-")
            cell.font = Font(name="Cairo", size=10)
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = border_thin
            if is_even:
                cell.fill = zebra_fill
        ws.row_dimensions[row_idx].height = 20
        
    # 5. ضبط عرض الأعمدة تلقائياً ليناسب المحتوى
    for col_idx in range(1, len(headers) + 1):
        col_letter = get_column_letter(col_idx)
        max_len = 0
        for row in range(7, ws.max_row + 1):
            cell_val = ws.cell(row=row, column=col_idx).value
            val_str = str(cell_val or '')
            if len(val_str) > max_len:
                max_len = len(val_str)
        ws.column_dimensions[col_letter].width = max(max_len + 6, 16)
        
    # الحفظ في ذاكرة مؤقتة للإرسال المباشر للمتصفح
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    
    filename = f"SEMACOM_{title}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename
    )