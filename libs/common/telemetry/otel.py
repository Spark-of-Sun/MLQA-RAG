from __future__ import annotations

import os

from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Tracer

# Shared span names across the gateway -> retrieval -> generation ->
# citation_validator path, so traces line up in Grafana/Datadog without
# each service inventing its own naming (docs/architecture.md §10).
SPAN_NAMES = {
    "gateway_query": "gateway.query",
    "ingestion_process_document": "ingestion.process_document",
    "retrieval_search": "retrieval.search",
    "generation_generate": "generation.generate",
    "citation_validator_validate": "citation_validator.validate",
}

# First-class dashboards/alerts per docs/architecture.md §10 — not generic
# uptime metrics.
METRIC_NAMES = {
    "citation_pass_rate": "legalmed.citation.pass_rate",
    "retrieval_latency_ms": "legalmed.retrieval.latency_ms",
    "token_spend": "legalmed.generation.token_spend",
    "ingestion_queue_depth": "legalmed.ingestion.queue_depth",
}


def configure_tracing(service_name: str) -> None:
    """No-op unless ENABLE_TRACING=true and OTEL_EXPORTER_OTLP_ENDPOINT is
    set — local dev runs without a collector by default.
    """
    if os.environ.get("ENABLE_TRACING", "false").lower() != "true":
        return

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return

    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter,
    )

    provider = TracerProvider(
        resource=Resource.create({SERVICE_NAME: service_name})
    )
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
    )
    trace.set_tracer_provider(provider)


def get_tracer(name: str) -> Tracer:
    return trace.get_tracer(name)

