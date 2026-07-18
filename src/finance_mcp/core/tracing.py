"""OpenTelemetry tracing setup shared by every entry point.

Console exporter by default (visible in local/dev logs); OTLP export
(e.g. to a self-hosted Langfuse, Stage 8) activates automatically when
``OTEL_EXPORTER_OTLP_ENDPOINT`` is set.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)
from opentelemetry.trace import Span, Tracer

_SERVICE_NAME = "finance-mcp"


def configure_tracing(otlp_endpoint: str | None = None) -> None:
    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: _SERVICE_NAME}))
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    if otlp_endpoint:
        # Imported lazily: the OTLP exporter package is an optional extra
        # only needed when a real collector (e.g. Langfuse, Stage 8) is
        # configured — the console exporter above always works standalone.
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))

    trace.set_tracer_provider(provider)


def get_tracer() -> Tracer:
    return trace.get_tracer(_SERVICE_NAME)


@contextmanager
def traced_operation(name: str, **attributes: str | int | float | bool) -> Iterator[Span]:
    """Wrap a core operation in a span, e.g.:

    with traced_operation("record_transaction", category="cogs"):
        ...
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(name) as span:
        for key, value in attributes.items():
            span.set_attribute(key, value)
        yield span
