from __future__ import annotations

import importlib.util
from typing import Any, Optional

from src.p0_runtime.runtime import P0Runtime


def is_fastapi_available() -> bool:
    return bool(importlib.util.find_spec("fastapi") and importlib.util.find_spec("pydantic"))


def create_fastapi_app(runtime: P0Runtime | None = None) -> Any:
    if not is_fastapi_available():
        raise RuntimeError("fastapi/pydantic not installed")

    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel

    app = FastAPI(title="RK3588 P0 FastAPI Adapter", version="0.1.0")
    rt = runtime or P0Runtime(webhook_url="https://example.com/hook", webhook_token="token")

    class TokenReq(BaseModel):
        user_id: str
        role: str = "viewer"
        now: Optional[str] = None

    class EventReq(BaseModel):
        now: Optional[str] = None
        event: dict

    @app.get("/api/v1/runtime/snapshot")
    def runtime_snapshot() -> dict:
        return rt.snapshot()

    @app.get("/api/v1/metrics")
    def runtime_metrics() -> dict:
        return rt.get_metrics()

    @app.post("/api/v1/auth/token")
    def issue_token_ep(req: TokenReq) -> dict:
        return rt.issue_token(user_id=req.user_id, role=req.role)

    @app.post("/api/v1/events")
    def ingest_event_ep(req: EventReq) -> dict:
        result = rt.ingest_event(req.event)
        if int(result.get("status", 202)) >= 400:
            raise HTTPException(status_code=int(result["status"]), detail=result)
        return result

    return app
