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
    if path == "/api/v1/algorithms":
        return "device:read"
    if path == "/api/v1/base-libraries":
        return "device:read"
    if path == "/api/v1/base-libraries/mappings":
        return "device:read"
    if path == "/api/v1/base-libraries/compatibility/policy":
        return "device:read"
    if path == "/api/v1/offline-executors":
        return "device:read"
    if path == "/api/v1/offline-jobs":
        return "device:read"
    if path == "/api/v1/edge-agents":
        return "device:read"
    if path == "/api/v1/offline-sync/cursors":
        return "device:read"
    if path == "/api/v1/offline-sync/streams":
        return "device:read"
    if path == "/api/v1/gray-rollout/policy":
        return "device:read"
    if path == "/api/v1/push/worker/status":
        return "device:read"
    if path == "/api/v1/audit/recent":
        return "device:write"
    if path == "/api/v1/audit/policy":
        return "device:read"
    if path == "/api/v1/network/policy":
        return "device:read"
    if path == "/api/v1/runtime/telemetry":
        return "device:read"
    return None


def required_post_action(path: str) -> str | None:
    if path == "/api/v1/devices/register":
        return "device:write"
    if path == "/api/v1/devices/capabilities":
        return "device:write"
    if path == "/api/v1/algorithms/upsert":
        return "device:write"
    if path == "/api/v1/base-libraries/upsert":
        return "device:write"
    if path == "/api/v1/base-libraries/mappings/upsert":
        return "device:write"
    if path == "/api/v1/base-libraries/mappings/batch-upsert":
        return "device:write"
    if path == "/api/v1/base-libraries/compatibility/policy":
        return "device:write"
    if path == "/api/v1/offline-executors/upsert":
        return "device:write"
    if path == "/api/v1/offline-executors/heartbeat":
        return "device:write"
    if path == "/api/v1/offline-jobs/create":
        return "device:write"
    if path == "/api/v1/offline-jobs/status":
        return "device:write"
    if path == "/api/v1/offline-jobs/status/batch":
        return "device:write"
    if path == "/api/v1/edge-agents/register":
        return "device:write"
    if path == "/api/v1/edge-agents/heartbeat":
        return "device:write"
    if path == "/api/v1/edge-agents/offline-jobs/lease":
        return "device:write"
    if path == "/api/v1/edge-agents/offline-jobs/lease/start":
        return "device:write"
    if path == "/api/v1/edge-agents/offline-jobs/lease/renew":
        return "device:write"
    if path == "/api/v1/edge-agents/offline-jobs/lease/release":
        return "device:write"
    if path == "/api/v1/edge-agents/offline-jobs/lease/complete":
        return "device:write"
    if path == "/api/v1/offline-sync/cursors/upsert":
        return "device:write"
    if path == "/api/v1/offline-sync/streams/upsert":
        return "device:write"
    if path == "/api/v1/gray-rollout/policy":
        return "device:write"
    if path == "/api/v1/gray-rollout/evaluate":
        return "device:read"
    if path == "/api/v1/gray-rollout/plan":
        return "device:read"
    if path == "/api/v1/runtime/schedule":
        return "device:read"
    if path == "/api/v1/audit/policy":
        return "device:write"
    if path == "/api/v1/runtime/telemetry":
        return "device:write"
    if path == "/api/v1/network/policy":
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
