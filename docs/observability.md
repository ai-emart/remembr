# Observability

Remembr can export OpenTelemetry traces and metrics to any OTLP-compatible collector.

## Enable it

```env
OTEL_ENABLED=true
OTEL_EXPORTER_ENDPOINT=http://otel-collector:4317
OTEL_SERVICE_NAME=remembr
OTEL_TRACES_SAMPLE_RATE=1.0
```

## What Remembr emits

Traces:

- FastAPI request spans
- SQLAlchemy database spans
- Redis spans
- HTTPX client spans
- Celery worker spans
- Custom spans such as `memory.search`, `embedding.generate`, and `webhook.deliver`

Metrics:

- `remembr_memories_stored_total{org_id}`
- `remembr_searches_total{org_id,mode}`
- `remembr_embeddings_generated_total{provider,model,status}`
- `remembr_webhooks_delivered_total{event,status}`
- `remembr_search_duration_ms{mode}`
- `remembr_embedding_generation_duration_ms{provider}`
- `remembr_embedding_queue_depth`
- `remembr_cache_hit_rate`
- `remembr_memory_count{org_id}`

## Collector example

```yaml
receivers:
  otlp:
    protocols:
      grpc:
      http:

processors:
  batch:

exporters:
  debug:
  prometheusremotewrite:
    endpoint: http://grafana:9090/api/v1/write

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [debug]
    metrics:
      receivers: [otlp]
      processors: [batch]
      exporters: [debug, prometheusremotewrite]
```

## What to watch

- Search latency by `mode`
- Worker backlog via `remembr_embedding_queue_depth`
- Error rate for webhook delivery
- Cache hit rate during hot traffic windows

## Notes

- If `OTEL_ENABLED=false`, Remembr does not configure exporters.
- OTLP gRPC usually targets port `4317`.
- Queue depth is derived from Redis-backed task state.

