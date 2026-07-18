"""Integration test: Alembic migrations apply cleanly to a real Postgres.

Uses testcontainers rather than mocking the DB — the whole point of this
test is to catch real SQL/schema issues (enum handling, FK order, seed
data) that a mocked session would hide. Requires Docker; skipped
automatically if the Docker daemon isn't reachable (e.g. some CI runners).
"""

import subprocess

import pytest
import sqlalchemy as sa
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration


def _docker_available() -> bool:
    try:
        subprocess.run(["docker", "info"], capture_output=True, timeout=5, check=True)
    except Exception:
        return False
    return True


@pytest.mark.skipif(not _docker_available(), reason="Docker daemon not available")
def test_migrations_apply_and_seed_categories() -> None:
    with PostgresContainer("postgres:17-alpine") as postgres:
        database_url = postgres.get_connection_url().replace(
            "postgresql+psycopg2", "postgresql+psycopg"
        )

        subprocess.run(
            ["uv", "run", "alembic", "upgrade", "head"],
            env={"DATABASE_URL": database_url, "PATH": _system_path()},
            check=True,
            capture_output=True,
            text=True,
        )

        engine = sa.create_engine(database_url)
        with engine.connect() as conn:
            tables = sa.inspect(conn).get_table_names()
            for expected in (
                "transactions",
                "categories",
                "budgets",
                "alert_events",
                "audit_log",
            ):
                assert expected in tables

            rows = conn.execute(sa.text("SELECT key, type FROM categories ORDER BY key")).fetchall()
            keys = {row.key for row in rows}
            assert keys == {
                "cogs",
                "sales",
                "marketing",
                "rd",
                "ga",
                "subscription",
                "services",
                "other",
            }

        # Downgrade must be a true inverse: no leftover tables or enum types.
        subprocess.run(
            ["uv", "run", "alembic", "downgrade", "base"],
            env={"DATABASE_URL": database_url, "PATH": _system_path()},
            check=True,
            capture_output=True,
            text=True,
        )
        with engine.connect() as conn:
            remaining_tables = [
                t for t in sa.inspect(conn).get_table_names() if t != "alembic_version"
            ]
            assert remaining_tables == []
            leftover_enums = conn.execute(
                sa.text(
                    "SELECT typname FROM pg_type WHERE typname IN "
                    "('transaction_type','transaction_source','category_type',"
                    "'audit_action','audit_actor','alert_severity')"
                )
            ).fetchall()
            assert leftover_enums == []


def _system_path() -> str:
    import os

    return os.environ.get("PATH", "")
