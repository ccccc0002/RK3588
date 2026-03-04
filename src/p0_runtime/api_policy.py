from __future__ import annotations


SUPPORTED_ROLES = frozenset({"admin", "operator", "viewer"})


def is_supported_role(role: str) -> bool:
    return str(role).strip().lower() in SUPPORTED_ROLES


def required_get_action(path: str) -> str | None:
    if path == "/api/v1/runtime/snapshot":
        return "alert:read"
    if path == "/api/v1/metrics":
        return "alert:read"
    if path == "/api/v1/devices":
        return "device:read"
    if path == "/api/v1/push/worker/status":
        return "device:read"
    return None


def required_post_action(path: str) -> str | None:
    if path == "/api/v1/devices/register":
        return "device:write"
    if path == "/api/v1/devices/capabilities":
        return "device:write"
    if path.startswith("/api/v1/viewer-sessions/") and path.endswith("/join"):
        return "device:read"
    if path.startswith("/api/v1/viewer-sessions/") and path.endswith("/leave"):
        return "device:read"
    if path == "/api/v1/events":
        return "device:write"
    if path == "/api/v1/push/dispatch":
        return "device:write"
    if path == "/api/v1/push/worker/start":
        return "device:write"
    if path == "/api/v1/push/worker/stop":
        return "device:write"
    return None
