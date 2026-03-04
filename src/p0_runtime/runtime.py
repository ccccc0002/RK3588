from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import re
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
        self._base_library_compatibility_policy: dict = (
            self._storage.load_base_library_compatibility_policy()
            if self._storage
            else {
                "enforce_capability_match": True,
                "required_status": "active",
                "version_regex_by_capability": {},
                "semver_range_by_capability": {},
            }
        )
        self._base_library_compatibility_policy = self._normalize_base_library_compatibility_policy(
            dict(self._base_library_compatibility_policy)
        )
        self._offline_executors: Dict[str, dict] = self._storage.load_offline_executors() if self._storage else {}
        self._offline_jobs: Dict[str, dict] = self._storage.load_offline_jobs() if self._storage else {}
        self._edge_agents: Dict[str, dict] = self._storage.load_edge_agents() if self._storage else {}
        self._offline_sync_cursors: Dict[tuple[str, str, str], dict] = (
            self._storage.load_offline_sync_cursors() if self._storage else {}
        )
        self._offline_sync_stream_cursors: Dict[tuple[str, str, str, str], dict] = (
            self._storage.load_offline_sync_stream_cursors() if self._storage else {}
        )
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
        self._gray_rollout_policy: dict = (
            self._storage.load_gray_rollout_policy()
            if self._storage
            else {"enabled": False, "default_percent": 0, "overrides": [], "dependencies": [], "dependency_graph": {}}
        )
        self._gray_rollout_policy = self._normalize_gray_rollout_policy(dict(self._gray_rollout_policy))
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

    @staticmethod
    def _parse_semver_tuple(value: str) -> tuple[int, int, int] | None:
        text = str(value).strip()
        match = re.match(r"^(\d+)\.(\d+)\.(\d+)$", text)
        if match is None:
            return None
        return (int(match.group(1)), int(match.group(2)), int(match.group(3)))

    @staticmethod
    def _normalize_base_library_compatibility_policy(payload: dict) -> dict:
        required_status = str(payload.get("required_status", "active")).strip().lower()
        if required_status not in {"draft", "active", "disabled"}:
            raise ValueError(f"unsupported required_status: {required_status}")

        matrix_raw = payload.get("version_regex_by_capability", {})
        if matrix_raw is None:
            matrix_raw = {}
        if not isinstance(matrix_raw, dict):
            raise ValueError("version_regex_by_capability must be an object")

        matrix: dict[str, str] = {}
        for key, value in matrix_raw.items():
            capability = str(key).strip().lower()
            pattern = str(value).strip()
            if not capability or not pattern:
                continue
            try:
                re.compile(pattern)
            except re.error:
                raise ValueError(f"invalid regex for capability {capability}: {pattern}")
            matrix[capability] = pattern

        semver_raw = payload.get("semver_range_by_capability", {})
        if semver_raw is None:
            semver_raw = {}
        if not isinstance(semver_raw, dict):
            raise ValueError("semver_range_by_capability must be an object")

        semver_map: dict[str, dict[str, str]] = {}
        for key, value in semver_raw.items():
            capability = str(key).strip().lower()
            if not capability:
                continue
            if not isinstance(value, dict):
                raise ValueError(f"semver_range_by_capability[{capability}] must be an object")

            min_version = str(value.get("min", "")).strip()
            max_version = str(value.get("max", "")).strip()
            if not min_version and not max_version:
                continue
            if min_version and P0Runtime._parse_semver_tuple(min_version) is None:
                raise ValueError(f"invalid semantic min version for capability {capability}: {min_version}")
            if max_version and P0Runtime._parse_semver_tuple(max_version) is None:
                raise ValueError(f"invalid semantic max version for capability {capability}: {max_version}")
            if min_version and max_version:
                min_tuple = P0Runtime._parse_semver_tuple(min_version)
                max_tuple = P0Runtime._parse_semver_tuple(max_version)
                if min_tuple is not None and max_tuple is not None and min_tuple > max_tuple:
                    raise ValueError(f"semantic range min greater than max for capability {capability}")
            semver_map[capability] = {"min": min_version, "max": max_version}

        return {
            "enforce_capability_match": bool(payload.get("enforce_capability_match", True)),
            "required_status": required_status,
            "version_regex_by_capability": matrix,
            "semver_range_by_capability": semver_map,
        }

    def get_base_library_compatibility_policy(self) -> dict:
        with self._lock:
            return dict(self._base_library_compatibility_policy)

    def update_base_library_compatibility_policy(self, payload: dict) -> dict:
        normalized = self._normalize_base_library_compatibility_policy(dict(payload))
        with self._lock:
            self._base_library_compatibility_policy = normalized
            if self._storage:
                self._storage.replace_base_library_compatibility_policy(normalized)
            self._append_audit_locked("base_library.compatibility_policy.update", {"policy": dict(normalized)})
            return dict(normalized)

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
            policy = dict(self._base_library_compatibility_policy)
            required_status = str(policy.get("required_status", "active")).lower()
            if str(library.get("status", "")).lower() != required_status:
                raise ValueError(f"base library status must be {required_status} for mapping")
            if bool(policy.get("enforce_capability_match", True)):
                library_capability = str(library.get("capability", "")).strip().lower()
                if library_capability != capability:
                    raise ValueError("base library capability mismatch")
            regex_map = dict(policy.get("version_regex_by_capability", {}))
            pattern = str(regex_map.get(capability, "")).strip()
            if pattern and re.match(pattern, library_key[1]) is None:
                raise ValueError("base library version does not satisfy compatibility policy")
            semver_map = dict(policy.get("semver_range_by_capability", {}))
            semver_rule = semver_map.get(capability)
            if isinstance(semver_rule, dict) and semver_rule:
                version_tuple = self._parse_semver_tuple(library_key[1])
                if version_tuple is None:
                    raise ValueError("base library version must be semantic version for compatibility policy")
                min_version = str(semver_rule.get("min", "")).strip()
                max_version = str(semver_rule.get("max", "")).strip()
                if min_version:
                    min_tuple = self._parse_semver_tuple(min_version)
                    if min_tuple is not None and version_tuple < min_tuple:
                        raise ValueError("base library version below semantic compatibility minimum")
                if max_version:
                    max_tuple = self._parse_semver_tuple(max_version)
                    if max_tuple is not None and version_tuple > max_tuple:
                        raise ValueError("base library version above semantic compatibility maximum")

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

    def batch_upsert_base_library_mappings(self, payload: dict) -> list[dict]:
        if "items" not in payload:
            raise ValueError("missing required field: items")
        items_raw = payload.get("items")
        if not isinstance(items_raw, list):
            raise ValueError("items must be a list")

        updated: list[dict] = []
        for item in items_raw:
            if not isinstance(item, dict):
                raise ValueError("each item must be an object")
            updated.append(self.upsert_base_library_mapping(dict(item)))
        return updated

    @staticmethod
    def _normalize_offline_executor_status(value: str) -> str:
        status = str(value).strip().lower()
        if status not in {"active", "drain", "disabled"}:
            raise ValueError(f"unsupported offline executor status: {status}")
        return status

    def _executor_health_state(self, record: dict, now: datetime | None = None) -> str:
        raw = str(record.get("last_heartbeat_at", "")).strip()
        if not raw:
            return "unknown"
        try:
            heartbeat_at = datetime.fromisoformat(raw)
        except ValueError:
            return "unknown"
        if heartbeat_at.tzinfo is None:
            heartbeat_at = heartbeat_at.replace(tzinfo=timezone.utc)
        reference = self._now_or(now)
        age_seconds = (reference - heartbeat_at).total_seconds()
        if age_seconds <= 300:
            return "healthy"
        return "stale"

    def _with_executor_health(self, record: dict, now: datetime | None = None) -> dict:
        enriched = dict(record)
        enriched["last_heartbeat_at"] = str(enriched.get("last_heartbeat_at", "")).strip()
        enriched["health_state"] = self._executor_health_state(enriched, now=now)
        return enriched

    def upsert_offline_executor(self, payload: dict) -> dict:
        required = ("executor_id", "endpoint", "status")
        for field in required:
            if field not in payload:
                raise ValueError(f"missing required field: {field}")

        capabilities_raw = payload.get("capabilities", [])
        if not isinstance(capabilities_raw, list):
            raise ValueError("capabilities must be a list")

        executor_id = str(payload["executor_id"]).strip()
        endpoint = str(payload["endpoint"]).strip()
        status = self._normalize_offline_executor_status(str(payload["status"]))
        if not executor_id:
            raise ValueError("executor_id must not be empty")
        if not (endpoint.startswith("http://") or endpoint.startswith("https://")):
            raise ValueError("endpoint must start with http:// or https://")
        last_heartbeat = str(payload.get("last_heartbeat_at", "")).strip()
        if last_heartbeat:
            try:
                datetime.fromisoformat(last_heartbeat)
            except ValueError:
                raise ValueError("last_heartbeat_at must be ISO datetime")
        at = datetime.now(timezone.utc).isoformat()
        with self._lock:
            existing = dict(self._offline_executors.get(executor_id, {}))
            resolved_heartbeat = last_heartbeat or str(existing.get("last_heartbeat_at", "")).strip()
            record = {
                "executor_id": executor_id,
                "endpoint": endpoint,
                "status": status,
                "capabilities": [str(item).strip().lower() for item in capabilities_raw if str(item).strip()],
                "last_heartbeat_at": resolved_heartbeat,
                "health_state": "",
                "updated_at": at,
            }
            record["health_state"] = self._executor_health_state(record)
            self._offline_executors[record["executor_id"]] = record
            if self._storage:
                self._storage.upsert_offline_executor(record)
            self._append_audit_locked(
                "offline.executor.upsert",
                {
                    "executor_id": record["executor_id"],
                    "status": record["status"],
                    "capabilities": list(record["capabilities"]),
                    "health_state": record["health_state"],
                },
            )
            return dict(record)

    def heartbeat_offline_executor(self, payload: dict, now: datetime | None = None) -> dict:
        if "executor_id" not in payload:
            raise ValueError("missing required field: executor_id")
        executor_id = str(payload["executor_id"]).strip()
        if not executor_id:
            raise ValueError("executor_id must not be empty")
        at = self._now_or(now).isoformat()
        with self._lock:
            existing = self._offline_executors.get(executor_id)
            if existing is None:
                raise ValueError("offline executor not found")
            updated = dict(existing)
            updated["last_heartbeat_at"] = at
            updated["health_state"] = "healthy"
            updated["updated_at"] = at
            self._offline_executors[executor_id] = updated
            if self._storage:
                self._storage.upsert_offline_executor(updated)
            self._append_audit_locked(
                "offline.executor.heartbeat",
                {
                    "executor_id": executor_id,
                    "last_heartbeat_at": at,
                    "health_state": "healthy",
                },
            )
            return dict(updated)

    def list_offline_executors(self, now: datetime | None = None) -> list[dict]:
        with self._lock:
            items = [self._with_executor_health(dict(item), now=now) for item in self._offline_executors.values()]
        items.sort(key=lambda item: item["executor_id"])
        return items

    @staticmethod
    def _normalize_edge_agent_status(value: str) -> str:
        status = str(value).strip().lower()
        if status not in {"active", "drain", "disabled"}:
            raise ValueError(f"unsupported edge agent status: {status}")
        return status

    def _edge_agent_health_state(self, record: dict, now: datetime | None = None) -> str:
        raw = str(record.get("last_heartbeat_at", "")).strip()
        if not raw:
            return "unknown"
        try:
            heartbeat_at = datetime.fromisoformat(raw)
        except ValueError:
            return "unknown"
        if heartbeat_at.tzinfo is None:
            heartbeat_at = heartbeat_at.replace(tzinfo=timezone.utc)
        reference = self._now_or(now)
        age_seconds = (reference - heartbeat_at).total_seconds()
        if age_seconds <= 300:
            return "healthy"
        return "stale"

    def _with_edge_agent_health(self, record: dict, now: datetime | None = None) -> dict:
        enriched = dict(record)
        enriched["last_heartbeat_at"] = str(enriched.get("last_heartbeat_at", "")).strip()
        enriched["health_state"] = self._edge_agent_health_state(enriched, now=now)
        return enriched

    def register_edge_agent(self, payload: dict) -> dict:
        required = ("agent_id", "tenant_id", "site_id", "box_id", "endpoint", "status")
        for field in required:
            if field not in payload:
                raise ValueError(f"missing required field: {field}")

        capabilities_raw = payload.get("capabilities", [])
        if not isinstance(capabilities_raw, list):
            raise ValueError("capabilities must be a list")

        agent_id = str(payload["agent_id"]).strip()
        endpoint = str(payload["endpoint"]).strip()
        if not agent_id:
            raise ValueError("agent_id must not be empty")
        if not (endpoint.startswith("http://") or endpoint.startswith("https://")):
            raise ValueError("endpoint must start with http:// or https://")
        last_heartbeat = str(payload.get("last_heartbeat_at", "")).strip()
        if last_heartbeat:
            try:
                datetime.fromisoformat(last_heartbeat)
            except ValueError:
                raise ValueError("last_heartbeat_at must be ISO datetime")

        at = datetime.now(timezone.utc).isoformat()
        with self._lock:
            existing = dict(self._edge_agents.get(agent_id, {}))
            resolved_heartbeat = last_heartbeat or str(existing.get("last_heartbeat_at", "")).strip()
            record = {
                "agent_id": agent_id,
                "tenant_id": str(payload["tenant_id"]).strip(),
                "site_id": str(payload["site_id"]).strip(),
                "box_id": str(payload["box_id"]).strip(),
                "endpoint": endpoint,
                "status": self._normalize_edge_agent_status(str(payload["status"])),
                "capabilities": [str(item).strip().lower() for item in capabilities_raw if str(item).strip()],
                "last_heartbeat_at": resolved_heartbeat,
                "health_state": "",
                "updated_at": at,
            }
            record["health_state"] = self._edge_agent_health_state(record)
            self._edge_agents[agent_id] = record
            if self._storage:
                self._storage.upsert_edge_agent(record)
            self._append_audit_locked(
                "edge.agent.register",
                {
                    "agent_id": record["agent_id"],
                    "tenant_id": record["tenant_id"],
                    "site_id": record["site_id"],
                    "box_id": record["box_id"],
                    "status": record["status"],
                    "health_state": record["health_state"],
                },
            )
            return dict(record)

    def heartbeat_edge_agent(self, payload: dict, now: datetime | None = None) -> dict:
        if "agent_id" not in payload:
            raise ValueError("missing required field: agent_id")
        agent_id = str(payload["agent_id"]).strip()
        if not agent_id:
            raise ValueError("agent_id must not be empty")
        at = self._now_or(now).isoformat()
        with self._lock:
            existing = self._edge_agents.get(agent_id)
            if existing is None:
                raise ValueError("edge agent not found")
            updated = dict(existing)
            updated["last_heartbeat_at"] = at
            updated["health_state"] = "healthy"
            updated["updated_at"] = at
            self._edge_agents[agent_id] = updated
            if self._storage:
                self._storage.upsert_edge_agent(updated)
            self._append_audit_locked(
                "edge.agent.heartbeat",
                {
                    "agent_id": agent_id,
                    "last_heartbeat_at": at,
                    "health_state": "healthy",
                },
            )
            return dict(updated)

    def list_edge_agents(self, now: datetime | None = None) -> list[dict]:
        with self._lock:
            items = [self._with_edge_agent_health(dict(item), now=now) for item in self._edge_agents.values()]
        items.sort(key=lambda item: item["agent_id"])
        return items

    @staticmethod
    def _parse_iso_datetime(value: str) -> datetime | None:
        raw = str(value).strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    @staticmethod
    def _new_offline_job_lease_token(agent_id: str, job_id: str, lease_at: str) -> str:
        key = f"{agent_id}|{job_id}|{lease_at}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _offline_job_scope_matches_agent(job: dict, agent: dict) -> bool:
        source_scope = job.get("source_scope", {})
        if not isinstance(source_scope, dict):
            return False
        for field in ("tenant_id", "site_id", "box_id"):
            expected = str(source_scope.get(field, "")).strip()
            if not expected:
                continue
            if expected != str(agent.get(field, "")).strip():
                return False
        return True

    def lease_offline_job_to_edge_agent(self, payload: dict, now: datetime | None = None) -> dict:
        if "agent_id" not in payload:
            raise ValueError("missing required field: agent_id")
        agent_id = str(payload.get("agent_id", "")).strip()
        if not agent_id:
            raise ValueError("agent_id must not be empty")

        lease_seconds = int(payload.get("lease_seconds", 60))
        if lease_seconds < 5 or lease_seconds > 3600:
            raise ValueError("lease_seconds must be between 5 and 3600")

        at_dt = self._now_or(now)
        at = at_dt.isoformat()
        lease_expires_at = (at_dt + timedelta(seconds=lease_seconds)).isoformat()

        with self._lock:
            edge_agent = self._edge_agents.get(agent_id)
            if edge_agent is None:
                raise ValueError("edge agent not found")

            resolved_agent = self._with_edge_agent_health(dict(edge_agent), now=at_dt)
            if str(resolved_agent.get("status", "")).lower() != "active":
                raise ValueError("edge agent must be active")
            if str(resolved_agent.get("health_state", "")).lower() == "stale":
                raise ValueError("edge agent is stale")

            jobs = [dict(item) for item in self._offline_jobs.values()]
            jobs.sort(key=lambda item: (str(item.get("created_at", "")), str(item.get("job_id", ""))))

            # Idempotent pull for agent: return currently active lease first.
            for job in jobs:
                if not self._offline_job_scope_matches_agent(job, resolved_agent):
                    continue
                if str(job.get("lease_agent_id", "")).strip() != agent_id:
                    continue
                if str(job.get("status", "")).lower() not in {"queued", "running"}:
                    continue
                expires = self._parse_iso_datetime(str(job.get("lease_expires_at", "")))
                if expires is None or expires <= at_dt:
                    continue
                return {
                    "agent_id": agent_id,
                    "lease_seconds": lease_seconds,
                    "lease_at": at,
                    "leased": True,
                    "job": dict(job),
                }

            for job in jobs:
                if str(job.get("status", "")).lower() != "queued":
                    continue
                if not self._offline_job_scope_matches_agent(job, resolved_agent):
                    continue
                lease_holder = str(job.get("lease_agent_id", "")).strip()
                lease_expires = self._parse_iso_datetime(str(job.get("lease_expires_at", "")))
                if lease_holder and lease_expires is not None and lease_expires > at_dt:
                    continue

                updated = dict(job)
                updated["lease_agent_id"] = agent_id
                updated["lease_token"] = self._new_offline_job_lease_token(agent_id, str(job.get("job_id", "")), at)
                updated["lease_expires_at"] = lease_expires_at
                updated["lease_updated_at"] = at
                updated["updated_at"] = at
                self._offline_jobs[str(updated.get("job_id", ""))] = updated
                if self._storage:
                    self._storage.upsert_offline_job(updated)
                self._append_audit_locked(
                    "offline.job.lease",
                    {
                        "job_id": str(updated.get("job_id", "")),
                        "agent_id": agent_id,
                        "lease_expires_at": lease_expires_at,
                    },
                )
                return {
                    "agent_id": agent_id,
                    "lease_seconds": lease_seconds,
                    "lease_at": at,
                    "leased": True,
                    "job": dict(updated),
                }

            return {
                "agent_id": agent_id,
                "lease_seconds": lease_seconds,
                "lease_at": at,
                "leased": False,
                "job": None,
            }

    def _resolve_active_edge_agent_for_lease_locked(self, agent_id: str, now: datetime) -> dict:
        edge_agent = self._edge_agents.get(agent_id)
        if edge_agent is None:
            raise ValueError("edge agent not found")
        resolved_agent = self._with_edge_agent_health(dict(edge_agent), now=now)
        if str(resolved_agent.get("status", "")).lower() != "active":
            raise ValueError("edge agent must be active")
        if str(resolved_agent.get("health_state", "")).lower() == "stale":
            raise ValueError("edge agent is stale")
        return resolved_agent

    def _get_valid_job_lease_locked(self, agent_id: str, job_id: str, lease_token: str, now: datetime) -> dict:
        existing = self._offline_jobs.get(job_id)
        if existing is None:
            raise ValueError("offline job not found")
        lease_agent_id = str(existing.get("lease_agent_id", "")).strip()
        if lease_agent_id != agent_id:
            raise ValueError("offline job lease holder mismatch")
        token = str(existing.get("lease_token", "")).strip()
        if not token or token != lease_token:
            raise ValueError("offline job lease token mismatch")
        lease_expires = self._parse_iso_datetime(str(existing.get("lease_expires_at", "")))
        if lease_expires is None or lease_expires <= now:
            raise ValueError("offline job lease expired")
        return dict(existing)

    def renew_offline_job_lease(self, payload: dict, now: datetime | None = None) -> dict:
        required = ("agent_id", "job_id", "lease_token")
        for field in required:
            if field not in payload:
                raise ValueError(f"missing required field: {field}")

        agent_id = str(payload.get("agent_id", "")).strip()
        job_id = str(payload.get("job_id", "")).strip()
        lease_token = str(payload.get("lease_token", "")).strip()
        if not agent_id or not job_id or not lease_token:
            raise ValueError("agent_id/job_id/lease_token must not be empty")

        lease_seconds = int(payload.get("lease_seconds", 60))
        if lease_seconds < 5 or lease_seconds > 3600:
            raise ValueError("lease_seconds must be between 5 and 3600")

        at_dt = self._now_or(now)
        at = at_dt.isoformat()
        lease_expires_at = (at_dt + timedelta(seconds=lease_seconds)).isoformat()
        with self._lock:
            _ = self._resolve_active_edge_agent_for_lease_locked(agent_id, at_dt)
            existing = self._get_valid_job_lease_locked(agent_id, job_id, lease_token, at_dt)

            updated = dict(existing)
            updated["lease_expires_at"] = lease_expires_at
            updated["lease_updated_at"] = at
            updated["updated_at"] = at
            self._offline_jobs[job_id] = updated
            if self._storage:
                self._storage.upsert_offline_job(updated)
            self._append_audit_locked(
                "offline.job.lease.renew",
                {
                    "job_id": job_id,
                    "agent_id": agent_id,
                    "lease_expires_at": lease_expires_at,
                },
            )
            return dict(updated)

    def start_offline_job_with_lease(self, payload: dict, now: datetime | None = None) -> dict:
        required = ("agent_id", "job_id", "lease_token")
        for field in required:
            if field not in payload:
                raise ValueError(f"missing required field: {field}")

        agent_id = str(payload.get("agent_id", "")).strip()
        job_id = str(payload.get("job_id", "")).strip()
        lease_token = str(payload.get("lease_token", "")).strip()
        if not agent_id or not job_id or not lease_token:
            raise ValueError("agent_id/job_id/lease_token must not be empty")

        at_dt = self._now_or(now)
        at = at_dt.isoformat()
        with self._lock:
            _ = self._resolve_active_edge_agent_for_lease_locked(agent_id, at_dt)
            existing = self._get_valid_job_lease_locked(agent_id, job_id, lease_token, at_dt)

            current_status = str(existing.get("status", "queued")).lower()
            if current_status not in {"queued", "running"}:
                raise ValueError("offline job status must be queued or running for lease start")

            updated = dict(existing)
            updated["status"] = "running"
            updated["lease_updated_at"] = at
            updated["updated_at"] = at
            self._offline_jobs[job_id] = updated
            if self._storage:
                self._storage.upsert_offline_job(updated)
            self._append_audit_locked(
                "offline.job.lease.start",
                {
                    "job_id": job_id,
                    "agent_id": agent_id,
                    "from_status": current_status,
                    "to_status": "running",
                },
            )
            return dict(updated)

    def complete_offline_job_with_lease(self, payload: dict, now: datetime | None = None) -> dict:
        required = ("agent_id", "job_id", "lease_token", "status")
        for field in required:
            if field not in payload:
                raise ValueError(f"missing required field: {field}")

        agent_id = str(payload.get("agent_id", "")).strip()
        job_id = str(payload.get("job_id", "")).strip()
        lease_token = str(payload.get("lease_token", "")).strip()
        if not agent_id or not job_id or not lease_token:
            raise ValueError("agent_id/job_id/lease_token must not be empty")

        target_status = self._normalize_offline_job_status(str(payload.get("status", "")))
        if target_status not in {"succeeded", "failed", "canceled"}:
            raise ValueError("status must be one of succeeded/failed/canceled")

        at_dt = self._now_or(now)
        with self._lock:
            _ = self._resolve_active_edge_agent_for_lease_locked(agent_id, at_dt)
            existing = self._get_valid_job_lease_locked(agent_id, job_id, lease_token, at_dt)
            current_status = str(existing.get("status", "queued")).lower()
            if current_status not in {"queued", "running"}:
                raise ValueError("offline job status must be queued or running for lease completion")

        status_payload: dict = {"job_id": job_id, "status": target_status}
        if "result_ref" in payload:
            status_payload["result_ref"] = str(payload.get("result_ref", "")).strip()
        if "error_reason" in payload:
            status_payload["error_reason"] = str(payload.get("error_reason", "")).strip()
        updated = self.update_offline_job_status(status_payload, now=at_dt)

        with self._lock:
            self._append_audit_locked(
                "offline.job.lease.complete",
                {
                    "job_id": job_id,
                    "agent_id": agent_id,
                    "to_status": target_status,
                },
            )
        return dict(updated)

    def release_offline_job_lease(self, payload: dict, now: datetime | None = None) -> dict:
        required = ("agent_id", "job_id", "lease_token")
        for field in required:
            if field not in payload:
                raise ValueError(f"missing required field: {field}")

        agent_id = str(payload.get("agent_id", "")).strip()
        job_id = str(payload.get("job_id", "")).strip()
        lease_token = str(payload.get("lease_token", "")).strip()
        if not agent_id or not job_id or not lease_token:
            raise ValueError("agent_id/job_id/lease_token must not be empty")

        at_dt = self._now_or(now)
        at = at_dt.isoformat()
        with self._lock:
            _ = self._resolve_active_edge_agent_for_lease_locked(agent_id, at_dt)
            existing = self._get_valid_job_lease_locked(agent_id, job_id, lease_token, at_dt)

            updated = dict(existing)
            updated["lease_agent_id"] = ""
            updated["lease_token"] = ""
            updated["lease_expires_at"] = ""
            updated["lease_updated_at"] = at
            updated["updated_at"] = at
            self._offline_jobs[job_id] = updated
            if self._storage:
                self._storage.upsert_offline_job(updated)
            self._append_audit_locked(
                "offline.job.lease.release",
                {
                    "job_id": job_id,
                    "agent_id": agent_id,
                },
            )
            return dict(updated)

    def upsert_offline_sync_cursor(self, payload: dict, now: datetime | None = None) -> dict:
        required = ("tenant_id", "site_id", "box_id", "cursor")
        for field in required:
            if field not in payload:
                raise ValueError(f"missing required field: {field}")

        key = (
            str(payload["tenant_id"]).strip(),
            str(payload["site_id"]).strip(),
            str(payload["box_id"]).strip(),
        )
        cursor = str(payload["cursor"]).strip()
        if not all(key) or not cursor:
            raise ValueError("tenant_id/site_id/box_id/cursor must not be empty")

        expected_version_raw = payload.get("expected_version")
        expected_version = None if expected_version_raw is None else int(expected_version_raw)
        at = self._now_or(now).isoformat()
        with self._lock:
            existing = self._offline_sync_cursors.get(key)
            current_version = int(existing["version"]) if existing is not None else 0
            if expected_version is not None and expected_version != current_version:
                raise ValueError("offline sync cursor version conflict")

            record = {
                "tenant_id": key[0],
                "site_id": key[1],
                "box_id": key[2],
                "cursor": cursor,
                "version": current_version + 1,
                "updated_at": at,
            }
            self._offline_sync_cursors[key] = record
            if self._storage:
                self._storage.upsert_offline_sync_cursor(record)
            self._append_audit_locked(
                "offline.sync.cursor.upsert",
                {
                    "tenant_id": key[0],
                    "site_id": key[1],
                    "box_id": key[2],
                    "version": record["version"],
                },
            )
            return dict(record)

    def list_offline_sync_cursors(self) -> list[dict]:
        with self._lock:
            items = [dict(item) for item in self._offline_sync_cursors.values()]
        items.sort(key=lambda item: (item["tenant_id"], item["site_id"], item["box_id"]))
        return items

    def upsert_offline_sync_stream_cursor(self, payload: dict, now: datetime | None = None) -> dict:
        required = ("tenant_id", "site_id", "box_id", "stream_id", "cursor")
        for field in required:
            if field not in payload:
                raise ValueError(f"missing required field: {field}")

        key = (
            str(payload["tenant_id"]).strip(),
            str(payload["site_id"]).strip(),
            str(payload["box_id"]).strip(),
            str(payload["stream_id"]).strip(),
        )
        cursor = str(payload["cursor"]).strip()
        if not all(key) or not cursor:
            raise ValueError("tenant_id/site_id/box_id/stream_id/cursor must not be empty")

        expected_version_raw = payload.get("expected_version")
        expected_version = None if expected_version_raw is None else int(expected_version_raw)
        at = self._now_or(now).isoformat()
        with self._lock:
            existing = self._offline_sync_stream_cursors.get(key)
            current_version = int(existing["version"]) if existing is not None else 0
            if expected_version is not None and expected_version != current_version:
                raise ValueError("offline sync stream cursor version conflict")

            record = {
                "tenant_id": key[0],
                "site_id": key[1],
                "box_id": key[2],
                "stream_id": key[3],
                "cursor": cursor,
                "version": current_version + 1,
                "updated_at": at,
            }
            self._offline_sync_stream_cursors[key] = record
            if self._storage:
                self._storage.upsert_offline_sync_stream_cursor(record)
            self._append_audit_locked(
                "offline.sync.stream.cursor.upsert",
                {
                    "tenant_id": key[0],
                    "site_id": key[1],
                    "box_id": key[2],
                    "stream_id": key[3],
                    "version": record["version"],
                },
            )
            return dict(record)

    def list_offline_sync_stream_cursors(self) -> list[dict]:
        with self._lock:
            items = [dict(item) for item in self._offline_sync_stream_cursors.values()]
        items.sort(key=lambda item: (item["tenant_id"], item["site_id"], item["box_id"], item["stream_id"]))
        return items

    @staticmethod
    def _normalize_offline_job_status(value: str) -> str:
        status = str(value).strip().lower()
        if status not in {"queued", "running", "succeeded", "failed", "canceled"}:
            raise ValueError(f"unsupported offline job status: {status}")
        return status

    def _select_executor_locked(
        self,
        algorithm_capabilities: list[str],
        requested_executor_id: str,
        now: datetime,
    ) -> str:
        if requested_executor_id:
            executor = self._offline_executors.get(requested_executor_id)
            if executor is None:
                raise ValueError("offline executor not found")
            if str(executor.get("status", "")).lower() != "active":
                raise ValueError("offline executor must be active")
            capabilities = set(str(item).strip().lower() for item in executor.get("capabilities", []))
            if capabilities and algorithm_capabilities and capabilities.isdisjoint(set(algorithm_capabilities)):
                raise ValueError("offline executor capability mismatch")
            health_state = self._executor_health_state(dict(executor), now=now)
            if health_state == "stale":
                raise ValueError("offline executor is stale")
            return requested_executor_id

        active = [self._with_executor_health(dict(item), now=now) for item in self._offline_executors.values() if str(item.get("status", "")).lower() == "active"]
        priority = {"healthy": 0, "unknown": 1, "stale": 2}
        active.sort(key=lambda item: (priority.get(str(item.get("health_state", "")), 3), str(item.get("executor_id", ""))))
        for executor in active:
            capabilities = set(str(item).strip().lower() for item in executor.get("capabilities", []))
            if not capabilities or not algorithm_capabilities or not capabilities.isdisjoint(set(algorithm_capabilities)):
                return str(executor.get("executor_id", ""))
        return ""

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

        at_dt = self._now_or(now)
        at = at_dt.isoformat()
        with self._lock:
            existing = self._offline_jobs.get(job_id)
            if existing is not None:
                return dict(existing)

            algorithm = self._algorithms.get(algorithm_key)
            if algorithm is None:
                raise ValueError("algorithm not found")
            if str(algorithm.get("status", "")).lower() != "active":
                raise ValueError("algorithm must be active for offline job")
            algorithm_capabilities = [str(item).strip().lower() for item in algorithm.get("capabilities", []) if str(item).strip()]
            requested_executor_id = str(payload.get("executor_id", "")).strip()
            selected_executor_id = self._select_executor_locked(
                algorithm_capabilities,
                requested_executor_id,
                now=at_dt,
            )

            record = {
                "job_id": job_id,
                "source_scope": dict(source_scope),
                "algorithm_id": algorithm_key[0],
                "algorithm_version": algorithm_key[1],
                "executor_id": selected_executor_id,
                "status": "queued",
                "result_ref": str(payload.get("result_ref", "")).strip(),
                "error_reason": "",
                "lease_agent_id": "",
                "lease_token": "",
                "lease_expires_at": "",
                "lease_updated_at": "",
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
                    "executor_id": selected_executor_id,
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
            if target_status in {"succeeded", "failed", "canceled"}:
                updated["lease_agent_id"] = ""
                updated["lease_token"] = ""
                updated["lease_expires_at"] = ""
                updated["lease_updated_at"] = at

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

    def batch_update_offline_job_status(self, payload: dict, now: datetime | None = None) -> list[dict]:
        if "items" not in payload:
            raise ValueError("missing required field: items")
        items_raw = payload.get("items")
        if not isinstance(items_raw, list):
            raise ValueError("items must be a list")

        updated: list[dict] = []
        for item in items_raw:
            if not isinstance(item, dict):
                raise ValueError("each item must be an object")
            updated.append(self.update_offline_job_status(dict(item), now=now))
        return updated

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

    @staticmethod
    def _validate_dependency_graph_acyclic(graph: dict[str, list[str]]) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visited:
                return
            if node in visiting:
                raise ValueError("dependency_graph must be acyclic")
            visiting.add(node)
            for dep in graph.get(node, []):
                visit(dep)
            visiting.remove(node)
            visited.add(node)

        for node in graph.keys():
            visit(str(node))

    @staticmethod
    def _normalize_gray_rollout_policy(payload: dict) -> dict:
        default_percent = int(payload.get("default_percent", 0))
        if default_percent < 0 or default_percent > 100:
            raise ValueError("default_percent must be between 0 and 100")

        dependencies_raw = payload.get("dependencies", [])
        if not isinstance(dependencies_raw, list):
            raise ValueError("dependencies must be a list")
        normalized_dependencies = sorted(
            {
                str(item).strip()
                for item in dependencies_raw
                if str(item).strip()
            }
        )

        dependency_graph_raw = payload.get("dependency_graph", {})
        if dependency_graph_raw is None:
            dependency_graph_raw = {}
        if not isinstance(dependency_graph_raw, dict):
            raise ValueError("dependency_graph must be an object")
        normalized_dependency_graph: dict[str, list[str]] = {}
        for key, value in dependency_graph_raw.items():
            node = str(key).strip()
            if not node:
                raise ValueError("dependency_graph keys must not be empty")
            if not isinstance(value, list):
                raise ValueError("dependency_graph values must be a list")
            normalized_dependency_graph[node] = sorted(
                {
                    str(item).strip()
                    for item in value
                    if str(item).strip()
                }
            )
        P0Runtime._validate_dependency_graph_acyclic(normalized_dependency_graph)

        overrides_raw = payload.get("overrides", [])
        if not isinstance(overrides_raw, list):
            raise ValueError("overrides must be a list")

        normalized_overrides: list[dict] = []
        for item in overrides_raw:
            if not isinstance(item, dict):
                raise ValueError("each override must be an object")
            tenant_id = str(item.get("tenant_id", "")).strip()
            site_id = str(item.get("site_id", "")).strip()
            box_id = str(item.get("box_id", "")).strip()
            if not tenant_id or not site_id or not box_id:
                raise ValueError("override tenant_id/site_id/box_id must not be empty")
            percent = int(item.get("percent", 0))
            if percent < 0 or percent > 100:
                raise ValueError("override percent must be between 0 and 100")
            normalized_overrides.append(
                {
                    "tenant_id": tenant_id,
                    "site_id": site_id,
                    "box_id": box_id,
                    "percent": percent,
                }
            )

        normalized_overrides.sort(key=lambda item: (item["tenant_id"], item["site_id"], item["box_id"]))
        return {
            "enabled": bool(payload.get("enabled", False)),
            "default_percent": default_percent,
            "dependencies": normalized_dependencies,
            "dependency_graph": normalized_dependency_graph,
            "overrides": normalized_overrides,
        }

    @staticmethod
    def _copy_gray_rollout_policy(policy: dict) -> dict:
        cloned = dict(policy)
        cloned["overrides"] = [dict(item) for item in cloned.get("overrides", [])]
        cloned["dependencies"] = [str(item) for item in cloned.get("dependencies", [])]
        cloned["dependency_graph"] = {
            str(node): [str(dep) for dep in deps]
            for node, deps in dict(cloned.get("dependency_graph", {})).items()
        }
        return cloned

    def get_gray_rollout_policy(self) -> dict:
        with self._lock:
            policy = self._copy_gray_rollout_policy(self._gray_rollout_policy)
        return policy

    def update_gray_rollout_policy(self, payload: dict) -> dict:
        normalized = self._normalize_gray_rollout_policy(dict(payload))
        with self._lock:
            self._gray_rollout_policy = normalized
            if self._storage is not None:
                self._storage.replace_gray_rollout_policy(self._gray_rollout_policy)
            self._append_audit_locked("gray.rollout.policy.update", {"policy": dict(normalized)})
            policy = self._copy_gray_rollout_policy(self._gray_rollout_policy)
        return policy

    @staticmethod
    def _scope_rollout_percent(policy: dict, tenant_id: str, site_id: str, box_id: str) -> int:
        for item in policy.get("overrides", []):
            if (
                str(item.get("tenant_id", "")) == tenant_id
                and str(item.get("site_id", "")) == site_id
                and str(item.get("box_id", "")) == box_id
            ):
                return int(item.get("percent", 0))
        return int(policy.get("default_percent", 0))

    @staticmethod
    def _collect_gray_dependency_closure(dependencies: list[str], dependency_graph: dict[str, list[str]]) -> set[str]:
        closure: set[str] = set()

        def visit(node: str) -> None:
            if node in closure:
                return
            closure.add(node)
            for child in dependency_graph.get(node, []):
                visit(str(child))

        for item in dependencies:
            visit(str(item))
        return closure

    @staticmethod
    def _topo_order_gray_dependencies(dependencies: list[str], dependency_graph: dict[str, list[str]]) -> list[str]:
        closure = P0Runtime._collect_gray_dependency_closure(dependencies, dependency_graph)
        if not closure:
            return []

        in_degree: dict[str, int] = {node: 0 for node in closure}
        dependents: dict[str, set[str]] = {node: set() for node in closure}
        for node in closure:
            prerequisites = [str(dep) for dep in dependency_graph.get(node, []) if str(dep) in closure]
            in_degree[node] = len(prerequisites)
            for prerequisite in prerequisites:
                dependents[prerequisite].add(node)

        ready = sorted([node for node, degree in in_degree.items() if degree == 0])
        order: list[str] = []
        while ready:
            node = ready.pop(0)
            order.append(node)
            for dependent in sorted(dependents.get(node, set())):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    ready.append(dependent)
            ready.sort()

        if len(order) != len(closure):
            raise ValueError("dependency_graph must be acyclic")
        return order

    @staticmethod
    def _resolve_gray_dependency_plan(
        dependencies: list[str],
        dependency_graph: dict[str, list[str]],
        dependency_status_raw: dict,
    ) -> dict:
        execution_order = P0Runtime._topo_order_gray_dependencies(dependencies, dependency_graph)
        closure = set(execution_order)
        blocked_set: set[str] = set()
        missing_set: set[str] = set()
        nodes: list[dict] = []
        for dependency in execution_order:
            prerequisites = [
                str(item)
                for item in dependency_graph.get(dependency, [])
                if str(item) in closure
            ]
            blocked_by = []
            if dependency not in dependency_status_raw:
                missing_set.add(dependency)
            if not bool(dependency_status_raw.get(dependency, False)):
                blocked_by.append(dependency)
            for prerequisite in prerequisites:
                if prerequisite not in dependency_status_raw:
                    missing_set.add(prerequisite)
                if not bool(dependency_status_raw.get(prerequisite, False)):
                    blocked_by.append(prerequisite)
            blocked_list = sorted(set(blocked_by))
            for item in blocked_list:
                blocked_set.add(item)
            nodes.append(
                {
                    "dependency": dependency,
                    "prerequisites": prerequisites,
                    "ready": len(blocked_list) == 0,
                    "blocked_by": blocked_list,
                }
            )
        return {
            "execution_order": execution_order,
            "nodes": nodes,
            "blocked_by": sorted(blocked_set),
            "missing_status": sorted(missing_set),
        }

    def plan_gray_rollout_dependencies(self, payload: dict) -> dict:
        required = ("tenant_id", "site_id", "box_id")
        for field in required:
            if field not in payload:
                raise ValueError(f"missing required field: {field}")
        tenant_id = str(payload["tenant_id"]).strip()
        site_id = str(payload["site_id"]).strip()
        box_id = str(payload["box_id"]).strip()
        if not tenant_id or not site_id or not box_id:
            raise ValueError("tenant_id/site_id/box_id must not be empty")

        seed = str(payload.get("seed", f"{tenant_id}/{site_id}/{box_id}")).strip()
        if not seed:
            raise ValueError("seed must not be empty")

        with self._lock:
            policy = self._copy_gray_rollout_policy(self._gray_rollout_policy)

        percent = self._scope_rollout_percent(policy, tenant_id, site_id, box_id)
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        bucket = (int(digest[:8], 16) % 100) + 1
        dependency_status_raw = payload.get("dependency_status", {})
        if dependency_status_raw is None:
            dependency_status_raw = {}
        if not isinstance(dependency_status_raw, dict):
            raise ValueError("dependency_status must be an object")

        dependencies = [str(item) for item in policy.get("dependencies", [])]
        dependency_graph = {
            str(node): [str(dep) for dep in deps]
            for node, deps in dict(policy.get("dependency_graph", {})).items()
        }
        dependency_plan = self._resolve_gray_dependency_plan(
            dependencies=dependencies,
            dependency_graph=dependency_graph,
            dependency_status_raw=dependency_status_raw,
        )
        blocked_by = [str(item) for item in dependency_plan["blocked_by"]]
        enabled = bool(policy.get("enabled", False)) and bucket <= percent and not blocked_by
        return {
            "tenant_id": tenant_id,
            "site_id": site_id,
            "box_id": box_id,
            "seed": seed,
            "percent": percent,
            "bucket": bucket,
            "dependencies": dependencies,
            "execution_order": [str(item) for item in dependency_plan["execution_order"]],
            "nodes": [dict(item) for item in dependency_plan["nodes"]],
            "blocked_by": blocked_by,
            "missing_status": [str(item) for item in dependency_plan["missing_status"]],
            "enabled": enabled,
        }

    def batch_plan_gray_rollout_dependencies(self, payload: dict) -> list[dict]:
        report = self.batch_plan_gray_rollout_dependencies_report(payload)
        errors = [dict(item) for item in report.get("errors", [])]
        if errors:
            first = errors[0]
            idx = int(first.get("index", 0))
            msg = str(first.get("error", "batch item invalid"))
            raise ValueError(f"items[{idx}]: {msg}")
        return [dict(item) for item in report.get("items", [])]

    def batch_plan_gray_rollout_dependencies_report(self, payload: dict) -> dict:
        items_raw = payload.get("items", [])
        if not isinstance(items_raw, list):
            raise ValueError("items must be a list")
        continue_on_error = bool(payload.get("continue_on_error", False))

        results: list[dict] = []
        errors: list[dict] = []
        for idx, item in enumerate(items_raw):
            if not isinstance(item, dict):
                message = "must be an object"
                if continue_on_error:
                    errors.append({"index": idx, "error": message})
                    continue
                raise ValueError(f"items[{idx}] {message}")
            try:
                planned = self.plan_gray_rollout_dependencies(dict(item))
            except ValueError as exc:
                if continue_on_error:
                    errors.append({"index": idx, "error": str(exc)})
                    continue
                raise ValueError(f"items[{idx}]: {exc}") from exc
            results.append(planned)
        return {
            "items": [dict(item) for item in results],
            "errors": [dict(item) for item in errors],
            "continue_on_error": continue_on_error,
            "total": len(items_raw),
            "success_count": len(results),
            "error_count": len(errors),
        }

    def evaluate_gray_rollout(self, payload: dict) -> dict:
        planned = self.plan_gray_rollout_dependencies(payload)
        return {
            "tenant_id": str(planned["tenant_id"]),
            "site_id": str(planned["site_id"]),
            "box_id": str(planned["box_id"]),
            "seed": str(planned["seed"]),
            "percent": int(planned["percent"]),
            "bucket": int(planned["bucket"]),
            "blocked_by": [str(item) for item in planned["blocked_by"]],
            "enabled": bool(planned["enabled"]),
        }

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
            data["offline_executor_count"] = len(self._offline_executors)
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
                "offline_executor_count": len(self._offline_executors),
                "offline_job_count": len(self._offline_jobs),
                "event_dedupe_size": len(self._event_state.seen_keys),
                "push_queue_size": len(self._push_state.tasks),
                "dead_letter_size": len(self._push_state.dead_letters),
            }
