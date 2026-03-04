from __future__ import annotations

from datetime import datetime, timezone
import threading
from typing import Callable, Dict, Tuple

from src.p0_core.ai_scheduler import SchedulePlan, StreamLoad, build_schedule
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
        self._algorithms: Dict[tuple[str, str], dict] = self._storage.load_algorithms() if self._storage else {}
        self._base_libraries: Dict[tuple[str, str], dict] = (
            self._storage.load_base_libraries() if self._storage else {}
        )
        self._base_library_mappings: Dict[tuple[str, str, str, str, str], dict] = (
            self._storage.load_base_library_mappings() if self._storage else {}
        )
        self._offline_jobs: Dict[str, dict] = self._storage.load_offline_jobs() if self._storage else {}
        self._push_worker: PushWorker | None = None
        self._last_capability_schedule: SchedulePlan | None = None
        self._audit_records: list[dict] = self._storage.load_audit_records() if self._storage else []
        self._audit_policy: dict = self._storage.load_audit_policy() if self._storage else {"max_records": 2000}
        max_records = max(1, int(self._audit_policy.get("max_records", 2000)))
        if len(self._audit_records) > max_records:
            self._audit_records = self._audit_records[-max_records:]
        max_audit_id = max((int(item["id"]) for item in self._audit_records), default=0)
        self._audit_next_id: int = max_audit_id + 1
        self._network_policy: dict = (
            self._storage.load_network_policy() if self._storage else {"enforce_allowlist": False, "webhook_allowlist": []}
        )
        self._stream_telemetry: Dict[tuple[str, str, str, str], dict] = {}

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

    def _append_audit_locked(self, action: str, details: dict) -> None:
        record = {
            "id": self._audit_next_id,
            "at": datetime.now(timezone.utc).isoformat(),
            "action": str(action),
            "details": dict(details),
        }
        self._audit_next_id += 1
        self._audit_records.append(record)
        if self._storage is not None:
            self._storage.append_audit_record(record)
        self._apply_audit_retention_locked()

    def _apply_audit_retention_locked(self) -> None:
        max_records = max(1, int(self._audit_policy.get("max_records", 2000)))
        if len(self._audit_records) > max_records:
            self._audit_records = self._audit_records[-max_records:]
        if self._storage is not None:
            self._storage.prune_audit_records(max_records)

    def issue_token(self, user_id: str, role: str, now: datetime | None = None) -> dict:
        at = self._now_or(now)
        token = issue_token(user_id=user_id, role=role, issued_at=at, secret=self._token_secret)
        return {"token": token, "issued_at": at.isoformat()}

    @staticmethod
    def _normalize_capabilities(payload: dict | None) -> dict:
        source = dict(payload or {})
        return {"ocr": bool(source.get("ocr", False)), "face": bool(source.get("face", False))}

    def register_device(self, payload: dict) -> dict:
        required = ("tenant_id", "site_id", "box_id", "device_id", "protocol")
        for field in required:
            if field not in payload:
                raise ValueError(f"missing required field: {field}")

        adapter = adapter_for(str(payload["protocol"]))
        if adapter.requires_stream_url and "stream_url" not in payload:
            raise ValueError("missing required field: stream_url")
        ingest_spec = adapter.build_ingest_spec(payload)

        record = {
            "tenant_id": str(payload["tenant_id"]),
            "site_id": str(payload["site_id"]),
            "box_id": str(payload["box_id"]),
            "device_id": str(payload["device_id"]),
            "protocol": str(payload["protocol"]).lower(),
            "stream_url": str(payload.get("stream_url", "")),
            "enabled": bool(payload.get("enabled", True)),
            "ingest_spec": ingest_spec,
            "capabilities": self._normalize_capabilities(payload.get("capabilities")),
        }
        key = (record["tenant_id"], record["site_id"], record["box_id"], record["device_id"])
        with self._lock:
            self._devices[key] = record
            if self._storage:
                self._storage.upsert_device(record)
            self._append_audit_locked(
                "device.register",
                {
                    "tenant_id": record["tenant_id"],
                    "site_id": record["site_id"],
                    "box_id": record["box_id"],
                    "device_id": record["device_id"],
                    "protocol": record["protocol"],
                },
            )
        return dict(record)

    def update_device_capabilities(self, payload: dict) -> dict:
        required = ("tenant_id", "site_id", "box_id", "device_id", "capabilities")
        for field in required:
            if field not in payload:
                raise ValueError(f"missing required field: {field}")

        key = (
            str(payload["tenant_id"]),
            str(payload["site_id"]),
            str(payload["box_id"]),
            str(payload["device_id"]),
        )
        capabilities = self._normalize_capabilities(dict(payload.get("capabilities", {})))

        with self._lock:
            existing = self._devices.get(key)
            if existing is None:
                raise ValueError("device not found")

            updated = dict(existing)
            updated["capabilities"] = capabilities
            self._devices[key] = updated
            if self._storage:
                self._storage.upsert_device(updated)
            self._append_audit_locked(
                "device.capabilities.update",
                {
                    "tenant_id": key[0],
                    "site_id": key[1],
                    "box_id": key[2],
                    "device_id": key[3],
                    "capabilities": capabilities,
                },
            )

        return dict(updated)

    def list_devices(self) -> list[dict]:
        with self._lock:
            items = [dict(item) for item in self._devices.values()]
        items.sort(key=lambda item: (item["tenant_id"], item["site_id"], item["box_id"], item["device_id"]))
        return items

    @staticmethod
    def _normalize_algorithm_status(value: str) -> str:
        status = str(value).strip().lower()
        if status not in {"draft", "active", "disabled"}:
            raise ValueError(f"unsupported algorithm status: {status}")
        return status

    def upsert_algorithm(self, payload: dict) -> dict:
        required = ("algorithm_id", "version", "status")
        for field in required:
            if field not in payload:
                raise ValueError(f"missing required field: {field}")

        capabilities_raw = payload.get("capabilities", [])
        if not isinstance(capabilities_raw, list):
            raise ValueError("capabilities must be a list")

        record = {
            "algorithm_id": str(payload["algorithm_id"]).strip(),
            "version": str(payload["version"]).strip(),
            "status": self._normalize_algorithm_status(str(payload["status"])),
            "capabilities": [str(item) for item in capabilities_raw],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if not record["algorithm_id"]:
            raise ValueError("algorithm_id must not be empty")
        if not record["version"]:
            raise ValueError("version must not be empty")

        key = (record["algorithm_id"], record["version"])
        with self._lock:
            self._algorithms[key] = record
            if self._storage:
                self._storage.upsert_algorithm(record)
            self._append_audit_locked(
                "algorithm.upsert",
                {
                    "algorithm_id": record["algorithm_id"],
                    "version": record["version"],
                    "status": record["status"],
                },
            )
        return dict(record)

    def list_algorithms(self) -> list[dict]:
        with self._lock:
            items = [dict(item) for item in self._algorithms.values()]
        items.sort(key=lambda item: (item["algorithm_id"], item["version"]))
        return items

    @staticmethod
    def _normalize_base_library_status(value: str) -> str:
        status = str(value).strip().lower()
        if status not in {"draft", "active", "disabled"}:
            raise ValueError(f"unsupported base library status: {status}")
        return status

    def upsert_base_library(self, payload: dict) -> dict:
        required = ("library_id", "version", "capability", "status")
        for field in required:
            if field not in payload:
                raise ValueError(f"missing required field: {field}")

        metadata_raw = payload.get("metadata", {})
        if metadata_raw is None:
            metadata_raw = {}
        if not isinstance(metadata_raw, dict):
            raise ValueError("metadata must be an object")

        record = {
            "library_id": str(payload["library_id"]).strip(),
            "version": str(payload["version"]).strip(),
            "capability": str(payload["capability"]).strip().lower(),
            "status": self._normalize_base_library_status(str(payload["status"])),
            "metadata": dict(metadata_raw),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if not record["library_id"]:
            raise ValueError("library_id must not be empty")
        if not record["version"]:
            raise ValueError("version must not be empty")
        if not record["capability"]:
            raise ValueError("capability must not be empty")

        key = (record["library_id"], record["version"])
        with self._lock:
            self._base_libraries[key] = record
            if self._storage:
                self._storage.upsert_base_library(record)
            self._append_audit_locked(
                "base_library.upsert",
                {
                    "library_id": record["library_id"],
                    "version": record["version"],
                    "capability": record["capability"],
                    "status": record["status"],
                },
            )
        return dict(record)

    def list_base_libraries(self) -> list[dict]:
        with self._lock:
            items = [dict(item) for item in self._base_libraries.values()]
        items.sort(key=lambda item: (item["library_id"], item["version"]))
        return items

    def upsert_base_library_mapping(self, payload: dict) -> dict:
        required = ("tenant_id", "site_id", "box_id", "device_id", "capability", "library_id", "library_version")
        for field in required:
            if field not in payload:
                raise ValueError(f"missing required field: {field}")

        capability = str(payload["capability"]).strip().lower()
        if not capability:
            raise ValueError("capability must not be empty")

        key = (
            str(payload["tenant_id"]),
            str(payload["site_id"]),
            str(payload["box_id"]),
            str(payload["device_id"]),
            capability,
        )
        device_key = key[:4]
        library_key = (str(payload["library_id"]).strip(), str(payload["library_version"]).strip())
        if not library_key[0] or not library_key[1]:
            raise ValueError("library_id and library_version must not be empty")

        with self._lock:
            if device_key not in self._devices:
                raise ValueError("device not found")
            library = self._base_libraries.get(library_key)
            if library is None:
                raise ValueError("base library not found")
            if str(library.get("status", "")).lower() != "active":
                raise ValueError("base library must be active for mapping")

            record = {
                "tenant_id": key[0],
                "site_id": key[1],
                "box_id": key[2],
                "device_id": key[3],
                "capability": key[4],
                "library_id": library_key[0],
                "library_version": library_key[1],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            self._base_library_mappings[key] = record
            if self._storage:
                self._storage.upsert_base_library_mapping(record)
            self._append_audit_locked(
                "base_library.mapping.upsert",
                {
                    "tenant_id": key[0],
                    "site_id": key[1],
                    "box_id": key[2],
                    "device_id": key[3],
                    "capability": key[4],
                    "library_id": library_key[0],
                    "library_version": library_key[1],
                },
            )
            return dict(record)

    def list_base_library_mappings(self) -> list[dict]:
        with self._lock:
            items = [dict(item) for item in self._base_library_mappings.values()]
        items.sort(key=lambda item: (item["tenant_id"], item["site_id"], item["box_id"], item["device_id"], item["capability"]))
        return items

    @staticmethod
    def _normalize_offline_job_status(value: str) -> str:
        status = str(value).strip().lower()
        if status not in {"queued", "running", "succeeded", "failed", "canceled"}:
            raise ValueError(f"unsupported offline job status: {status}")
        return status

    def create_offline_job(self, payload: dict, now: datetime | None = None) -> dict:
        required = ("job_id", "source_scope", "algorithm_id", "algorithm_version")
        for field in required:
            if field not in payload:
                raise ValueError(f"missing required field: {field}")

        job_id = str(payload["job_id"]).strip()
        if not job_id:
            raise ValueError("job_id must not be empty")
        source_scope = payload.get("source_scope")
        if not isinstance(source_scope, dict):
            raise ValueError("source_scope must be an object")

        algorithm_key = (str(payload["algorithm_id"]).strip(), str(payload["algorithm_version"]).strip())
        if not algorithm_key[0] or not algorithm_key[1]:
            raise ValueError("algorithm_id and algorithm_version must not be empty")

        at = self._now_or(now).isoformat()
        with self._lock:
            existing = self._offline_jobs.get(job_id)
            if existing is not None:
                return dict(existing)

            algorithm = self._algorithms.get(algorithm_key)
            if algorithm is None:
                raise ValueError("algorithm not found")
            if str(algorithm.get("status", "")).lower() != "active":
                raise ValueError("algorithm must be active for offline job")

            record = {
                "job_id": job_id,
                "source_scope": dict(source_scope),
                "algorithm_id": algorithm_key[0],
                "algorithm_version": algorithm_key[1],
                "status": "queued",
                "result_ref": str(payload.get("result_ref", "")).strip(),
                "error_reason": "",
                "created_at": at,
                "updated_at": at,
            }
            self._offline_jobs[job_id] = record
            if self._storage:
                self._storage.upsert_offline_job(record)
            self._append_audit_locked(
                "offline.job.create",
                {
                    "job_id": job_id,
                    "algorithm_id": algorithm_key[0],
                    "algorithm_version": algorithm_key[1],
                },
            )
            return dict(record)

    def update_offline_job_status(self, payload: dict, now: datetime | None = None) -> dict:
        required = ("job_id", "status")
        for field in required:
            if field not in payload:
                raise ValueError(f"missing required field: {field}")

        job_id = str(payload["job_id"]).strip()
        target_status = self._normalize_offline_job_status(str(payload["status"]))
        at = self._now_or(now).isoformat()
        transitions = {
            "queued": frozenset({"queued", "running", "failed", "canceled"}),
            "running": frozenset({"running", "succeeded", "failed", "canceled"}),
            "succeeded": frozenset({"succeeded"}),
            "failed": frozenset({"failed"}),
            "canceled": frozenset({"canceled"}),
        }

        with self._lock:
            existing = self._offline_jobs.get(job_id)
            if existing is None:
                raise ValueError("offline job not found")
            current_status = str(existing.get("status", "queued")).lower()
            if target_status not in transitions.get(current_status, frozenset()):
                raise ValueError(f"invalid offline job transition: {current_status}->{target_status}")

            updated = dict(existing)
            updated["status"] = target_status
            updated["updated_at"] = at
            if "result_ref" in payload:
                updated["result_ref"] = str(payload.get("result_ref", "")).strip()
            if "error_reason" in payload:
                updated["error_reason"] = str(payload.get("error_reason", "")).strip()

            self._offline_jobs[job_id] = updated
            if self._storage:
                self._storage.upsert_offline_job(updated)
            self._append_audit_locked(
                "offline.job.status.update",
                {
                    "job_id": job_id,
                    "from_status": current_status,
                    "to_status": target_status,
                },
            )
            return dict(updated)

    def list_offline_jobs(self) -> list[dict]:
        with self._lock:
            items = [dict(item) for item in self._offline_jobs.values()]
        items.sort(key=lambda item: (item.get("updated_at", ""), item.get("job_id", "")), reverse=True)
        return items

    def list_audit_records(self, limit: int = 20) -> list[dict]:
        capped = max(1, min(200, int(limit)))
        with self._lock:
            tail = self._audit_records[-capped:]
            items = [dict(item) for item in reversed(tail)]
        return items

    @staticmethod
    def _normalize_audit_policy(payload: dict) -> dict:
        if "max_records" not in payload:
            raise ValueError("missing required field: max_records")
        max_records = int(payload["max_records"])
        if max_records < 1 or max_records > 50000:
            raise ValueError("max_records must be between 1 and 50000")
        return {"max_records": max_records}

    def get_audit_policy(self) -> dict:
        with self._lock:
            return dict(self._audit_policy)

    def update_audit_policy(self, payload: dict) -> dict:
        normalized = self._normalize_audit_policy(dict(payload))
        with self._lock:
            self._audit_policy = normalized
            if self._storage is not None:
                self._storage.replace_audit_policy(self._audit_policy)
            self._apply_audit_retention_locked()
            self._append_audit_locked("audit.policy.update", {"policy": dict(normalized)})
            return dict(self._audit_policy)

    @staticmethod
    def _normalize_network_policy(payload: dict) -> dict:
        allowlist_raw = payload.get("webhook_allowlist", [])
        if not isinstance(allowlist_raw, list):
            raise ValueError("webhook_allowlist must be a list")

        normalized_allowlist: list[str] = []
        for item in allowlist_raw:
            value = str(item).strip()
            if not value:
                continue
            if not (value.startswith("http://") or value.startswith("https://")):
                raise ValueError(f"invalid webhook url: {value}")
            normalized_allowlist.append(value)

        return {
            "enforce_allowlist": bool(payload.get("enforce_allowlist", False)),
            "webhook_allowlist": normalized_allowlist,
        }

    def get_network_policy(self) -> dict:
        with self._lock:
            return dict(self._network_policy)

    def update_network_policy(self, payload: dict) -> dict:
        normalized = self._normalize_network_policy(dict(payload))
        with self._lock:
            self._network_policy = normalized
            if self._storage is not None:
                self._storage.replace_network_policy(self._network_policy)
            self._append_audit_locked("network.policy.update", {"policy": dict(normalized)})
            return dict(self._network_policy)

    def _is_target_allowed(self, target_url: str) -> bool:
        with self._lock:
            policy = dict(self._network_policy)
        if not bool(policy.get("enforce_allowlist", False)):
            return True
        allowlist = [str(item) for item in policy.get("webhook_allowlist", [])]
        if not allowlist:
            return False
        url = str(target_url)
        return any(url.startswith(prefix) for prefix in allowlist)

    @staticmethod
    def _device_key(payload: dict) -> tuple[str, str, str, str]:
        return (
            str(payload["tenant_id"]),
            str(payload["site_id"]),
            str(payload["box_id"]),
            str(payload["device_id"]),
        )

    def update_stream_telemetry(self, payload: dict, now: datetime | None = None) -> dict:
        required = ("tenant_id", "site_id", "box_id", "device_id", "fps_in")
        for field in required:
            if field not in payload:
                raise ValueError(f"missing required field: {field}")

        key = self._device_key(payload)
        fps_in = float(payload["fps_in"])
        if fps_in <= 0:
            raise ValueError("fps_in must be positive")

        at = self._now_or(now).isoformat()
        record = {
            "tenant_id": key[0],
            "site_id": key[1],
            "box_id": key[2],
            "device_id": key[3],
            "fps_in": fps_in,
            "updated_at": at,
        }
        with self._lock:
            if key not in self._devices:
                raise ValueError("device not found")
            self._stream_telemetry[key] = record
            self._append_audit_locked(
                "runtime.telemetry.update",
                {
                    "tenant_id": key[0],
                    "site_id": key[1],
                    "box_id": key[2],
                    "device_id": key[3],
                    "fps_in": fps_in,
                    "updated_at": at,
                },
            )
        return dict(record)

    def list_stream_telemetry(self) -> list[dict]:
        with self._lock:
            items = [dict(item) for item in self._stream_telemetry.values()]
        items.sort(key=lambda item: (item["tenant_id"], item["site_id"], item["box_id"], item["device_id"]))
        return items

    def plan_capability_schedule(self, budget: float) -> dict:
        capped_budget = max(0.1, float(budget))
        with self._lock:
            devices = [dict(item) for item in self._devices.values() if bool(item.get("enabled", True))]
            previous = self._last_capability_schedule
            telemetry_map = {key: float(item.get("fps_in", 8.0)) for key, item in self._stream_telemetry.items()}

        streams = []
        for item in devices:
            key = (item["tenant_id"], item["site_id"], item["box_id"], item["device_id"])
            fps_in = float(telemetry_map.get(key, 8.0))
            capabilities = self._normalize_capabilities(item.get("capabilities"))
            priority = 3 if capabilities["face"] else (2 if capabilities["ocr"] else 1)
            complexity = 1.0 + (0.6 if capabilities["face"] else 0.0) + (0.4 if capabilities["ocr"] else 0.0)
            streams.append(
                StreamLoad(
                    stream_id=str(item["device_id"]),
                    fps_in=fps_in,
                    complexity=complexity,
                    priority=priority,
                )
            )

        plan = build_schedule(tuple(streams), budget=capped_budget, previous=previous)
        with self._lock:
            self._last_capability_schedule = plan

        return {
            "degraded": bool(plan.degraded),
            "total_cost": float(plan.total_cost),
            "streams": [
                {
                    "device_id": item.stream_id,
                    "sample_fps": float(item.sample_fps),
                    "estimated_cost": float(item.estimated_cost),
                }
                for item in plan.streams
            ],
        }

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
            policy_denied = not self._is_target_allowed(task.target_url)
            ok = False if policy_denied else bool(sender(task))
            with self._lock:
                if policy_denied:
                    self._push_state = mark_delivery_result(
                        self._push_state,
                        task_id=task.task_id,
                        success=False,
                        now=at,
                        force_dead_letter=True,
                        failure_reason="delivery_failed_policy_denied",
                    )
                    self._append_audit_locked(
                        "push.dispatch.policy_denied",
                        {
                            "task_id": task.task_id,
                            "target_url": task.target_url,
                            "reason": "allowlist_denied",
                        },
                    )
                else:
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
            data["algorithm_count"] = len(self._algorithms)
            data["base_library_count"] = len(self._base_libraries)
            data["base_library_mapping_count"] = len(self._base_library_mappings)
            data["offline_job_count"] = len(self._offline_jobs)
            data["telemetry_count"] = len(self._stream_telemetry)
            data["audit_max_records"] = int(self._audit_policy.get("max_records", 2000))
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
                "algorithm_count": len(self._algorithms),
                "base_library_count": len(self._base_libraries),
                "base_library_mapping_count": len(self._base_library_mappings),
                "offline_job_count": len(self._offline_jobs),
                "event_dedupe_size": len(self._event_state.seen_keys),
                "push_queue_size": len(self._push_state.tasks),
                "dead_letter_size": len(self._push_state.dead_letters),
            }
