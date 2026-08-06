"""Idempotent migration runner: applies db/migrations/*.sql in filename order,
recording each in schema_migrations. Safe to run on every deploy.

Usage: python -m scripts.migrate
"""
import pathlib

from src import db

MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parents[1] / "db" / "migrations"


def run():
    conn = db.get_conn()
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute("""create table if not exists schema_migrations (
                             version text primary key,
                             applied_at timestamptz not null default now())""")
            cur.execute("select version from schema_migrations")
            applied = {r[0] for r in cur.fetchall()}
        conn.commit()
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in applied:
                continue
            with conn.cursor() as cur:
                cur.execute(path.read_text())
                cur.execute("insert into schema_migrations (version) values (%s)",
                            (path.name,))
            conn.commit()
            print(f"applied {path.name}")
        print("migrations up to date")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    run()
