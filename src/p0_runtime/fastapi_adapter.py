from __future__ import annotations

from datetime import datetime
import importlib.util
from typing import Any

from src.p0_runtime.api_policy import is_supported_role, required_get_action, required_post_action
from src.p0_runtime.runtime import P0Runtime


def is_fastapi_available() -> bool:
    return bool(importlib.util.find_spec("fastapi") and importlib.util.find_spec("pydantic"))


def _ok(data: dict, meta: dict | None = None) -> dict:
    return {"success": True, "data": data, "error": None, "meta": meta or {}}


def _err(code: str, message: str, details: dict | None = None, meta: dict | None = None) -> dict:
    return {
        "success": False,
        "data": None,
        "error": {"code": code, "message": message, "details": details or {}},
        "meta": meta or {},
    }


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _sender_for_mode(mode: str | None):
    normalized = (mode or "real").strip().lower()
    if normalized == "real":
        return None
    if normalized == "always_success":
        return lambda _task: True
    if normalized == "always_fail":
        return lambda _task: False
    return None


def create_fastapi_app(runtime: P0Runtime | None = None, bootstrap_token: str = "") -> Any:
    if not is_fastapi_available():
        raise RuntimeError("fastapi/pydantic not installed")

    from fastapi import Body, FastAPI, Header
    from fastapi.responses import JSONResponse

    app = FastAPI(title="RK3588 P0 FastAPI Adapter", version="0.1.0")
    rt = runtime or P0Runtime(webhook_url="https://example.com/hook", webhook_token="token")
    bootstrap_secret = str(bootstrap_token or "").strip()

    def _authorize_request(authorization: str, required_action: str) -> JSONResponse | None:
        auth_value = str(authorization or "")
        if not auth_value.startswith("Bearer "):
            return JSONResponse(status_code=401, content=_err("unauthorized", "missing bearer token"))
        token = auth_value[len("Bearer ") :].strip()
        if not token:
            return JSONResponse(status_code=401, content=_err("unauthorized", "missing bearer token"))

        ok, context = rt.authorize(token=token, required_action=required_action)
        if ok:
            return None
        if context and context.get("reason") == "forbidden":
            return JSONResponse(
                status_code=403,
                content=_err(
                    "forbidden",
                    "action not allowed for current role",
                    details={"required_action": required_action, "role": context.get("role")},
                ),
            )
        return JSONResponse(status_code=401, content=_err("invalid_token", "token invalid or expired"))

    @app.get("/api/v1/runtime/snapshot")
    def runtime_snapshot(authorization: str = Header(default="", alias="Authorization")):
        denied = _authorize_request(authorization, _required_get_action("/api/v1/runtime/snapshot") or "alert:read")
        if denied is not None:
            return denied
        return _ok(rt.snapshot())

    @app.get("/api/v1/metrics")
    def runtime_metrics(authorization: str = Header(default="", alias="Authorization")):
        denied = _authorize_request(authorization, _required_get_action("/api/v1/metrics") or "alert:read")
        if denied is not None:
            return denied
        return _ok(rt.get_metrics())

    @app.get("/api/v1/devices")
    def list_devices(authorization: str = Header(default="", alias="Authorization")):
        denied = _authorize_request(authorization, _required_get_action("/api/v1/devices") or "device:read")
        if denied is not None:
            return denied
        return _ok({"items": rt.list_devices()})

    @app.get("/api/v1/push/worker/status")
    def push_worker_status(authorization: str = Header(default="", alias="Authorization")):
        denied = _authorize_request(authorization, _required_get_action("/api/v1/push/worker/status") or "device:read")
        if denied is not None:
            return denied
        return _ok(rt.push_worker_status())

    @app.post("/api/v1/auth/token")
    def issue_token_ep(
        payload: dict = Body(default_factory=dict),
        x_bootstrap_token: str = Header(default="", alias="X-Bootstrap-Token"),
    ):
        role = str(payload.get("role", "viewer"))
        if not is_supported_role(role):
            return JSONResponse(status_code=400, content=_err("bad_request", f"unsupported role: {role}"))

        if role == "admin":
            provided = str(x_bootstrap_token or "").strip()
            if not bootstrap_secret or provided != bootstrap_secret:
                return JSONResponse(
                    status_code=403,
                    content=_err("forbidden", "admin token issuance requires valid bootstrap token"),
                )

        user_id = str(payload.get("user_id", ""))
        now = _parse_time(payload.get("now"))
        return _ok(rt.issue_token(user_id=user_id, role=role, now=now))

    @app.post("/api/v1/devices/register")
    def register_device_ep(
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(authorization, _required_post_action("/api/v1/devices/register") or "device:write")
        if denied is not None:
            return denied
        try:
            return _ok(rt.register_device(dict(payload)))
        except ValueError as exc:
            return JSONResponse(status_code=400, content=_err("bad_request", str(exc)))

    @app.post("/api/v1/viewer-sessions/{stream_id}/join")
    def viewer_join_ep(
        stream_id: str,
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(
            authorization,
            _required_post_action(f"/api/v1/viewer-sessions/{stream_id}/join") or "device:read",
        )
        if denied is not None:
            return denied
        return _ok(rt.viewer_join(stream_id=stream_id, now=_parse_time(payload.get("now"))))

    @app.post("/api/v1/viewer-sessions/{stream_id}/leave")
    def viewer_leave_ep(
        stream_id: str,
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(
            authorization,
            _required_post_action(f"/api/v1/viewer-sessions/{stream_id}/leave") or "device:read",
        )
        if denied is not None:
            return denied
        return _ok(rt.viewer_leave(stream_id=stream_id, now=_parse_time(payload.get("now"))))

    @app.post("/api/v1/events")
    def ingest_event_ep(
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(authorization, _required_post_action("/api/v1/events") or "device:write")
        if denied is not None:
            return denied
        try:
            event = dict(payload.get("event", {}))
            result = rt.ingest_event(event, now=_parse_time(payload.get("now")))
            status = int(result.get("status", 202))
            if status >= 400:
                return JSONResponse(
                    status_code=status,
                    content=_err("event_rejected", str(result.get("reason", "event_rejected")), details=result),
                )
            return JSONResponse(status_code=status, content=_ok(result))
        except ValueError as exc:
            return JSONResponse(status_code=400, content=_err("bad_request", str(exc)))

    @app.post("/api/v1/push/dispatch")
    def dispatch_push_ep(
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(authorization, _required_post_action("/api/v1/push/dispatch") or "device:write")
        if denied is not None:
            return denied
        limit = int(payload.get("limit", 20))
        mode = str(payload.get("mode", "real"))
        sender = _sender_for_mode(mode)
        result = rt.dispatch_pushes(now=_parse_time(payload.get("now")), sender=sender, max_items=limit)
        return _ok(result)

    @app.post("/api/v1/push/worker/start")
    def start_push_worker_ep(
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(authorization, _required_post_action("/api/v1/push/worker/start") or "device:write")
        if denied is not None:
            return denied
        interval_ms = int(payload.get("interval_ms", 500))
        limit = int(payload.get("limit", 20))
        mode = str(payload.get("mode", "real"))
        sender = _sender_for_mode(mode)
        result = rt.start_push_worker(
            interval_seconds=max(0.01, interval_ms / 1000.0),
            max_items=limit,
            sender=sender,
        )
        return _ok(result)

    @app.post("/api/v1/push/worker/stop")
    def stop_push_worker_ep(
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(authorization, _required_post_action("/api/v1/push/worker/stop") or "device:write")
        if denied is not None:
            return denied
        _ = payload
        return _ok(rt.stop_push_worker())

    return app
