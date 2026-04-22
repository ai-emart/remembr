# Observability

Remembr can export OpenTelemetry traces and metrics to any OTLP-compatible collector with one configuration change:

```env
OTEL_ENABLED=true
OTEL_EXPORTER_ENDPOINT=http://localhost:4317
```

## What Remembr Emits

Traces:
- FastAPI request spans
- SQLAlchemy database spans
- Redis spans
- HTTPX client spans
- Celery worker spans
- Custom spans:
  - `memory.search`
  - `embedding.generate`
  - `webhook.deliver`

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

Resource attributes:
- `service.name`
- `service.version`
- `deployment.environment`

## Collector Example

Point Remembr at your collector:

```env
OTEL_ENABLED=true
OTEL_SERVICE_NAME=remembr
OTEL_EXPORTER_ENDPOINT=http://otel-collector:4317
OTEL_TRACES_SAMPLE_RATE=1.0
```

Example `otel-collector-config.yaml`:

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
  otlphttp/honeycomb:
    endpoint: https://api.honeycomb.io
    headers:
      x-honeycomb-team: ${HONEYCOMB_API_KEY}
  datadog:
    api:
      key: ${DD_API_KEY}
      site: datadoghq.com
  prometheusremotewrite:
    endpoint: http://grafana:9090/api/v1/write

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [debug, otlphttp/honeycomb, datadog]
    metrics:
      receivers: [otlp]
      processors: [batch]
      exporters: [debug, prometheusremotewrite, datadog]
```

## Dashboard Mapping

Grafana:
- Trace volume by `service.name=remembr`
- P95 `remembr_search_duration_ms`
- `remembr_embedding_queue_depth` for worker backlog
- `remembr_memory_count` split by `org_id`

Datadog:
- APM service: `remembr`
- Timeseries for `remembr_searches_total` by `mode`
- Timeseries for `remembr_embeddings_generated_total` by `provider`, `model`, `status`
- Monitor on `remembr_webhooks_delivered_total{status:failed}`

Honeycomb:
- Query `name=memory.search` and break down by `mode`
- Query `name=embedding.generate` and break down by `provider` and `model`
- Query `name=webhook.deliver` and break down by `event`

## Notes

- If `OTEL_ENABLED=false`, Remembr does not configure exporters or auto-instrumentation.
- Remembr uses OTLP gRPC, so the endpoint should usually be something like `http://collector:4317`.
- The embedding queue depth metric is refreshed every 15 seconds from Redis.
- `remembr_cache_hit_rate` is a rolling one-minute ratio based on cache hits and misses observed in-process.
