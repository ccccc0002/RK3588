from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Dict
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


def _post_json(url: str, payload: dict, timeout_seconds: float = 3.0, auth_token: str = "") -> dict:
    body = json.dumps(payload).encode("utf-8")
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    req = Request(
        url=url,
        data=body,
        method="POST",
        headers=headers,
    )
    with urlopen(req, timeout=timeout_seconds) as resp:
        raw = json.loads(resp.read().decode("utf-8"))
        return _unwrap_response(raw)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def dispatch_once(
    base_url: str,
    limit: int = 20,
    mode: str = "real",
    timeout_seconds: float = 3.0,
    auth_token: str = "",
) -> dict:
    url = base_url.rstrip("/") + "/api/v1/push/dispatch"
    payload = {
        "now": _now_iso(),
        "limit": int(limit),
        "mode": str(mode),
    }
    return _post_json(url, payload, timeout_seconds=timeout_seconds, auth_token=auth_token)


def start_worker(
    base_url: str,
    interval_ms: int = 500,
    limit: int = 20,
    mode: str = "real",
    timeout_seconds: float = 3.0,
    auth_token: str = "",
) -> dict:
    url = base_url.rstrip("/") + "/api/v1/push/worker/start"
    payload = {
        "interval_ms": int(interval_ms),
        "limit": int(limit),
        "mode": str(mode),
    }
    return _post_json(url, payload, timeout_seconds=timeout_seconds, auth_token=auth_token)


def stop_worker(base_url: str, timeout_seconds: float = 3.0, auth_token: str = "") -> dict:
    url = base_url.rstrip("/") + "/api/v1/push/worker/stop"
    return _post_json(url, {}, timeout_seconds=timeout_seconds, auth_token=auth_token)


def get_json(url: str, timeout_seconds: float = 3.0, auth_token: str = "") -> dict:
    headers: Dict[str, str] = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    req = Request(url=url, method="GET", headers=headers)
    with urlopen(req, timeout=timeout_seconds) as resp:
        raw = json.loads(resp.read().decode("utf-8"))
        return _unwrap_response(raw)


def get_metrics(base_url: str, timeout_seconds: float = 3.0, auth_token: str = "") -> dict:
    return get_json(base_url.rstrip("/") + "/api/v1/metrics", timeout_seconds=timeout_seconds, auth_token=auth_token)


def get_worker_status(base_url: str, timeout_seconds: float = 3.0, auth_token: str = "") -> dict:
    return get_json(base_url.rstrip("/") + "/api/v1/push/worker/status", timeout_seconds=timeout_seconds, auth_token=auth_token)


def issue_token(
    base_url: str,
    user_id: str = "worker",
    role: str = "operator",
    timeout_seconds: float = 3.0,
) -> str:
    url = base_url.rstrip("/") + "/api/v1/auth/token"
    res = _post_json(url, {"user_id": user_id, "role": role, "now": _now_iso()}, timeout_seconds=timeout_seconds)
    token = str(res.get("token", ""))
    if not token:
        raise RuntimeError("failed to issue runtime token")
    return token
