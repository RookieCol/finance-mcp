"""FastAPI dependencies — a DB session per request, committed on success
and rolled back on any exception, reusing the same `core.db.session_scope`
transaction boundary the MCP tools and scheduler use.
"""

from collections.abc import Iterator

from sqlalchemy.orm import Session

from caudal.core import db


def get_db() -> Iterator[Session]:
    with db.session_scope() as session:
        yield session
