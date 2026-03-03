from __future__ import annotations

from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from typing import Any
from urllib.parse import urlparse

from src.p0_runtime.runtime import P0Runtime


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


class _RuntimeHandler(BaseHTTPRequestHandler):
    runtime: P0Runtime

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/v1/runtime/snapshot":
            _json_response(self, 200, self.runtime.snapshot())
            return

        _json_response(self, 404, {"error": "not_found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        body = json.loads(raw_body or "{}")

        if parsed.path == "/api/v1/auth/token":
            res = self.runtime.issue_token(
                user_id=str(body.get("user_id", "")),
                role=str(body.get("role", "viewer")),
                now=_parse_time(body.get("now")),
            )
            _json_response(self, 200, res)
            return

        if parsed.path.startswith("/api/v1/viewer-sessions/") and parsed.path.endswith("/join"):
            stream_id = parsed.path[len("/api/v1/viewer-sessions/") : -len("/join")]
            res = self.runtime.viewer_join(stream_id=stream_id, now=_parse_time(body.get("now")))
            _json_response(self, 200, res)
            return

        if parsed.path.startswith("/api/v1/viewer-sessions/") and parsed.path.endswith("/leave"):
            stream_id = parsed.path[len("/api/v1/viewer-sessions/") : -len("/leave")]
            res = self.runtime.viewer_leave(stream_id=stream_id, now=_parse_time(body.get("now")))
            _json_response(self, 200, res)
            return

        if parsed.path == "/api/v1/events":
            event_raw = dict(body.get("event", {}))
            res = self.runtime.ingest_event(event_raw, now=_parse_time(body.get("now")))
            _json_response(self, int(res.get("status", 202)), res)
            return

        _json_response(self, 404, {"error": "not_found"})


def create_server(host: str = "127.0.0.1", port: int = 18080) -> ThreadingHTTPServer:
    runtime = P0Runtime(webhook_url="https://example.com/hook", webhook_token="token")

    class Handler(_RuntimeHandler):
        pass

    Handler.runtime = runtime
    return ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    host = os.getenv("P0_RUNTIME_HOST", "127.0.0.1")
    port = int(os.getenv("P0_RUNTIME_PORT", "18080"))
    server = create_server(host=host, port=port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
