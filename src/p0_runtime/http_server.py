from __future__ import annotations

from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from src.p0_runtime.api_envelope import error_payload, ok_payload
from src.p0_runtime.api_policy import is_supported_role, required_get_action, required_post_action
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
    bootstrap_token: str = ""

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _bearer_token(self) -> str | None:
        auth_value = str(self.headers.get("Authorization", ""))
        if not auth_value.startswith("Bearer "):
            return None
        token = auth_value[len("Bearer ") :].strip()
        if not token:
            return None
        return token

    def _authorize(self, required_action: str) -> tuple[int | None, dict | None]:
        token = self._bearer_token()
        if token is None:
            return 401, error_payload("unauthorized", "missing bearer token")

        ok, context = self.runtime.authorize(token=token, required_action=required_action)
        if ok:
            return None, None
        if context and context.get("reason") == "forbidden":
            return (
                403,
                error_payload(
                    "forbidden",
                    "action not allowed for current role",
                    details={"required_action": required_action, "role": context.get("role")},
                ),
            )
        return 401, error_payload("invalid_token", "token invalid or expired")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        required_action = required_get_action(parsed.path)
        if required_action is not None:
            denied_status, denied_payload = self._authorize(required_action)
            if denied_status is not None:
                _json_response(self, denied_status, denied_payload or error_payload("unauthorized", "unauthorized"))
                return

        if parsed.path == "/api/v1/runtime/snapshot":
            _json_response(self, 200, ok_payload(self.runtime.snapshot()))
            return

        if parsed.path == "/api/v1/metrics":
            _json_response(self, 200, ok_payload(self.runtime.get_metrics()))
            return

        if parsed.path == "/api/v1/devices":
            _json_response(self, 200, ok_payload({"items": self.runtime.list_devices()}))
            return

        if parsed.path == "/api/v1/algorithms":
            _json_response(self, 200, ok_payload({"items": self.runtime.list_algorithms()}))
            return

        if parsed.path == "/api/v1/base-libraries":
            _json_response(self, 200, ok_payload({"items": self.runtime.list_base_libraries()}))
            return

        if parsed.path == "/api/v1/base-libraries/mappings":
            _json_response(self, 200, ok_payload({"items": self.runtime.list_base_library_mappings()}))
            return

        if parsed.path == "/api/v1/base-libraries/compatibility/policy":
            _json_response(self, 200, ok_payload(self.runtime.get_base_library_compatibility_policy()))
            return

        if parsed.path == "/api/v1/offline-executors":
            _json_response(self, 200, ok_payload({"items": self.runtime.list_offline_executors()}))
            return

        if parsed.path == "/api/v1/offline-jobs":
            _json_response(self, 200, ok_payload({"items": self.runtime.list_offline_jobs()}))
            return

        if parsed.path == "/api/v1/push/worker/status":
            _json_response(self, 200, ok_payload(self.runtime.push_worker_status()))
            return

        if parsed.path == "/api/v1/audit/recent":
            query = parse_qs(parsed.query)
            limit = int((query.get("limit", ["20"]) or ["20"])[0])
            _json_response(self, 200, ok_payload({"items": self.runtime.list_audit_records(limit=limit)}))
            return

        if parsed.path == "/api/v1/audit/policy":
            _json_response(self, 200, ok_payload(self.runtime.get_audit_policy()))
            return

        if parsed.path == "/api/v1/network/policy":
            _json_response(self, 200, ok_payload(self.runtime.get_network_policy()))
            return

        if parsed.path == "/api/v1/runtime/telemetry":
            _json_response(self, 200, ok_payload({"items": self.runtime.list_stream_telemetry()}))
            return

        _json_response(self, 404, error_payload("not_found", "endpoint not found"))

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path != "/api/v1/auth/token":
                required_action = required_post_action(parsed.path)
                if required_action is not None:
                    denied_status, denied_payload = self._authorize(required_action)
                    if denied_status is not None:
                        _json_response(self, denied_status, denied_payload or error_payload("unauthorized", "unauthorized"))
                        return

            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            body = json.loads(raw_body or "{}")

            if parsed.path == "/api/v1/auth/token":
                role = str(body.get("role", "viewer"))
                if not is_supported_role(role):
                    _json_response(self, 400, error_payload("bad_request", f"unsupported role: {role}"))
                    return

                if role == "admin":
                    expected = str(self.bootstrap_token or "").strip()
                    provided = str(self.headers.get("X-Bootstrap-Token", "")).strip()
                    if not expected or provided != expected:
                        _json_response(
                            self,
                            403,
                            error_payload("forbidden", "admin token issuance requires valid bootstrap token"),
                        )
                        return

                res = self.runtime.issue_token(
                    user_id=str(body.get("user_id", "")),
                    role=role,
                    now=_parse_time(body.get("now")),
                )
                _json_response(self, 200, ok_payload(res))
                return

            if parsed.path == "/api/v1/devices/register":
                res = self.runtime.register_device(dict(body))
                _json_response(self, 200, ok_payload(res))
                return

            if parsed.path == "/api/v1/devices/capabilities":
                res = self.runtime.update_device_capabilities(dict(body))
                _json_response(self, 200, ok_payload(res))
                return

            if parsed.path == "/api/v1/algorithms/upsert":
                res = self.runtime.upsert_algorithm(dict(body))
                _json_response(self, 200, ok_payload(res))
                return

            if parsed.path == "/api/v1/base-libraries/upsert":
                res = self.runtime.upsert_base_library(dict(body))
                _json_response(self, 200, ok_payload(res))
                return

            if parsed.path == "/api/v1/base-libraries/mappings/upsert":
                res = self.runtime.upsert_base_library_mapping(dict(body))
                _json_response(self, 200, ok_payload(res))
                return

            if parsed.path == "/api/v1/base-libraries/compatibility/policy":
                res = self.runtime.update_base_library_compatibility_policy(dict(body))
                _json_response(self, 200, ok_payload(res))
                return

            if parsed.path == "/api/v1/offline-executors/upsert":
                res = self.runtime.upsert_offline_executor(dict(body))
                _json_response(self, 200, ok_payload(res))
                return

            if parsed.path == "/api/v1/offline-jobs/create":
                res = self.runtime.create_offline_job(dict(body), now=_parse_time(body.get("now")))
                _json_response(self, 200, ok_payload(res))
                return

            if parsed.path == "/api/v1/offline-jobs/status":
                res = self.runtime.update_offline_job_status(dict(body), now=_parse_time(body.get("now")))
                _json_response(self, 200, ok_payload(res))
                return

            if parsed.path == "/api/v1/runtime/schedule":
                budget = float(body.get("budget", 10.0))
                res = self.runtime.plan_capability_schedule(budget=budget)
                _json_response(self, 200, ok_payload(res))
                return

            if parsed.path == "/api/v1/runtime/telemetry":
                res = self.runtime.update_stream_telemetry(dict(body), now=_parse_time(body.get("now")))
                _json_response(self, 200, ok_payload(res))
                return

            if parsed.path == "/api/v1/network/policy":
                res = self.runtime.update_network_policy(dict(body))
                _json_response(self, 200, ok_payload(res))
                return

            if parsed.path == "/api/v1/audit/policy":
                res = self.runtime.update_audit_policy(dict(body))
                _json_response(self, 200, ok_payload(res))
                return

            if parsed.path.startswith("/api/v1/viewer-sessions/") and parsed.path.endswith("/join"):
                stream_id = parsed.path[len("/api/v1/viewer-sessions/") : -len("/join")]
                res = self.runtime.viewer_join(stream_id=stream_id, now=_parse_time(body.get("now")))
                _json_response(self, 200, ok_payload(res))
                return

            if parsed.path.startswith("/api/v1/viewer-sessions/") and parsed.path.endswith("/leave"):
                stream_id = parsed.path[len("/api/v1/viewer-sessions/") : -len("/leave")]
                res = self.runtime.viewer_leave(stream_id=stream_id, now=_parse_time(body.get("now")))
                _json_response(self, 200, ok_payload(res))
                return

            if parsed.path == "/api/v1/events":
                event_raw = dict(body.get("event", {}))
                res = self.runtime.ingest_event(event_raw, now=_parse_time(body.get("now")))
                status = int(res.get("status", 202))
                if status >= 400:
                    _json_response(
                        self,
                        status,
                        error_payload("event_rejected", str(res.get("reason", "event_rejected")), details=res),
                    )
                else:
                    _json_response(self, status, ok_payload(res))
                return

            if parsed.path == "/api/v1/push/dispatch":
                limit = int(body.get("limit", 20))
                mode = str(body.get("mode", "real"))
                sender = _sender_for_mode(mode)
                res = self.runtime.dispatch_pushes(now=_parse_time(body.get("now")), sender=sender, max_items=limit)
                _json_response(self, 200, ok_payload(res))
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
                _json_response(self, 200, ok_payload(res))
                return

            if parsed.path == "/api/v1/push/worker/stop":
                res = self.runtime.stop_push_worker()
                _json_response(self, 200, ok_payload(res))
                return

            _json_response(self, 404, error_payload("not_found", "endpoint not found"))
        except json.JSONDecodeError:
            _json_response(self, 400, error_payload("invalid_json", "request body must be valid JSON"))
        except ValueError as exc:
            _json_response(self, 400, error_payload("bad_request", str(exc)))
        except Exception:
            _json_response(self, 500, error_payload("internal_error", "unexpected server error"))


def create_server(
    host: str = "127.0.0.1",
    port: int = 18080,
    storage_db_path: str | None = None,
    bootstrap_token: str = "",
) -> ThreadingHTTPServer:
    runtime = P0Runtime(webhook_url="https://example.com/hook", webhook_token="token", storage_db_path=storage_db_path)

    class Handler(_RuntimeHandler):
        pass

    Handler.runtime = runtime
    Handler.bootstrap_token = str(bootstrap_token or "")
    return ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    host = os.getenv("P0_RUNTIME_HOST", "127.0.0.1")
    port = int(os.getenv("P0_RUNTIME_PORT", "18080"))
    db_path = os.getenv("P0_RUNTIME_DB_PATH", "").strip() or None
    bootstrap_token = os.getenv("P0_RUNTIME_BOOTSTRAP_TOKEN", "")
    server = create_server(host=host, port=port, storage_db_path=db_path, bootstrap_token=bootstrap_token)
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
