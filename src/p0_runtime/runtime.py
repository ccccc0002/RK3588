from __future__ import annotations

from datetime import datetime, timezone
import threading
from typing import Callable, Dict, Tuple

from src.p0_core.auth_license import is_action_allowed
from src.p0_core.auth_service import issue_token, verify_token
from src.p0_core.event_center import EventState, initial_event_state, normalize_raw_event, process_event
from src.p0_core.push_gateway import PushState, due_tasks, enqueue_push, initial_push_state, mark_delivery_result
from src.p0_core.viewer_session import SessionSnapshot, new_snapshot, on_tick, on_viewer_join, on_viewer_leave
from src.p0_runtime.ingest_adapters import adapter_for
from src.p0_runtime.push_worker import PushWorker
from src.p0_runtime.storage import RuntimeStorage
from src.p0_runtime.webhook_sender import send_webhook


class P0Runtime:
    def __init__(
        self,
        webhook_url: str,
        webhook_token: str,
        token_secret: str = "rk3588-secret",
        storage_db_path: str | None = None,
    ) -> None:
        self._webhook_url = webhook_url
        self._webhook_token = webhook_token
        self._token_secret = token_secret
        self._storage = RuntimeStorage(storage_db_path) if storage_db_path else None

        self._lock = threading.RLock()
        self._sessions: Dict[str, SessionSnapshot] = {}
        self._event_state: EventState = self._storage.load_event_state() if self._storage else initial_event_state()
        self._push_state: PushState = self._storage.load_push_state() if self._storage else initial_push_state()
        self._devices: Dict[tuple[str, str, str, str], dict] = self._storage.load_devices() if self._storage else {}
        self._push_worker: PushWorker | None = None

        self._metrics = {
            "dispatch_runs": 0,
            "dispatch_processed": 0,
            "dispatch_sent": 0,
            "dispatch_failed": 0,
            "queue_peak": len(self._push_state.tasks),
            "worker_start_count": 0,
            "worker_stop_count": 0,
            "last_dispatch_at": None,
        }

    def close(self) -> None:
        worker = None
        with self._lock:
            if self._push_worker and self._push_worker.is_running:
                worker = self._push_worker
        if worker is not None:
            worker.stop()

        with self._lock:
            self._push_worker = None
            if self._storage is not None:
                self._storage.close()
                self._storage = None

    def _now_or(self, now: datetime | None) -> datetime:
        if now is None:
            return datetime.now(timezone.utc)
        if now.tzinfo is None:
            return now.replace(tzinfo=timezone.utc)
        return now

    def _update_queue_peak_locked(self) -> None:
        queue_now = len(self._push_state.tasks)
        if queue_now > int(self._metrics["queue_peak"]):
            self._metrics["queue_peak"] = queue_now

    def _persist_event_state_locked(self) -> None:
        if self._storage is None:
            return
        self._storage.replace_event_state(self._event_state)

    def _persist_push_state_locked(self) -> None:
        if self._storage is None:
            return
        self._storage.replace_push_state(self._push_state)

    def issue_token(self, user_id: str, role: str, now: datetime | None = None) -> dict:
        at = self._now_or(now)
        token = issue_token(user_id=user_id, role=role, issued_at=at, secret=self._token_secret)
        return {"token": token, "issued_at": at.isoformat()}

    def register_device(self, payload: dict) -> dict:
        required = ("tenant_id", "site_id", "box_id", "device_id", "protocol", "stream_url")
        for field in required:
            if field not in payload:
                raise ValueError(f"missing required field: {field}")

        adapter = adapter_for(str(payload["protocol"]))
        ingest_spec = adapter.build_ingest_spec(payload)

        record = {
            "tenant_id": str(payload["tenant_id"]),
            "site_id": str(payload["site_id"]),
            "box_id": str(payload["box_id"]),
            "device_id": str(payload["device_id"]),
            "protocol": str(payload["protocol"]).lower(),
            "stream_url": str(payload["stream_url"]),
            "enabled": bool(payload.get("enabled", True)),
            "ingest_spec": ingest_spec,
        }
        key = (record["tenant_id"], record["site_id"], record["box_id"], record["device_id"])
        with self._lock:
            self._devices[key] = record
            if self._storage:
                self._storage.upsert_device(record)
        return dict(record)

    def list_devices(self) -> list[dict]:
        with self._lock:
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
        with self._lock:
            snapshot = self._sessions.get(stream_id, new_snapshot(at))
            updated = on_viewer_join(snapshot, at)
            self._sessions[stream_id] = updated
        return {"stream_id": stream_id, "state": updated.state.value, "viewer_count": updated.viewer_count}

    def viewer_leave(self, stream_id: str, now: datetime | None = None) -> dict:
        at = self._now_or(now)
        with self._lock:
            snapshot = self._sessions.get(stream_id, new_snapshot(at))
            updated = on_viewer_leave(snapshot, at)
            self._sessions[stream_id] = updated
        return {"stream_id": stream_id, "state": updated.state.value, "viewer_count": updated.viewer_count}

    def ingest_event(self, raw_event: dict, now: datetime | None = None) -> dict:
        at = self._now_or(now)
        event = normalize_raw_event(raw_event, occurred_at=at)
        with self._lock:
            state, accepted = process_event(self._event_state, event, now=at)
            self._event_state = state
            self._persist_event_state_locked()
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
            self._update_queue_peak_locked()
            self._persist_push_state_locked()

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

        with self._lock:
            ready = list(due_tasks(self._push_state, now=at))

        sent = 0
        failed = 0
        processed = 0
        state_changed = False
        for task in ready:
            if processed >= max_items:
                break
            processed += 1
            ok = bool(sender(task))
            with self._lock:
                self._push_state = mark_delivery_result(self._push_state, task_id=task.task_id, success=ok, now=at)
                self._update_queue_peak_locked()
                state_changed = True
            if ok:
                sent += 1
            else:
                failed += 1

        with self._lock:
            if state_changed:
                self._persist_push_state_locked()
            self._metrics["dispatch_runs"] = int(self._metrics["dispatch_runs"]) + 1
            self._metrics["dispatch_processed"] = int(self._metrics["dispatch_processed"]) + processed
            self._metrics["dispatch_sent"] = int(self._metrics["dispatch_sent"]) + sent
            self._metrics["dispatch_failed"] = int(self._metrics["dispatch_failed"]) + failed
            self._metrics["last_dispatch_at"] = at.isoformat()

        return {"sent": sent, "failed": failed, "processed": processed}

    def start_push_worker(
        self,
        interval_seconds: float = 0.5,
        max_items: int = 20,
        sender: Callable[[object], bool] | None = None,
    ) -> dict:
        with self._lock:
            if self._push_worker and self._push_worker.is_running:
                return {"started": False, "reason": "already_running"}

            def _dispatch_once() -> None:
                self.dispatch_pushes(now=datetime.now(timezone.utc), sender=sender, max_items=max_items)

            worker = PushWorker(dispatch_once=_dispatch_once, interval_seconds=interval_seconds)
            self._push_worker = worker
            self._metrics["worker_start_count"] = int(self._metrics["worker_start_count"]) + 1
            worker.start()
            return {"started": True, "interval_seconds": interval_seconds, "max_items": max_items}

    def stop_push_worker(self) -> dict:
        with self._lock:
            if not self._push_worker or not self._push_worker.is_running:
                return {"stopped": False, "reason": "not_running"}
            worker = self._push_worker

        worker.stop()
        with self._lock:
            self._metrics["worker_stop_count"] = int(self._metrics["worker_stop_count"]) + 1
        return {"stopped": True}

    def push_worker_status(self) -> dict:
        with self._lock:
            running = bool(self._push_worker and self._push_worker.is_running)
            interval = self._push_worker.interval_seconds if self._push_worker else None
        return {"running": running, "interval_seconds": interval}

    def tick(self, now: datetime | None = None) -> None:
        at = self._now_or(now)
        with self._lock:
            for stream_id, snapshot in list(self._sessions.items()):
                self._sessions[stream_id] = on_tick(snapshot, at)

    def get_metrics(self) -> dict:
        storage = self._storage
        with self._lock:
            data = dict(self._metrics)
            data["queue_current"] = len(self._push_state.tasks)
            data["dead_letter_current"] = len(self._push_state.dead_letters)
            data["device_count"] = len(self._devices)
            data["storage_enabled"] = bool(storage is not None)
        if storage is not None:
            data["storage"] = storage.stats()
        else:
            data["storage"] = None
        return data

    def snapshot(self) -> dict:
        with self._lock:
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
