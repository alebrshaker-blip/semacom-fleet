import os

from app import create_app

app = create_app()


if __name__ == "__main__":
    from waitress import serve

    # تغيير القيمة الافتراضية إلى 0.0.0.0 لتكون متاحة للاتصالات الخارجية على المنصات السحابية
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    serve(app, host=host, port=port)