# 1. استخدام صورة Python الرسمية
FROM python:3.11-slim

# 2. منع بايثون من كتابة ملفات pyc وضمان إخراج السجلات مباشرة
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# 3. تثبيت المكتبات البرمجية الخاصة بالنظام والمطلوبة لمكتبة WeasyPrint والخطوط العربية
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    python3-pip \
    python3-setuptools \
    python3-wheel \
    python3-cffi \
    libcairo2 \
    libpango-1.0-0 \
    pangocairo \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info \
    fonts-dejavu-core \
    fonts-kacst \
    fonts-freefont-ttf \
    && rm -rf /var/lib/apt/lists/*

# 4. تحديد مجلد العمل
WORKDIR /app

# 5. نسخ ملف المكتبات وتثبيتها
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# 6. نسخ بقية كود المشروع
COPY . /app/

# 7. تعيين المنفذ الافتراضي الخاص بـ Google Cloud Run
ENV PORT=8080
EXPOSE 8080

# 8. أمر تشغيل التطبيق عبر Gunicorn
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 main:app