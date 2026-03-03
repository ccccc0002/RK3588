from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class LicenseSnapshot:
    license_id: str
    ipc_limit: int
    enabled_devices: int
    expires_at: datetime


ROLE_ACTIONS = {
    "admin": {"license:update", "device:write", "device:read", "alert:read"},
    "operator": {"device:write", "device:read", "alert:read"},
    "viewer": {"device:read", "alert:read"},
}


def can_enable_device(snapshot: LicenseSnapshot, at: datetime) -> tuple[bool, str | None]:
    if at >= snapshot.expires_at:
        return False, "license_expired"

    if snapshot.enabled_devices >= snapshot.ipc_limit:
        return False, "ipc_limit_reached"

    return True, None


def is_action_allowed(role: str, action: str) -> bool:
    return action in ROLE_ACTIONS.get(role, set())
