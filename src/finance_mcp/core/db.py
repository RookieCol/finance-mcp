"""Session factory shared by the MCP server, web UI, and scheduler.

Repository functions (``core.repository``) only ``flush()`` — they never
commit — so the caller controls transaction boundaries. ``session_scope``
is that boundary: commit on success, rollback on any exception.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def init_engine(database_url: str) -> Engine:
    global _engine, _session_factory
    _engine = create_engine(database_url)
    _session_factory = sessionmaker(bind=_engine)
    return _engine


@contextmanager
def session_scope() -> Iterator[Session]:
    if _session_factory is None:
        raise RuntimeError("init_engine() must be called before session_scope()")
    session = _session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
