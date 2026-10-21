import click

from app import create_app
from config import settings

app = create_app()


@app.cli.command("reset-db")
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
def reset_db_command(yes):
    """Drop all tables and recreate them fresh."""
    from utils.reset_db import confirm, reset_database

    if not confirm(yes):
        raise click.Abort()
    dropped, created = reset_database()
    click.echo(f"Dropped {dropped} tables, created {created} tables.")


if __name__ == "__main__":
    from waitress import serve
    from modules.notifications.services.email_digest_service import (
        start_weekly_digest_scheduler,
    )

    # تغيير القيمة الافتراضية إلى 0.0.0.0 لتكون متاحة للاتصالات الخارجية على المنصات السحابية
    scheduler = start_weekly_digest_scheduler()
    try:
        serve(app, host=settings.HOST, port=settings.PORT)
    finally:
        scheduler.shutdown(wait=False)