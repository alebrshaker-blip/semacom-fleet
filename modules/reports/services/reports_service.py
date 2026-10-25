import os
import re
from core import database as dbapi
import qrcode
import io
import math
import mimetypes
import warnings
import base64
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse
from PIL import Image, ImageOps, UnidentifiedImageError
from flask import request, url_for
from config import settings
from core import storage

from modules.reports.typography import REPORT_FONT_FILES, get_report_typography

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../'))
TEMP_UPLOAD_DIR = os.path.join(tempfile.gettempdir(), 'semacom-fleet')
QR_DIR = os.path.join(TEMP_UPLOAD_DIR, 'qrcodes')
REPORTS_DIR = os.path.join(TEMP_UPLOAD_DIR, 'reports')

os.makedirs(QR_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)


def init_report_counter_db():
    """إنشاء جداول التقارير والتسلسل والمستندات المعتمدة من نماذج ORM"""
    from sqlalchemy import text

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
        inserted = session.execute(text(
            "INSERT INTO document_sequence (id, last_number) VALUES (1, 0) "
            "ON CONFLICT (id) DO NOTHING"
        ))
        if inserted.rowcount:
            session.execute(text("""
                UPDATE document_sequence
                SET last_number = GREATEST(
                    last_number,
                    COALESCE((
                        SELECT MAX(CAST(SUBSTRING(doc_number FROM 4) AS BIGINT))
                        FROM approved_documents
                        WHERE doc_number ~ '^No\\.[0-9]+$'
                    ), 0),
                    COALESCE((
                        SELECT MAX(CAST(SUBSTRING(doc_number FROM 4) AS BIGINT))
                        FROM generated_reports
                        WHERE doc_number ~ '^No\\.[0-9]+$'
                    ), 0)
                )
                WHERE id = 1
            """))
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
    from sqlalchemy import text

    from core.database import get_session

    init_report_counter_db()
    with get_session() as session:
        seq_num = session.execute(text(
            "UPDATE document_sequence SET last_number = last_number + 1 "
            "WHERE id = 1 RETURNING last_number"
        )).scalar_one()

    # صياغة الرقم المرجعي المتسلسل الموحد: No.000001
    return f"No.{seq_num:06d}"


def generate_document_qr(
    doc_number: str,
    doc_type: str = "general",
    item_id: str = "1",
    access_token: str = None
) -> str:
    """
    Generate a QR code and persist it in Supabase Storage.
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
    
    clean_doc_num = doc_number.replace('.', '_').replace('-', '_')
    filename = f"qr_{clean_doc_num}.png"
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    return storage.upload_bytes(
        buffer.getvalue(),
        'reports/qrcodes',
        filename,
        content_type='image/png',
        path=f"reports/qrcodes/{filename}",
        upsert=True,
    )


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
    resolved_output = os.path.realpath(output_path)
    reports_root = os.path.realpath(REPORTS_DIR)
    try:
        output_root = os.path.commonpath((reports_root, resolved_output))
    except ValueError as error:
        raise ValueError(
            'PDF reports must be written under the temporary reports directory'
        ) from error
    if output_root != reports_root:
        raise ValueError('PDF reports must be written under the temporary reports directory')
    output_path = resolved_output

    try:
        from weasyprint import HTML
    except Exception as error:
        raise RuntimeError(
            'WeasyPrint is installed, but its native Pango/GTK libraries are unavailable'
        ) from error

    try:
        static_dir = os.path.join(BASE_DIR, 'app', 'static')
        report_css_path = os.path.join(static_dir, 'css', 'report.css')
        if not os.path.isfile(report_css_path):
            raise FileNotFoundError(f'Report stylesheet not found: {report_css_path}')
        with open(report_css_path, encoding='utf-8') as css_file:
            report_css = css_file.read()
        typography = get_report_typography()
        selected_font_files = set(
            REPORT_FONT_FILES[typography['report_font_family']]
        )

        def resolve_font_face(match):
            font_face = match.group(0)
            source_match = re.search(
                r'url\(["\']?([^"\')]+)',
                font_face,
                flags=re.IGNORECASE,
            )
            if not source_match:
                return ''
            font_name = os.path.basename(source_match.group(1))
            if font_name not in selected_font_files:
                return ''
            font_path = os.path.join(static_dir, 'fonts', font_name)
            if not os.path.isfile(font_path):
                raise FileNotFoundError(f'Report font not found: {font_path}')
            return font_face.replace(
                source_match.group(1),
                Path(font_path).as_uri(),
            )

        report_css = re.sub(
            r'@font-face\s*\{[^}]*\}',
            resolve_font_face,
            report_css,
            flags=re.IGNORECASE,
        )
        report_css += (
            f"\n:root {{ --report-font-size: "
            f"{typography['report_font_size']}; }}\n"
        )
        html = re.sub(
            r'<link\b[^>]*href=["\'][^"\']*report\.css(?:\?[^"\']*)?["\'][^>]*>',
            '',
            html,
            flags=re.IGNORECASE,
        )
        body_match = re.search(r'<body\b([^>]*)>', html, flags=re.IGNORECASE)
        if body_match:
            attributes = body_match.group(1)
            class_match = re.search(
                r'\bclass=["\']([^"\']*)["\']',
                attributes,
                flags=re.IGNORECASE,
            )
            class_names = class_match.group(1).split() if class_match else []
            font_classes = {
                'font-cairo', 'font-tajawal', 'font-majalla', 'font-almarai'
            }
            class_names = [
                name for name in class_names if name not in font_classes
            ]
            class_names.append(typography['report_font_class'])
            class_attribute = f'class="{" ".join(class_names)}"'
            if class_match:
                attributes = (
                    attributes[:class_match.start()]
                    + class_attribute
                    + attributes[class_match.end():]
                )
            else:
                attributes += f' {class_attribute}'
            style_match = re.search(
                r'\bstyle=["\']([^"\']*)["\']',
                attributes,
                flags=re.IGNORECASE,
            )
            style_text = style_match.group(1) if style_match else ''
            style_text = re.sub(
                r'--report-font-size\s*:\s*[^;]+;?',
                '',
                style_text,
                flags=re.IGNORECASE,
            ).strip().rstrip(';')
            style_text = (
                f'{style_text}; ' if style_text else ''
            ) + f"--report-font-size: {typography['report_font_size']};"
            style_attribute = f'style="{style_text}"'
            if style_match:
                attributes = (
                    attributes[:style_match.start()]
                    + style_attribute
                    + attributes[style_match.end():]
                )
            else:
                attributes += f' {style_attribute}'
            html = (
                html[:body_match.start()]
                + f'<body{attributes}>'
                + html[body_match.end():]
            )
        inline_styles = f'<style>{report_css}</style>'
        if re.search(r'</head\s*>', html, flags=re.IGNORECASE):
            html = re.sub(
                r'</head\s*>',
                lambda _: f'{inline_styles}</head>',
                html,
                count=1,
                flags=re.IGNORECASE,
            )
        else:
            html = f'{inline_styles}{html}'
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        HTML(
            string=html,
            base_url=base_url
        ).write_pdf(target=output_path)
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
        """Reject the legacy API that issued references without archiving a document."""
        return {
            "status": "error",
            "message": (
                "إصدار التقارير يتم من شاشة المعاينة عبر إجراء الاعتماد؛ "
                "واجهة التوليد القديمة لا تحفظ ملف التقرير ولا يجوز استخدامها للإصدار."
            )
        }
