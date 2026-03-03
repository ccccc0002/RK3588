from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json


@dataclass(frozen=True)
class AlertEvent:
    event_id: str
    tenant_id: str
    site_id: str
    box_id: str
    source_id: str
    event_type: str
    object_id: str
    occurred_at: datetime
    payload: dict
    dedupe_key: str


@dataclass(frozen=True)
class SeenDedupKey:
    dedupe_key: str
    seen_at: datetime


@dataclass(frozen=True)
class EventState:
    seen_keys: tuple[SeenDedupKey, ...]


def initial_event_state() -> EventState:
    return EventState(seen_keys=tuple())


def _build_dedupe_key(raw: dict) -> str:
    return ":".join(
        [
            str(raw["tenant_id"]),
            str(raw["site_id"]),
            str(raw["box_id"]),
            str(raw["source_id"]),
            str(raw["event_type"]),
            str(raw.get("object_id", "-")),
        ]
    )


def normalize_raw_event(raw: dict, occurred_at: datetime) -> AlertEvent:
    required = ("tenant_id", "site_id", "box_id", "source_id", "event_type")
    for field in required:
        if field not in raw:
            raise ValueError(f"missing required field: {field}")

    payload = dict(raw.get("payload", {}))
    dedupe_key = _build_dedupe_key(raw)
    payload_hash = hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    event_id_seed = f"{dedupe_key}:{occurred_at.isoformat()}:{payload_hash}"
    event_id = hashlib.sha1(event_id_seed.encode("utf-8")).hexdigest()[:16]

    return AlertEvent(
        event_id=event_id,
        tenant_id=str(raw["tenant_id"]),
        site_id=str(raw["site_id"]),
        box_id=str(raw["box_id"]),
        source_id=str(raw["source_id"]),
        event_type=str(raw["event_type"]),
        object_id=str(raw.get("object_id", "-")),
        occurred_at=occurred_at,
        payload=payload,
        dedupe_key=dedupe_key,
    )


def process_event(
    state: EventState,
    event: AlertEvent,
    now: datetime,
    window_seconds: int = 60,
) -> tuple[EventState, bool]:
    cutoff = now - timedelta(seconds=window_seconds)
    kept = tuple(entry for entry in state.seen_keys if entry.seen_at >= cutoff)
    duplicate = any(entry.dedupe_key == event.dedupe_key for entry in kept)
    if duplicate:
        return EventState(seen_keys=kept), False

    appended = kept + (SeenDedupKey(dedupe_key=event.dedupe_key, seen_at=now),)
    return EventState(seen_keys=appended), True
