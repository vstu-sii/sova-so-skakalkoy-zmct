import json
import logging
import os
import uuid

from fastapi import Request
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import Counter, Histogram
from prometheus_fastapi_instrumentator import Instrumentator

LIMITS = Counter("extractor_limit_decisions", "Budget and authorization decisions", ["decision", "reason"])
TOKENS = Counter("extractor_llm_tokens", "Tokens reported by Ollama", ["tier", "direction"])
FAILURES = Counter("extractor_llm_failures", "Model failures by tier", ["tier"])
CALLS = Histogram("extractor_llm_duration_seconds", "Ollama latency including response read", ["tier"],
                  buckets=(.25, .5, 1, 2, 5, 10, 20, 45, 90, 180))
UNACCOUNTED = Counter("extractor_llm_unaccounted", "Calls with unknown token counts", ["tier"])
for tier in ("standard", "economy"):
    for direction in ("input", "output"):
        TOKENS.labels(tier, direction)
    CALLS.labels(tier)
    FAILURES.labels(tier)
    UNACCOUNTED.labels(tier)
for decision in ("degraded", "rejected"):
    for reason in ("requests", "tokens"):
        LIMITS.labels(decision, reason)
LIMITS.labels("denied", "authorization")
logger = logging.getLogger("uvicorn.error")
provider = TracerProvider(resource=Resource.create({"service.name": "extractor"}))
endpoint = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
if endpoint:
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, timeout=3)))
tracer = provider.get_tracer("event-platform.extractor")


def log_event(event, **fields):
    span = trace.get_current_span().get_span_context()
    logger.info(json.dumps(dict(event=event, service="extractor",
        trace_id=f"{span.trace_id:032x}" if span.is_valid else None, **fields),
        ensure_ascii=False))


def setup(app):
    @app.middleware("http")
    async def trace_request(request: Request, call_next):
        if request.url.path != "/extract":
            return await call_next(request)
        request.state.request_id = str(uuid.uuid4())
        with tracer.start_as_current_span("POST /extract", kind=trace.SpanKind.SERVER) as span:
            span.set_attribute("app.request_id", request.state.request_id)
            response = await call_next(request)
            span.set_attribute("http.response.status_code", response.status_code)
            response.headers["X-Trace-ID"] = f"{span.get_span_context().trace_id:032x}"
            response.headers["X-Request-ID"] = request.state.request_id
            return response

    Instrumentator(excluded_handlers=["/metrics", "/health"]).instrument(app).expose(app, include_in_schema=False)
