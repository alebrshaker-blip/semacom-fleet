FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1 \
    TMPDIR=/tmp \
    PORT=8080

# تثبيت الحزم والمكتبات المساعدة للرسم والـ PDF والخطوط العربية
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    python3-dev \
    python3-setuptools \
    python3-wheel \
    python3-cffi \
    libcairo2 \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libpangocairo-1.0-0 \
    libharfbuzz0b \
    libharfbuzz-subset0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    libpq-dev \
    shared-mime-info \
    fontconfig \
    fonts-dejavu \
    fonts-noto-core \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# إنشاء المستخدم العادي ومجلد السجلات والمجلدات المؤقتة ومنح الصلاحيات
RUN useradd --system --uid 10001 --create-home appuser \
    && mkdir -p /app/logs /tmp/semacom-fleet/reports /tmp/semacom-fleet/qrcodes \
    && chown -R 10001:10001 /app /tmp/semacom-fleet

# تثبيت مكتبات بايثون
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي ملفات التطبيق ومنح ملكيتها للمستخدم العادي
COPY --chown=10001:10001 . /app/

# اختبار محرك WeasyPrint للـ PDF قبل إكمال البناء
RUN python -c "from io import BytesIO; from weasyprint import HTML; output = BytesIO(); HTML(string='<html><body>PDF smoke test</body></html>').write_pdf(output); assert output.getvalue().startswith(b'%PDF-')"

USER 10001:10001

EXPOSE 8080

CMD exec gunicorn --bind :$PORT --workers 1 --threads 4 --timeout 300 --graceful-timeout 30 --keep-alive 5 main:app