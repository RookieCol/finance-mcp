"""Shared testcontainers Postgres fixture for integration tests.

One container per test session (migrations applied once); each test gets
its own transaction that's rolled back afterward, so tests stay isolated
without paying container-startup cost per test.
"""

import os
import subprocess
from collections.abc import Generator

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker
from testcontainers.postgres import PostgresContainer


def _docker_available() -> bool:
    try:
        subprocess.run(["docker", "info"], capture_output=True, timeout=5, check=True)
    except Exception:
        return False
    return True


requires_docker = pytest.mark.skipif(not _docker_available(), reason="Docker daemon not available")


@pytest.fixture(scope="session")
def database_url() -> Generator[str, None, None]:
    if not _docker_available():
        pytest.skip("Docker daemon not available")

    with PostgresContainer("postgres:17-alpine") as postgres:
        url = postgres.get_connection_url().replace("postgresql+psycopg2", "postgresql+psycopg")
        env = {**os.environ, "DATABASE_URL": url}
        subprocess.run(
            ["uv", "run", "alembic", "upgrade", "head"],
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        yield url


@pytest.fixture
def mcp_env(database_url: str) -> Generator[str, None, None]:
    """Wires the module-level engine `core.db` uses (the MCP tools call
    `db.session_scope()`, not a session fixture, so this initializes the
    same global the running server would) and truncates mutable tables
    before each test for isolation, since MCP tool calls auto-commit.
    """
    from caudal.core import db as db_module

    db_module.init_engine(database_url)
    engine = sa.create_engine(database_url)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "TRUNCATE transactions, audit_log, budgets, alert_events RESTART IDENTITY CASCADE"
            )
        )
    engine.dispose()
    yield database_url


@pytest.fixture
def web_env(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Generator[str, None, None]:
    """Sets DATABASE_URL in the environment (the FastAPI app's own
    lifespan reads it via `core.config.get_settings()` on startup) and
    truncates mutable tables before each test.
    """
    monkeypatch.setenv("DATABASE_URL", database_url)
    engine = sa.create_engine(database_url)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "TRUNCATE transactions, audit_log, budgets, alert_events RESTART IDENTITY CASCADE"
            )
        )
    engine.dispose()
    yield database_url


@pytest.fixture
def db_session(database_url: str) -> Generator[Session, None, None]:
    engine = sa.create_engine(database_url)
    connection = engine.connect()
    transaction = connection.begin()
    session_factory = sessionmaker(bind=connection)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()
