import os
from core import database as dbapi
import qrcode
import math
import mimetypes
import warnings
import base64
from datetime import datetime
from urllib.parse import unquote, urlparse
from PIL import Image, ImageOps, UnidentifiedImageError
from flask import request, url_for
from config import settings

# تحديد المسار الرئيسي للمشروع (SEMACOM_Fleet_System)
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../'))

# المسار المباشر لمجلد الاستاتيك المعتمد: SEMACOM_Fleet_System/app/static/uploads/qrcodes
QR_DIR = os.path.join(BASE_DIR, 'app', 'static', 'uploads', 'qrcodes')
REPORTS_DIR = os.path.join(BASE_DIR, 'app', 'static', 'uploads', 'reports')

# إنشاء مجلد qrcodes تلقائياً إذا لم يكن موجوداً
os.makedirs(QR_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)


def init_report_counter_db():
    """إنشاء جداول التقارير والتسلسل والمستندات المعتمدة من نماذج ORM"""
    from sqlalchemy import select, text

    from core.database import engine, get_session, sync_columns
    from modules.reports.models.report_orm import (
        ApprovedDocument,
        DocumentSequence,
        GeneratedReport,
        ReportTemplate,
    )

    for model in (DocumentSequence, ApprovedDocument, GeneratedReport, ReportTemplate):
        model.__table__.create(bind=engine, checkfirst=True)
    sync_columns()

    with get_session() as session:
        if session.scalars(select(DocumentSequence.id).limit(1)).first() is None:
            session.add(DocumentSequence(id=1, last_number=0))
            # explicit id: advance the SERIAL so later inserts don't collide
            session.flush()
            session.execute(text(
                "SELECT setval(pg_get_serial_sequence('document_sequence', 'id'), "
                "GREATEST((SELECT MAX(id) FROM document_sequence), 1))"
            ))

        session.execute(text(
            "UPDATE approved_documents SET reference_number = doc_number "
            "WHERE reference_number IS NULL AND is_finalized = 1"
        ))
        session.execute(text(
            "UPDATE generated_reports SET is_finalized = 1, reference_number = doc_number "
            "WHERE doc_number IN (SELECT doc_number FROM approved_documents WHERE is_finalized = 1)"
        ))


def generate_reference_number() -> str:
    """
    الدالة الأولى: توليد رقم مرجعي تسلسلي موحد بتركيب No.000000
    """
    from sqlalchemy import select

    from core.database import get_session
    from modules.reports.models.report_orm import DocumentSequence

    init_report_counter_db()
    with get_session() as session:
        # row lock makes the increment atomic across concurrent requests
        sequence = session.scalars(
            select(DocumentSequence).where(DocumentSequence.id == 1).with_for_update()
        ).first()
        if sequence is None:
            sequence = DocumentSequence(id=1, last_number=0)
            session.add(sequence)
        sequence.last_number = (sequence.last_number or 0) + 1
        seq_num = sequence.last_number

    # صياغة الرقم المرجعي المتسلسل الموحد: No.000001
    return f"No.{seq_num:06d}"


def generate_document_qr(
    doc_number: str,
    doc_type: str = "general",
    item_id: str = "1",
    access_token: str = None
) -> str:
    """
    الدالة الثانية: توليد QR Code وحفظه في app/static/uploads/qrcodes/
    """
    try:
        host_url = request.host_url.rstrip('/')
    except RuntimeError:
        host_url = settings.DEFAULT_BASE_URL

    try:
        if access_token:
            target_url = url_for(
                'reports.public_view_document', doc_number=doc_number,
                token=access_token, _external=True
            )
        else:
            target_url = url_for(
                'reports.final_report', doc_number=doc_number, _external=True
            )
    except RuntimeError:
        target_url = (
            f"{host_url}/reports/public/view/{doc_number}?token={access_token}"
            if access_token else f"{host_url}/reports/final/{doc_number}"
        )
    
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(target_url)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="#1b365d", back_color="white")
    
    # حفظ الملف في مسار static المعتمد
    clean_doc_num = doc_number.replace('.', '_').replace('-', '_')
    filename = f"qr_{clean_doc_num}.png"
    filepath = os.path.join(QR_DIR, filename)
    img.save(filepath)
    
    # إرجاع المسار النسبي المستعمل في قوالب Flask
    return f"/static/uploads/qrcodes/{filename}"


def merge_report_images(image_sources, output_path, canvas_size=(1800, 1100)):
    """Create one full-bleed image from the final image sources selected in preview."""
    images = []
    valid_sources = image_sources or []

    for source in valid_sources:
        if not source or not os.path.exists(source):
            continue
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(source) as image:
                    if image.width * image.height > 40_000_000:
                        raise ValueError('حجم أبعاد الصورة يتجاوز الحد المسموح')
                    image.load()
                    images.append(ImageOps.exif_transpose(image).convert('RGB'))
        except (FileNotFoundError, UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
            continue
        except Image.DecompressionBombWarning:
            continue

    if not images:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        placeholder = Image.new('RGB', canvas_size, 'white')
        placeholder.save(output_path, format='JPEG', quality=92, optimize=True)
        return output_path

    width, height = canvas_size
    columns = 1 if len(images) == 1 else 2
    rows = math.ceil(len(images) / columns)
    cell_width = width // columns
    cell_height = height // rows
    canvas = Image.new('RGB', (width, height), 'white')
    for index, image in enumerate(images):
        last_odd_image = columns == 2 and len(images) % 2 == 1 and index == len(images) - 1
        x = 0 if last_odd_image else (index % columns) * cell_width
        y = (index // columns) * cell_height
        target_width = width if last_odd_image or columns == 1 else cell_width
        target_height = height - y if index // columns == rows - 1 else cell_height
        fitted = ImageOps.fit(
            image,
            (target_width, target_height),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5)
        )
        canvas.paste(fitted, (x, y))
        image.close()

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    canvas.save(output_path, format='JPEG', quality=92, optimize=True)
    return output_path


def render_report_pdf(html, output_path, base_url):
    try:
        from weasyprint import HTML
    except Exception as error:
        raise RuntimeError(
            'WeasyPrint is installed, but its native Pango/GTK libraries are unavailable'
        ) from error

    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        pdf_bytes = HTML(
            string=html,
            base_url=base_url
        ).write_pdf()
        with open(output_path, 'wb') as pdf_file:
            pdf_file.write(pdf_bytes)
    except Exception as error:
        raise RuntimeError(f'تعذر تجهيز ملف PDF: {error}') from error
    return output_path


class ReportsService:
    def fetch_report_data_by_type(self, template_key: str, params: dict) -> dict:
        """تجهيز البيانات الافتراضية للتقرير (الحفاظ على الدالة القديمة)"""
        return {
            "title": "تقرير معتمد",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "params": params
        }

    def process_and_archive_report(self, template_key: str, params: dict) -> dict:
        """توليد الرقم المرجعي الموحد والـ QR وتأكيد عملية الحفظ والأرشفة"""
        doc_number = generate_reference_number()
        item_id = str(params.get('id') or params.get('accident_id') or '1')
        qr_url = generate_document_qr(doc_number, template_key, item_id)
        
        return {
            "status": "success",
            "doc_number": doc_number,
            "qr_code_url": qr_url,
            "message": "تم إنشـاء التقرير المعتمد بنجاح"
        }