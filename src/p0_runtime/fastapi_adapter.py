from __future__ import annotations

import importlib.util
from typing import Any

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


def create_fastapi_app(runtime: P0Runtime | None = None) -> Any:
    if not is_fastapi_available():
        raise RuntimeError("fastapi/pydantic not installed")

    from fastapi import Body, FastAPI, HTTPException

    app = FastAPI(title="RK3588 P0 FastAPI Adapter", version="0.1.0")
    rt = runtime or P0Runtime(webhook_url="https://example.com/hook", webhook_token="token")

    @app.get("/api/v1/runtime/snapshot")
    def runtime_snapshot() -> dict:
        return _ok(rt.snapshot())

    @app.get("/api/v1/metrics")
    def runtime_metrics() -> dict:
        return _ok(rt.get_metrics())

    @app.post("/api/v1/auth/token")
    def issue_token_ep(payload: dict = Body(default_factory=dict)) -> dict:
        user_id = str(payload.get("user_id", ""))
        role = str(payload.get("role", "viewer"))
        return _ok(rt.issue_token(user_id=user_id, role=role))

    @app.post("/api/v1/events")
    def ingest_event_ep(payload: dict = Body(default_factory=dict)) -> dict:
        event = dict(payload.get("event", {}))
        result = rt.ingest_event(event)
        if int(result.get("status", 202)) >= 400:
            raise HTTPException(status_code=int(result["status"]), detail=_err("event_rejected", "event rejected", result))
        return _ok(result)

    return app
