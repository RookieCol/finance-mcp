"""FastAPI application: the internal UI (Stage 6) — dashboard, manual
transaction/budget CRUD, alert acknowledgement — sharing the same
`core/` validation and storage the MCP tools (Stage 4) use.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import sqlalchemy as sa
import uvicorn
from fastapi import FastAPI
from prometheus_client import make_asgi_app

from finance_mcp.config import get_settings
from finance_mcp.core import db
from finance_mcp.core.logging import configure_logging
from finance_mcp.core.tracing import configure_tracing
from finance_mcp.web.routes import router


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    configure_tracing(settings.otel_exporter_otlp_endpoint, settings.otel_exporter_otlp_headers)
    db.init_engine(settings.database_url)
    yield


app = FastAPI(title="finance-mcp — internal UI", lifespan=lifespan)
app.include_router(router)
app.mount("/metrics", make_asgi_app())


@app.get("/healthz")
def healthz() -> dict[str, str]:
    engine = db.get_engine()
    if engine is None:  # pragma: no cover - only true before lifespan runs
        return {"status": "not_ready"}
    try:
        with engine.connect() as conn:
            conn.execute(sa.text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - exercised via integration test
        return {"status": "error", "detail": str(exc)}
    return {"status": "ok"}


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "finance_mcp.web.app:app", host=settings.ui_host, port=settings.ui_port, reload=False
    )


if __name__ == "__main__":
    main()
