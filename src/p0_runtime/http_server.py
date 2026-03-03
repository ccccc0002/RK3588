from __future__ import annotations

from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from typing import Any, Callable
from urllib.parse import urlparse

from src.p0_runtime.runtime import P0Runtime


def _ok(data: dict, meta: dict | None = None) -> dict:
    return {"success": True, "data": data, "error": None, "meta": meta or {}}


def _err(code: str, message: str, details: dict | None = None, meta: dict | None = None) -> dict:
    return {
        "success": False,
        "data": None,
        "error": {"code": code, "message": message, "details": details or {}},
        "meta": meta or {},
    }


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


def _sender_for_mode(mode: str | None) -> Callable[[object], bool] | None:
    normalized = (mode or "real").strip().lower()
    if normalized == "real":
        return None
    if normalized == "always_success":
        return lambda _task: True
    if normalized == "always_fail":
        return lambda _task: False
    return None


class _RuntimeHandler(BaseHTTPRequestHandler):
    runtime: P0Runtime

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/v1/runtime/snapshot":
            _json_response(self, 200, _ok(self.runtime.snapshot()))
            return

        if parsed.path == "/api/v1/metrics":
            _json_response(self, 200, _ok(self.runtime.get_metrics()))
            return

        if parsed.path == "/api/v1/devices":
            _json_response(self, 200, _ok({"items": self.runtime.list_devices()}))
            return

        if parsed.path == "/api/v1/push/worker/status":
            _json_response(self, 200, _ok(self.runtime.push_worker_status()))
            return

        _json_response(self, 404, _err("not_found", "endpoint not found"))

    def do_POST(self) -> None:
        try:
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
                _json_response(self, 200, _ok(res))
                return

            if parsed.path == "/api/v1/devices/register":
                res = self.runtime.register_device(dict(body))
                _json_response(self, 200, _ok(res))
                return

            if parsed.path.startswith("/api/v1/viewer-sessions/") and parsed.path.endswith("/join"):
                stream_id = parsed.path[len("/api/v1/viewer-sessions/") : -len("/join")]
                res = self.runtime.viewer_join(stream_id=stream_id, now=_parse_time(body.get("now")))
                _json_response(self, 200, _ok(res))
                return

            if parsed.path.startswith("/api/v1/viewer-sessions/") and parsed.path.endswith("/leave"):
                stream_id = parsed.path[len("/api/v1/viewer-sessions/") : -len("/leave")]
                res = self.runtime.viewer_leave(stream_id=stream_id, now=_parse_time(body.get("now")))
                _json_response(self, 200, _ok(res))
                return

            if parsed.path == "/api/v1/events":
                event_raw = dict(body.get("event", {}))
                res = self.runtime.ingest_event(event_raw, now=_parse_time(body.get("now")))
                status = int(res.get("status", 202))
                if status >= 400:
                    _json_response(self, status, _err("event_rejected", str(res.get("reason", "event_rejected")), details=res))
                else:
                    _json_response(self, status, _ok(res))
                return

            if parsed.path == "/api/v1/push/dispatch":
                limit = int(body.get("limit", 20))
                mode = str(body.get("mode", "real"))
                sender = _sender_for_mode(mode)
                res = self.runtime.dispatch_pushes(now=_parse_time(body.get("now")), sender=sender, max_items=limit)
                _json_response(self, 200, _ok(res))
                return

            if parsed.path == "/api/v1/push/worker/start":
                interval_ms = int(body.get("interval_ms", 500))
                limit = int(body.get("limit", 20))
                mode = str(body.get("mode", "real"))
                sender = _sender_for_mode(mode)
                res = self.runtime.start_push_worker(
                    interval_seconds=max(0.01, interval_ms / 1000.0),
                    max_items=limit,
                    sender=sender,
                )
                _json_response(self, 200, _ok(res))
                return

            if parsed.path == "/api/v1/push/worker/stop":
                res = self.runtime.stop_push_worker()
                _json_response(self, 200, _ok(res))
                return

            _json_response(self, 404, _err("not_found", "endpoint not found"))
        except json.JSONDecodeError:
            _json_response(self, 400, _err("invalid_json", "request body must be valid JSON"))
        except ValueError as exc:
            _json_response(self, 400, _err("bad_request", str(exc)))
        except Exception:
            _json_response(self, 500, _err("internal_error", "unexpected server error"))


def create_server(host: str = "127.0.0.1", port: int = 18080, storage_db_path: str | None = None) -> ThreadingHTTPServer:
    runtime = P0Runtime(webhook_url="https://example.com/hook", webhook_token="token", storage_db_path=storage_db_path)

    class Handler(_RuntimeHandler):
        pass

    Handler.runtime = runtime
    return ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    host = os.getenv("P0_RUNTIME_HOST", "127.0.0.1")
    port = int(os.getenv("P0_RUNTIME_PORT", "18080"))
    db_path = os.getenv("P0_RUNTIME_DB_PATH", "").strip() or None
    server = create_server(host=host, port=port, storage_db_path=db_path)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        runtime = getattr(server.RequestHandlerClass, "runtime", None)
        if runtime is not None:
            runtime.close()


if __name__ == "__main__":
    main()
