from __future__ import annotations


_REQUIRED_FIELDS = (
    "tenant_id",
    "site_id",
    "box_id",
    "device_id",
    "sip_server",
    "sip_port",
    "channel_id",
    "transport",
)
_SUPPORTED_TRANSPORT = frozenset({"udp", "tcp"})


def _as_non_empty_text(payload: dict, field: str) -> str:
    value = str(payload.get(field, "")).strip()
    if not value:
        raise ValueError(f"missing required field: {field}")
    return value


def _as_port(payload: dict, field: str) -> int:
    if field not in payload:
        raise ValueError(f"missing required field: {field}")
    value = int(payload.get(field))
    if value < 1 or value > 65535:
        raise ValueError(f"{field} out of range: {value}")
    return value


def normalize_gb28181_source(payload: dict) -> dict:
    for field in _REQUIRED_FIELDS:
        if field not in payload:
            raise ValueError(f"missing required field: {field}")

    tenant_id = _as_non_empty_text(payload, "tenant_id")
    site_id = _as_non_empty_text(payload, "site_id")
    box_id = _as_non_empty_text(payload, "box_id")
    device_id = _as_non_empty_text(payload, "device_id")
    sip_server = _as_non_empty_text(payload, "sip_server")
    sip_port = _as_port(payload, "sip_port")
    channel_id = _as_non_empty_text(payload, "channel_id")

    transport = _as_non_empty_text(payload, "transport").lower()
    if transport not in _SUPPORTED_TRANSPORT:
        raise ValueError(f"unsupported transport: {transport}")

    expires_seconds = int(payload.get("expires_seconds", 3600))
    if expires_seconds < 60 or expires_seconds > 86400:
        raise ValueError(f"expires_seconds out of range: {expires_seconds}")

    ingest_spec = {
        "sip_server": sip_server,
        "sip_port": sip_port,
        "channel_id": channel_id,
        "transport": transport,
        "expires_seconds": expires_seconds,
    }

    return {
        "tenant_id": tenant_id,
        "site_id": site_id,
        "box_id": box_id,
        "device_id": device_id,
        "protocol": "gb28181",
        "transport": transport,
        "enabled": bool(payload.get("enabled", True)),
        "ingest_spec": ingest_spec,
    }
