from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Dict, Tuple

from src.p0_core.auth_license import is_action_allowed
from src.p0_core.auth_service import issue_token, verify_token
from src.p0_core.event_center import EventState, initial_event_state, normalize_raw_event, process_event
from src.p0_core.push_gateway import PushState, due_tasks, enqueue_push, initial_push_state, mark_delivery_result
from src.p0_core.viewer_session import SessionSnapshot, new_snapshot, on_tick, on_viewer_join, on_viewer_leave
from src.p0_runtime.webhook_sender import send_webhook


class P0Runtime:
    def __init__(self, webhook_url: str, webhook_token: str, token_secret: str = "rk3588-secret") -> None:
        self._webhook_url = webhook_url
        self._webhook_token = webhook_token
        self._token_secret = token_secret

        self._sessions: Dict[str, SessionSnapshot] = {}
        self._event_state: EventState = initial_event_state()
        self._push_state: PushState = initial_push_state()
        self._devices: Dict[tuple[str, str, str, str], dict] = {}

    def _now_or(self, now: datetime | None) -> datetime:
        if now is None:
            return datetime.now(timezone.utc)
        if now.tzinfo is None:
            return now.replace(tzinfo=timezone.utc)
        return now

    def issue_token(self, user_id: str, role: str, now: datetime | None = None) -> dict:
        at = self._now_or(now)
        token = issue_token(user_id=user_id, role=role, issued_at=at, secret=self._token_secret)
        return {"token": token, "issued_at": at.isoformat()}

    def register_device(self, payload: dict) -> dict:
        required = ("tenant_id", "site_id", "box_id", "device_id", "protocol", "stream_url")
        for field in required:
            if field not in payload:
                raise ValueError(f"missing required field: {field}")

        record = {
            "tenant_id": str(payload["tenant_id"]),
            "site_id": str(payload["site_id"]),
            "box_id": str(payload["box_id"]),
            "device_id": str(payload["device_id"]),
            "protocol": str(payload["protocol"]),
            "stream_url": str(payload["stream_url"]),
            "enabled": bool(payload.get("enabled", True)),
        }
        key = (record["tenant_id"], record["site_id"], record["box_id"], record["device_id"])
        self._devices[key] = record
        return dict(record)

    def list_devices(self) -> list[dict]:
        items = [dict(item) for item in self._devices.values()]
        items.sort(key=lambda item: (item["tenant_id"], item["site_id"], item["box_id"], item["device_id"]))
        return items

    def authorize(self, token: str, required_action: str, now: datetime | None = None) -> Tuple[bool, dict | None]:
        at = self._now_or(now)
        ok, payload = verify_token(token=token, at=at, secret=self._token_secret)
        if not ok or payload is None:
            return False, None

        if not is_action_allowed(payload.role, required_action):
            return False, {"user_id": payload.user_id, "role": payload.role, "reason": "forbidden"}

        return True, {"user_id": payload.user_id, "role": payload.role}

    def viewer_join(self, stream_id: str, now: datetime | None = None) -> dict:
        at = self._now_or(now)
        snapshot = self._sessions.get(stream_id, new_snapshot(at))
        updated = on_viewer_join(snapshot, at)
        self._sessions[stream_id] = updated
        return {"stream_id": stream_id, "state": updated.state.value, "viewer_count": updated.viewer_count}

    def viewer_leave(self, stream_id: str, now: datetime | None = None) -> dict:
        at = self._now_or(now)
        snapshot = self._sessions.get(stream_id, new_snapshot(at))
        updated = on_viewer_leave(snapshot, at)
        self._sessions[stream_id] = updated
        return {"stream_id": stream_id, "state": updated.state.value, "viewer_count": updated.viewer_count}

    def ingest_event(self, raw_event: dict, now: datetime | None = None) -> dict:
        at = self._now_or(now)
        event = normalize_raw_event(raw_event, occurred_at=at)
        state, accepted = process_event(self._event_state, event, now=at)
        self._event_state = state
        if not accepted:
            return {"status": 409, "reason": "duplicate_event", "dedupe_key": event.dedupe_key}

        self._push_state = enqueue_push(
            self._push_state,
            idempotency_key=event.event_id,
            target_url=self._webhook_url,
            bearer_token=self._webhook_token,
            payload={
                "event_id": event.event_id,
                "tenant_id": event.tenant_id,
                "site_id": event.site_id,
                "box_id": event.box_id,
                "source_id": event.source_id,
                "event_type": event.event_type,
                "occurred_at": event.occurred_at.isoformat(),
                "payload": event.payload,
            },
            now=at,
        )

        return {"status": 202, "event_id": event.event_id, "dedupe_key": event.dedupe_key}

    def dispatch_pushes(
        self,
        now: datetime | None = None,
        sender: Callable[[object], bool] | None = None,
        max_items: int = 20,
    ) -> dict:
        at = self._now_or(now)
        if sender is None:
            sender = send_webhook

        ready = list(due_tasks(self._push_state, now=at))
        sent = 0
        failed = 0
        processed = 0
        for task in ready:
            if processed >= max_items:
                break
            processed += 1
            ok = bool(sender(task))
            self._push_state = mark_delivery_result(self._push_state, task_id=task.task_id, success=ok, now=at)
            if ok:
                sent += 1
            else:
                failed += 1

        return {"sent": sent, "failed": failed, "processed": processed}

    def tick(self, now: datetime | None = None) -> None:
        at = self._now_or(now)
        for stream_id, snapshot in list(self._sessions.items()):
            self._sessions[stream_id] = on_tick(snapshot, at)

    def snapshot(self) -> dict:
        sessions = {
            stream_id: {
                "state": item.state.value,
                "viewer_count": item.viewer_count,
                "last_transition_at": item.last_transition_at.isoformat(),
            }
            for stream_id, item in self._sessions.items()
        }
        return {
            "sessions": sessions,
            "device_count": len(self._devices),
            "event_dedupe_size": len(self._event_state.seen_keys),
            "push_queue_size": len(self._push_state.tasks),
            "dead_letter_size": len(self._push_state.dead_letters),
        }
