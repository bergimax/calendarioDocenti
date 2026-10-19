# Observability

## What is observed

The key user journey is **generating the weekly timetable** (`POST /api/schedule/generate`).
Every run produces, all tied together by one **trace ID**:

| Signal | Where it is produced | Stored in | Viewed in |
|---|---|---|---|
| **Trace** | FastAPI auto-instrumentation (request span, DB spans) + a hand-made `schedule.generate` span with `schedule.outcome`, `schedule.n_slots` | Tempo | Grafana → Explore → Tempo, dashboard panel "Recent traces" |
| **Metrics** | `schedule_generation_total{outcome}`, `schedule_generation_duration_seconds` (histogram), HTTP server metrics | Prometheus | Dashboard *User journey: weekly timetable generation* |
| **Structured logs** | JSON, one object per line, fields `ts level logger service message trace_id span_id event outcome duration_s …` (stdout **and** OTLP) | Loki | Dashboard "Journey logs"; click `trace_id` to jump to the trace |

`outcome` is one of `generated`, `infeasible`, `timeout`, `error` (user-level problem such as a
locked week) and `internal_error` (unexpected exception: a bug or an outage). Code:
[`app/observability.py`](../app/observability.py).

```
backend ──OTLP/HTTP──▶ OpenTelemetry Collector ─┬─▶ Tempo       (traces)
                                                ├─▶ Prometheus  (metrics)
                                                └─▶ Loki        (logs)
                                                          Grafana ◀── all three, plus alert rules
```

The stack runs as the `lgtm` service (`grafana/otel-lgtm`) of `docker-compose.local.yml`, so
`make up` starts it with the app. Grafana: http://localhost:3001 (anonymous, local only);
dashboard and alert rule are provisioned from [`observability/`](../observability).

Try it: `make up && make demo-data` generates a timetable, then open the dashboard. To see
the correlation, copy a `trace_id` from `docker compose -f docker-compose.local.yml logs backend`
and search it in Grafana → Explore → Tempo; the same id is on the Loki log lines.

## Privacy rules (no customer data or credentials in telemetry)

- Span attributes and metric labels contain only counters, enums and ISO week dates — never
  teacher/class names or emails.
- `JsonFormatter` and the OTLP log handler mask e-mail addresses in every message and stack trace.
- Request/response bodies and the `Authorization` header are never recorded (FastAPI
  instrumentation does not capture them; `/health` is excluded).
- Tests: `tests/test_observability.py` (`test_json_log_masks_emails_…`).

## Production

The production VM (1 GB RAM) is too small to also run the telemetry stack. There the backend
logs the same structured JSON (with trace ids) to stdout — `docker compose logs backend` — and
OTLP export stays off (`OTEL_EXPORTER_OTLP_ENDPOINT` unset). Pointing
`OTEL_EXPORTER_OTLP_ENDPOINT` at any OTLP backend (Grafana Cloud free tier, a separate VM)
enables traces and metrics with no code change.

## Alerting

See [oncall-agent.md](oncall-agent.md). One alert on user impact: **Timetable generation
failing** — any `internal_error` outcome in the last 5 minutes
(`sum(increase(schedule_generation_total{outcome="internal_error"}[5m])) > 0`).
