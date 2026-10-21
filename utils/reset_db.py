"""Drop every table and recreate the database fresh (PostgreSQL).

Usage:
    python -m utils.reset_db [--yes]
    flask --app main reset-db [--yes]
"""
import sys

from sqlalchemy import text

from core.database import engine


def drop_all():
    """Drop every table in the public schema (CASCADE handles foreign keys).

    The schema itself is kept so hosted-Postgres (e.g. Supabase) grants survive.
    """
    with engine.begin() as connection:
        names = connection.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        ).scalars().all()
        if names:
            quoted = ", ".join(engine.dialect.identifier_preparer.quote_identifier(n) for n in names)
            connection.execute(text(f"DROP TABLE IF EXISTS {quoted} CASCADE"))
    return len(names)


def reset_database():
    """drop_all() then recreate all tables inside a fresh Flask application context."""
    from app import create_app

    dropped = drop_all()
    app = create_app()  # create_app() runs all init_*_db() functions in app context
    with app.app_context():
        with engine.connect() as connection:
            created = connection.execute(
                text("SELECT COUNT(*) FROM information_schema.tables "
                     "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'")
            ).scalar()
    return dropped, created


def confirm(skip=False):
    if skip:
        return True
    target = engine.url.render_as_string(hide_password=True)
    answer = input(f"This will DELETE ALL DATA in {target}. Type 'yes' to continue: ")
    return answer.strip().lower() == "yes"


if __name__ == "__main__":
    if not confirm("--yes" in sys.argv):
        sys.exit("Aborted.")
    dropped_count, created_count = reset_database()
    print(f"Dropped {dropped_count} tables, created {created_count} tables.")
