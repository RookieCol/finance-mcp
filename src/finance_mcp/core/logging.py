"""Structured logging setup shared by every entry point (MCP server, web UI,
scheduler). JSON output, one correlation ID per request/tool-call/scheduler
run, threaded through via structlog's contextvars so nested calls into
core/ inherit it without explicit passing.
"""

import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import structlog


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", level=level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]


@contextmanager
def correlation_id(existing: str | None = None) -> Iterator[str]:
    """Bind a correlation ID to all log calls made within this context.

    One ID per request/tool-call/scheduler-run — pass ``existing`` to
    propagate an ID received from a caller instead of minting a new one.
    """
    cid = existing or str(uuid.uuid4())
    structlog.contextvars.bind_contextvars(correlation_id=cid)
    try:
        yield cid
    finally:
        structlog.contextvars.unbind_contextvars("correlation_id")
