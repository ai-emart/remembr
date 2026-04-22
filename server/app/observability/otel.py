"""OpenTelemetry setup and custom metrics for Remembr."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger
from opentelemetry import metrics, trace
from opentelemetry.metrics import Observation
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import (
    DEPLOYMENT_ENVIRONMENT,
    SERVICE_NAME,
    SERVICE_VERSION,
    Resource,
)
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

from app.config import get_settings

APP_VERSION = "0.1.0"


@dataclass
class _MetricHandles:
    memories_stored_total: Any | None = None
    searches_total: Any | None = None
    embeddings_generated_total: Any | None = None
    webhooks_delivered_total: Any | None = None
    search_duration_ms: Any | None = None
    embedding_generation_duration_ms: Any | None = None


@dataclass
class _OtelState:
    configured: bool = False
    tracer_provider: TracerProvider | None = None
    meter_provider: MeterProvider | None = None
    fastapi_instrumented: bool = False
    sqlalchemy_instrumented: bool = False
    redis_instrumented: bool = False
    httpx_instrumented: bool = False
    celery_instrumented: bool = False
    queue_depth: int = 0
    cache_events: deque[tuple[datetime, bool]] = field(default_factory=deque)
    memory_counts: dict[str, int] = field(default_factory=dict)
    metric_handles: _MetricHandles = field(default_factory=_MetricHandles)
    queue_task: asyncio.Task[None] | None = None
    queue_stop: asyncio.Event | None = None


_STATE = _OtelState()


def get_tracer(name: str = "app.observability") -> Any:
    """Return an OpenTelemetry tracer."""
    return trace.get_tracer(name)


def _resource(service_name: str, environment: str, version: str) -> Resource:
    return Resource.create(
        {
            SERVICE_NAME: service_name,
            SERVICE_VERSION: version,
            DEPLOYMENT_ENVIRONMENT: environment,
        }
    )


def _setup_metric_handles() -> None:
    meter = metrics.get_meter("app.observability")
    _STATE.metric_handles = _MetricHandles(
        memories_stored_total=meter.create_counter("remembr_memories_stored_total"),
        searches_total=meter.create_counter("remembr_searches_total"),
        embeddings_generated_total=meter.create_counter("remembr_embeddings_generated_total"),
        webhooks_delivered_total=meter.create_counter("remembr_webhooks_delivered_total"),
        search_duration_ms=meter.create_histogram("remembr_search_duration_ms", unit="ms"),
        embedding_generation_duration_ms=meter.create_histogram(
            "remembr_embedding_generation_duration_ms",
            unit="ms",
        ),
    )
    meter.create_observable_gauge(
        "remembr_embedding_queue_depth",
        callbacks=[_observe_queue_depth],
    )
    meter.create_observable_gauge(
        "remembr_cache_hit_rate",
        callbacks=[_observe_cache_hit_rate],
    )
    meter.create_observable_gauge(
        "remembr_memory_count",
        callbacks=[_observe_memory_count],
    )


def _observe_queue_depth(_options: Any) -> list[Observation]:
    return [Observation(_STATE.queue_depth)]


def _observe_cache_hit_rate(_options: Any) -> list[Observation]:
    cutoff = datetime.now(UTC) - timedelta(minutes=1)
    while _STATE.cache_events and _STATE.cache_events[0][0] < cutoff:
        _STATE.cache_events.popleft()

    if not _STATE.cache_events:
        return [Observation(0.0)]

    hits = sum(1 for _, hit in _STATE.cache_events if hit)
    ratio = hits / len(_STATE.cache_events)
    return [Observation(ratio)]


def _observe_memory_count(_options: Any) -> list[Observation]:
    return [
        Observation(count, {"org_id": org_id})
        for org_id, count in sorted(_STATE.memory_counts.items())
    ]


async def _poll_embedding_queue_depth(
    redis_client: Any,
    queue_name: str,
    stop_event: asyncio.Event,
) -> None:
    while not stop_event.is_set():
        try:
            _STATE.queue_depth = int(await redis_client.llen(queue_name))
        except Exception as exc:
            logger.debug("Failed to poll embedding queue depth", error=str(exc))
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=15.0)
        except TimeoutError:
            continue


def _start_queue_depth_task(redis_client: Any, queue_name: str) -> None:
    if _STATE.queue_task is not None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    stop_event = asyncio.Event()
    _STATE.queue_stop = stop_event
    _STATE.queue_task = loop.create_task(
        _poll_embedding_queue_depth(redis_client, queue_name, stop_event)
    )


def setup_otel(
    app: Any | None = None,
    *,
    engine: Any | None = None,
    redis_client: Any | None = None,
    celery_app: Any | None = None,
    span_exporter: Any | None = None,
    metric_reader: Any | None = None,
) -> bool:
    """Configure OpenTelemetry tracing, metrics, and auto-instrumentation."""
    settings = get_settings()
    if not settings.otel_enabled:
        logger.debug("OpenTelemetry disabled")
        return False

    endpoint = settings.otel_exporter_endpoint
    version = getattr(app, "version", APP_VERSION) if app is not None else APP_VERSION

    if not _STATE.configured:
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        tracer_provider = TracerProvider(
            resource=_resource(settings.otel_service_name, settings.environment, version),
            sampler=TraceIdRatioBased(settings.otel_traces_sample_rate),
        )

        if span_exporter is None and endpoint:
            span_exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)

        if span_exporter is not None:
            processor = (
                SimpleSpanProcessor(span_exporter)
                if span_exporter.__class__.__name__ == "InMemorySpanExporter"
                else BatchSpanProcessor(span_exporter)
            )
            tracer_provider.add_span_processor(processor)

        trace.set_tracer_provider(tracer_provider)

        if metric_reader is None and endpoint:
            metric_exporter = OTLPMetricExporter(endpoint=endpoint, insecure=True)
            metric_reader = PeriodicExportingMetricReader(
                metric_exporter,
                export_interval_millis=15_000,
            )

        metric_readers = [metric_reader] if metric_reader is not None else []
        meter_provider = MeterProvider(
            resource=_resource(settings.otel_service_name, settings.environment, version),
            metric_readers=metric_readers,
        )
        metrics.set_meter_provider(meter_provider)

        _STATE.configured = True
        _STATE.tracer_provider = tracer_provider
        _STATE.meter_provider = meter_provider
        _setup_metric_handles()

    if app is not None and not _STATE.fastapi_instrumented:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
        _STATE.fastapi_instrumented = True

    if engine is not None and not _STATE.sqlalchemy_instrumented:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
        _STATE.sqlalchemy_instrumented = True

    if redis_client is not None and not _STATE.redis_instrumented:
        from opentelemetry.instrumentation.redis import RedisInstrumentor

        RedisInstrumentor().instrument()
        _STATE.redis_instrumented = True

    if not _STATE.httpx_instrumented:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
        _STATE.httpx_instrumented = True

    if celery_app is not None and not _STATE.celery_instrumented:
        from opentelemetry.instrumentation.celery import CeleryInstrumentor

        CeleryInstrumentor().instrument()
        _STATE.celery_instrumented = True

    if redis_client is not None:
        queue_name = getattr(getattr(celery_app, "conf", None), "task_default_queue", "celery")
        _start_queue_depth_task(redis_client, queue_name)

    logger.info(
        "OpenTelemetry configured",
        service_name=settings.otel_service_name,
        endpoint=endpoint,
    )
    return True


async def shutdown_otel() -> None:
    """Stop background tasks and flush providers."""
    if _STATE.queue_stop is not None:
        _STATE.queue_stop.set()
    if _STATE.queue_task is not None:
        await asyncio.gather(_STATE.queue_task, return_exceptions=True)
    _STATE.queue_task = None
    _STATE.queue_stop = None

    if _STATE.meter_provider is not None:
        _STATE.meter_provider.shutdown()
    if _STATE.tracer_provider is not None:
        _STATE.tracer_provider.shutdown()


def reset_otel_state_for_tests() -> None:
    """Reset mutable OTel state used by tests."""
    _STATE.queue_depth = 0
    _STATE.cache_events.clear()
    _STATE.memory_counts.clear()
    _STATE.metric_handles = _MetricHandles()
    _STATE.queue_task = None
    _STATE.queue_stop = None
    _STATE.configured = False
    _STATE.tracer_provider = None
    _STATE.meter_provider = None
    _STATE.fastapi_instrumented = False
    _STATE.sqlalchemy_instrumented = False
    _STATE.redis_instrumented = False
    _STATE.httpx_instrumented = False
    _STATE.celery_instrumented = False


def record_memory_stored(org_id: str, count: int = 1) -> None:
    handle = _STATE.metric_handles.memories_stored_total
    if handle is not None:
        handle.add(count, {"org_id": org_id})
    increment_memory_count(org_id, count)


def record_memory_deleted(org_id: str, count: int = 1) -> None:
    increment_memory_count(org_id, -count)


def increment_memory_count(org_id: str, delta: int) -> None:
    current = _STATE.memory_counts.get(org_id, 0)
    _STATE.memory_counts[org_id] = max(current + delta, 0)


def record_search(org_id: str, mode: str, duration_ms: float) -> None:
    counter = _STATE.metric_handles.searches_total
    histogram = _STATE.metric_handles.search_duration_ms
    attributes = {"org_id": org_id, "mode": mode}
    if counter is not None:
        counter.add(1, attributes)
    if histogram is not None:
        histogram.record(duration_ms, {"mode": mode})


def record_embedding_generated(
    provider: str,
    model: str,
    status: str,
    duration_ms: float,
) -> None:
    counter = _STATE.metric_handles.embeddings_generated_total
    histogram = _STATE.metric_handles.embedding_generation_duration_ms
    attributes = {"provider": provider, "model": model, "status": status}
    if counter is not None:
        counter.add(1, attributes)
    if histogram is not None:
        histogram.record(duration_ms, {"provider": provider})


def record_webhook_delivery(event: str, status: str) -> None:
    counter = _STATE.metric_handles.webhooks_delivered_total
    if counter is not None:
        counter.add(1, {"event": event, "status": status})


def record_cache_access(hit: bool) -> None:
    _STATE.cache_events.append((datetime.now(UTC), hit))
