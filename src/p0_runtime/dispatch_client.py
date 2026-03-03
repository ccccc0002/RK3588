from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any
from urllib.request import Request, urlopen


def _unwrap_response(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return payload

    if "success" not in payload:
        return payload

    if bool(payload.get("success")):
        data = payload.get("data", {})
        return data if isinstance(data, dict) else {"value": data}

    err = payload.get("error", {}) if isinstance(payload.get("error"), dict) else {}
    code = str(err.get("code", "unknown_error"))
    message = str(err.get("message", "request failed"))
    raise RuntimeError(f"{code}: {message}")


def _post_json(url: str, payload: dict, timeout_seconds: float = 3.0) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = Request(
        url=url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req, timeout=timeout_seconds) as resp:
        raw = json.loads(resp.read().decode("utf-8"))
        return _unwrap_response(raw)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def dispatch_once(base_url: str, limit: int = 20, mode: str = "real", timeout_seconds: float = 3.0) -> dict:
    url = base_url.rstrip("/") + "/api/v1/push/dispatch"
    payload = {
        "now": _now_iso(),
        "limit": int(limit),
        "mode": str(mode),
    }
    return _post_json(url, payload, timeout_seconds=timeout_seconds)


def start_worker(
    base_url: str,
    interval_ms: int = 500,
    limit: int = 20,
    mode: str = "real",
    timeout_seconds: float = 3.0,
) -> dict:
    url = base_url.rstrip("/") + "/api/v1/push/worker/start"
    payload = {
        "interval_ms": int(interval_ms),
        "limit": int(limit),
        "mode": str(mode),
    }
    return _post_json(url, payload, timeout_seconds=timeout_seconds)


def stop_worker(base_url: str, timeout_seconds: float = 3.0) -> dict:
    url = base_url.rstrip("/") + "/api/v1/push/worker/stop"
    return _post_json(url, {}, timeout_seconds=timeout_seconds)


def get_json(url: str, timeout_seconds: float = 3.0) -> dict:
    req = Request(url=url, method="GET")
    with urlopen(req, timeout=timeout_seconds) as resp:
        raw = json.loads(resp.read().decode("utf-8"))
        return _unwrap_response(raw)


def get_metrics(base_url: str, timeout_seconds: float = 3.0) -> dict:
    return get_json(base_url.rstrip("/") + "/api/v1/metrics", timeout_seconds=timeout_seconds)


def get_worker_status(base_url: str, timeout_seconds: float = 3.0) -> dict:
    return get_json(base_url.rstrip("/") + "/api/v1/push/worker/status", timeout_seconds=timeout_seconds)
