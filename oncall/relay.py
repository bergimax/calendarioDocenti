"""
Alert -> on-call agent relay (stdlib only, runs next to the observability stack).

Grafana's webhook contact point posts alerts here. For each *firing* alert the relay
adds context an agent needs and cannot fetch itself (the telemetry stack is not on the
public internet): the most recent error logs with their trace ids, pulled from Loki.
It then wakes the on-call agent by sending a GitHub `repository_dispatch` event
(`alert`), which runs .github/workflows/oncall-agent.yml.

Without GITHUB_TOKEN it runs in dry-run mode: the payload that *would* be sent is
logged and kept at GET /last, so the whole chain can be demonstrated locally.

Privacy: only log lines already scrubbed by the backend (see app/observability.py) are
forwarded; lines are truncated and capped.
"""

import json
import logging
import os
import sys
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional

log = logging.getLogger("oncall-relay")

LOKI_URL = os.environ.get("LOKI_URL", "http://lgtm:3100")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "bergimax/calendarioDocenti")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GRAFANA_URL = os.environ.get("GRAFANA_PUBLIC_URL", "http://localhost:3001")
DEDUP_SECONDS = int(os.environ.get("DEDUP_SECONDS", "1800"))
MAX_LOG_LINES = 10
MAX_LINE_CHARS = 1500

_last_sent: Dict[str, float] = {}
_last_payload: Optional[Dict[str, Any]] = None


def fetch_error_logs(lookback_s: int = 900) -> List[Dict[str, str]]:
    """Most recent ERROR logs of the backend from Loki: [{ts, line, trace_id}]."""
    now = time.time_ns()
    params = urllib.parse.urlencode({
        "query": '{service_name="calendario-backend"} | detected_level="error"',
        "start": now - lookback_s * 1_000_000_000,
        "end": now,
        "limit": MAX_LOG_LINES,
        "direction": "backward",
    })
    try:
        with urllib.request.urlopen(f"{LOKI_URL}/loki/api/v1/query_range?{params}", timeout=10) as resp:
            data = json.load(resp)
    except Exception as exc:  # Loki down must not block waking the agent
        log.warning("could not fetch logs from Loki: %s", exc)
        return []
    entries = []
    for stream in data.get("data", {}).get("result", []):
        for value in stream.get("values", []):
            metadata = value[2].get("structured_metadata", {}) if len(value) > 2 and isinstance(value[2], dict) else {}
            entries.append({
                "ts": value[0],
                "line": value[1][:MAX_LINE_CHARS],
                "trace_id": metadata.get("trace_id", stream.get("stream", {}).get("trace_id", "")),
                "stacktrace": str(metadata.get("exception_stacktrace") or stream.get("stream", {}).get("exception_stacktrace", ""))[:MAX_LINE_CHARS * 2],
            })
    entries.sort(key=lambda e: e["ts"], reverse=True)
    return entries[:MAX_LOG_LINES]


def build_dispatch(alert: Dict[str, Any], logs: List[Dict[str, str]]) -> Dict[str, Any]:
    """The `repository_dispatch` body for one firing alert."""
    labels = alert.get("labels", {})
    annotations = alert.get("annotations", {})
    trace_ids = sorted({e["trace_id"] for e in logs if e.get("trace_id")})
    return {
        "event_type": "alert",
        "client_payload": {
            "alertname": labels.get("alertname", "unknown"),
            "severity": labels.get("severity", ""),
            "service": labels.get("service", ""),
            "journey": labels.get("journey", ""),
            "summary": annotations.get("summary", ""),
            "description": annotations.get("description", ""),
            "started_at": alert.get("startsAt", ""),
            "trace_ids": trace_ids[:5],
            "grafana_url": GRAFANA_URL,
            # JSON string: repository_dispatch limits nesting depth and property count
            "recent_error_logs": json.dumps(logs, ensure_ascii=False)[:40000],
        },
    }


def send_dispatch(body: Dict[str, Any]) -> str:
    global _last_payload
    _last_payload = body
    if not GITHUB_TOKEN:
        log.info("DRY RUN (no GITHUB_TOKEN): would dispatch %s", json.dumps(body)[:2000])
        return "dry-run"
    req = urllib.request.Request(
        f"https://api.github.com/repos/{GITHUB_REPO}/dispatches",
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        log.info("dispatched alert to GitHub: HTTP %s", resp.status)
    return "dispatched"


def handle_alerts(payload: Dict[str, Any], now: Optional[float] = None) -> List[str]:
    """Process a Grafana/Alertmanager webhook body; returns one result per firing alert."""
    now = time.time() if now is None else now
    results = []
    for alert in payload.get("alerts", []):
        if alert.get("status") != "firing":
            continue
        name = alert.get("labels", {}).get("alertname", "unknown")
        last = _last_sent.get(name)
        if last is not None and now - last < DEDUP_SECONDS:
            results.append(f"{name}: skipped (already dispatched within {DEDUP_SECONDS}s)")
            continue
        _last_sent[name] = now
        results.append(f"{name}: {send_dispatch(build_dispatch(alert, fetch_error_logs()))}")
    return results


class Handler(BaseHTTPRequestHandler):
    def _reply(self, code: int, body: Any) -> None:
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/health":
            self._reply(200, {"status": "ok"})
        elif self.path == "/last":
            self._reply(200, _last_payload or {})
        else:
            self._reply(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/alert":
            return self._reply(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            self._reply(200, {"results": handle_alerts(payload)})
        except Exception as exc:
            log.exception("failed to handle alert")
            self._reply(500, {"error": str(exc)})

    def log_message(self, fmt, *args):
        log.info("%s %s", self.address_string(), fmt % args)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    port = int(os.environ.get("PORT", "8080"))
    log.info("on-call relay listening on :%s (%s)", port, "LIVE" if GITHUB_TOKEN else "dry-run")
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
