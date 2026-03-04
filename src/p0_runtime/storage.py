from __future__ import annotations

from datetime import datetime
import json
import os
import sqlite3
import threading
from typing import Dict, Tuple

from src.p0_core.event_center import EventState, SeenDedupKey
from src.p0_core.push_gateway import PushState, PushTask


class RuntimeStorage:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = threading.RLock()
        self._closed = False
        self._ensure_parent_dir(db_path)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _ensure_parent_dir(self, db_path: str) -> None:
        if db_path == ":memory:":
            return
        parent = os.path.dirname(os.path.abspath(db_path))
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)

    def _init_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS devices (
                  tenant_id TEXT NOT NULL,
                  site_id TEXT NOT NULL,
                  box_id TEXT NOT NULL,
                  device_id TEXT NOT NULL,
                  record_json TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  PRIMARY KEY (tenant_id, site_id, box_id, device_id)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS algorithms (
                  algorithm_id TEXT NOT NULL,
                  version TEXT NOT NULL,
                  record_json TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  PRIMARY KEY (algorithm_id, version)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS base_libraries (
                  library_id TEXT NOT NULL,
                  version TEXT NOT NULL,
                  record_json TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  PRIMARY KEY (library_id, version)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS base_library_mappings (
                  tenant_id TEXT NOT NULL,
                  site_id TEXT NOT NULL,
                  box_id TEXT NOT NULL,
                  device_id TEXT NOT NULL,
                  capability TEXT NOT NULL,
                  record_json TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  PRIMARY KEY (tenant_id, site_id, box_id, device_id, capability)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS base_library_compatibility_policy (
                  singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                  policy_json TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS offline_executors (
                  executor_id TEXT PRIMARY KEY,
                  record_json TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS offline_jobs (
                  job_id TEXT PRIMARY KEY,
                  record_json TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS edge_agents (
                  agent_id TEXT PRIMARY KEY,
                  record_json TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS offline_sync_cursors (
                  tenant_id TEXT NOT NULL,
                  site_id TEXT NOT NULL,
                  box_id TEXT NOT NULL,
                  record_json TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  PRIMARY KEY (tenant_id, site_id, box_id)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS offline_sync_stream_cursors (
                  tenant_id TEXT NOT NULL,
                  site_id TEXT NOT NULL,
                  box_id TEXT NOT NULL,
                  stream_id TEXT NOT NULL,
                  record_json TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  PRIMARY KEY (tenant_id, site_id, box_id, stream_id)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS push_queue (
                  sequence_no INTEGER NOT NULL,
                  task_id TEXT PRIMARY KEY,
                  idempotency_key TEXT NOT NULL,
                  target_url TEXT NOT NULL,
                  bearer_token TEXT NOT NULL,
                  payload_json TEXT NOT NULL,
                  attempt_count INTEGER NOT NULL,
                  next_attempt_at TEXT NOT NULL,
                  last_error TEXT
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS push_dead_letters (
                  sequence_no INTEGER NOT NULL,
                  task_id TEXT PRIMARY KEY,
                  idempotency_key TEXT NOT NULL,
                  target_url TEXT NOT NULL,
                  bearer_token TEXT NOT NULL,
                  payload_json TEXT NOT NULL,
                  attempt_count INTEGER NOT NULL,
                  next_attempt_at TEXT NOT NULL,
                  last_error TEXT
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS event_seen_keys (
                  dedupe_key TEXT PRIMARY KEY,
                  seen_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS network_policy (
                  singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                  policy_json TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS gray_rollout_policy (
                  singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                  policy_json TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_records (
                  id INTEGER PRIMARY KEY,
                  at TEXT NOT NULL,
                  action TEXT NOT NULL,
                  details_json TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_policy (
                  singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                  policy_json TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.commit()

    def load_devices(self) -> Dict[Tuple[str, str, str, str], dict]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT tenant_id, site_id, box_id, device_id, record_json
                FROM devices
                ORDER BY tenant_id, site_id, box_id, device_id
                """
            ).fetchall()

        items: Dict[Tuple[str, str, str, str], dict] = {}
        for row in rows:
            record = dict(json.loads(row["record_json"]))
            key = (str(row["tenant_id"]), str(row["site_id"]), str(row["box_id"]), str(row["device_id"]))
            items[key] = record
        return items

    def upsert_device(self, record: dict) -> None:
        key = (
            str(record["tenant_id"]),
            str(record["site_id"]),
            str(record["box_id"]),
            str(record["device_id"]),
        )
        payload = json.dumps(record, sort_keys=True, separators=(",", ":"))
        now = datetime.utcnow().isoformat()

        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO devices
                (tenant_id, site_id, box_id, device_id, record_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (key[0], key[1], key[2], key[3], payload, now),
            )
            self._conn.commit()

    def load_algorithms(self) -> Dict[Tuple[str, str], dict]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT algorithm_id, version, record_json
                FROM algorithms
                ORDER BY algorithm_id, version
                """
            ).fetchall()

        items: Dict[Tuple[str, str], dict] = {}
        for row in rows:
            record = dict(json.loads(row["record_json"]))
            key = (str(row["algorithm_id"]), str(row["version"]))
            items[key] = record
        return items

    def upsert_algorithm(self, record: dict) -> None:
        key = (str(record["algorithm_id"]), str(record["version"]))
        payload = json.dumps(record, sort_keys=True, separators=(",", ":"))
        now = datetime.utcnow().isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO algorithms
                (algorithm_id, version, record_json, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (key[0], key[1], payload, now),
            )
            self._conn.commit()

    def load_base_libraries(self) -> Dict[Tuple[str, str], dict]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT library_id, version, record_json
                FROM base_libraries
                ORDER BY library_id, version
                """
            ).fetchall()

        items: Dict[Tuple[str, str], dict] = {}
        for row in rows:
            record = dict(json.loads(row["record_json"]))
            key = (str(row["library_id"]), str(row["version"]))
            items[key] = record
        return items

    def upsert_base_library(self, record: dict) -> None:
        key = (str(record["library_id"]), str(record["version"]))
        payload = json.dumps(record, sort_keys=True, separators=(",", ":"))
        now = datetime.utcnow().isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO base_libraries
                (library_id, version, record_json, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (key[0], key[1], payload, now),
            )
            self._conn.commit()

    def load_base_library_mappings(self) -> Dict[Tuple[str, str, str, str, str], dict]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT tenant_id, site_id, box_id, device_id, capability, record_json
                FROM base_library_mappings
                ORDER BY tenant_id, site_id, box_id, device_id, capability
                """
            ).fetchall()

        items: Dict[Tuple[str, str, str, str, str], dict] = {}
        for row in rows:
            record = dict(json.loads(row["record_json"]))
            key = (
                str(row["tenant_id"]),
                str(row["site_id"]),
                str(row["box_id"]),
                str(row["device_id"]),
                str(row["capability"]),
            )
            items[key] = record
        return items

    def upsert_base_library_mapping(self, record: dict) -> None:
        key = (
            str(record["tenant_id"]),
            str(record["site_id"]),
            str(record["box_id"]),
            str(record["device_id"]),
            str(record["capability"]),
        )
        payload = json.dumps(record, sort_keys=True, separators=(",", ":"))
        now = datetime.utcnow().isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO base_library_mappings
                (tenant_id, site_id, box_id, device_id, capability, record_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (key[0], key[1], key[2], key[3], key[4], payload, now),
            )
            self._conn.commit()

    def load_base_library_compatibility_policy(self) -> dict:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT policy_json
                FROM base_library_compatibility_policy
                WHERE singleton_id = 1
                """
            ).fetchone()
        if row is None:
            return {
                "enforce_capability_match": True,
                "required_status": "active",
                "version_regex_by_capability": {},
                "semver_range_by_capability": {},
            }
        return dict(json.loads(str(row["policy_json"])))

    def replace_base_library_compatibility_policy(self, policy: dict) -> None:
        payload = json.dumps(policy, sort_keys=True, separators=(",", ":"))
        now = datetime.utcnow().isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO base_library_compatibility_policy
                (singleton_id, policy_json, updated_at)
                VALUES (1, ?, ?)
                """,
                (payload, now),
            )
            self._conn.commit()

    def load_offline_executors(self) -> Dict[str, dict]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT executor_id, record_json
                FROM offline_executors
                ORDER BY executor_id
                """
            ).fetchall()

        items: Dict[str, dict] = {}
        for row in rows:
            items[str(row["executor_id"])] = dict(json.loads(row["record_json"]))
        return items

    def upsert_offline_executor(self, record: dict) -> None:
        executor_id = str(record["executor_id"])
        payload = json.dumps(record, sort_keys=True, separators=(",", ":"))
        now = datetime.utcnow().isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO offline_executors
                (executor_id, record_json, updated_at)
                VALUES (?, ?, ?)
                """,
                (executor_id, payload, now),
            )
            self._conn.commit()

    def load_offline_jobs(self) -> Dict[str, dict]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT job_id, record_json
                FROM offline_jobs
                ORDER BY job_id
                """
            ).fetchall()

        items: Dict[str, dict] = {}
        for row in rows:
            items[str(row["job_id"])] = dict(json.loads(row["record_json"]))
        return items

    def upsert_offline_job(self, record: dict) -> None:
        job_id = str(record["job_id"])
        payload = json.dumps(record, sort_keys=True, separators=(",", ":"))
        now = datetime.utcnow().isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO offline_jobs
                (job_id, record_json, updated_at)
                VALUES (?, ?, ?)
                """,
                (job_id, payload, now),
            )
            self._conn.commit()

    def load_edge_agents(self) -> Dict[str, dict]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT agent_id, record_json
                FROM edge_agents
                ORDER BY agent_id
                """
            ).fetchall()

        items: Dict[str, dict] = {}
        for row in rows:
            items[str(row["agent_id"])] = dict(json.loads(row["record_json"]))
        return items

    def upsert_edge_agent(self, record: dict) -> None:
        agent_id = str(record["agent_id"])
        payload = json.dumps(record, sort_keys=True, separators=(",", ":"))
        now = datetime.utcnow().isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO edge_agents
                (agent_id, record_json, updated_at)
                VALUES (?, ?, ?)
                """,
                (agent_id, payload, now),
            )
            self._conn.commit()

    def load_offline_sync_cursors(self) -> Dict[Tuple[str, str, str], dict]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT tenant_id, site_id, box_id, record_json
                FROM offline_sync_cursors
                ORDER BY tenant_id, site_id, box_id
                """
            ).fetchall()

        items: Dict[Tuple[str, str, str], dict] = {}
        for row in rows:
            key = (str(row["tenant_id"]), str(row["site_id"]), str(row["box_id"]))
            items[key] = dict(json.loads(row["record_json"]))
        return items

    def upsert_offline_sync_cursor(self, record: dict) -> None:
        key = (str(record["tenant_id"]), str(record["site_id"]), str(record["box_id"]))
        payload = json.dumps(record, sort_keys=True, separators=(",", ":"))
        now = datetime.utcnow().isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO offline_sync_cursors
                (tenant_id, site_id, box_id, record_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (key[0], key[1], key[2], payload, now),
            )
            self._conn.commit()

    def load_offline_sync_stream_cursors(self) -> Dict[Tuple[str, str, str, str], dict]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT tenant_id, site_id, box_id, stream_id, record_json
                FROM offline_sync_stream_cursors
                ORDER BY tenant_id, site_id, box_id, stream_id
                """
            ).fetchall()

        items: Dict[Tuple[str, str, str, str], dict] = {}
        for row in rows:
            key = (str(row["tenant_id"]), str(row["site_id"]), str(row["box_id"]), str(row["stream_id"]))
            items[key] = dict(json.loads(row["record_json"]))
        return items

    def upsert_offline_sync_stream_cursor(self, record: dict) -> None:
        key = (
            str(record["tenant_id"]),
            str(record["site_id"]),
            str(record["box_id"]),
            str(record["stream_id"]),
        )
        payload = json.dumps(record, sort_keys=True, separators=(",", ":"))
        now = datetime.utcnow().isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO offline_sync_stream_cursors
                (tenant_id, site_id, box_id, stream_id, record_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (key[0], key[1], key[2], key[3], payload, now),
            )
            self._conn.commit()

    def load_push_state(self) -> PushState:
        with self._lock:
            queue_rows = self._conn.execute(
                """
                SELECT task_id, idempotency_key, target_url, bearer_token, payload_json,
                       attempt_count, next_attempt_at, last_error
                FROM push_queue
                ORDER BY sequence_no ASC
                """
            ).fetchall()
            dead_rows = self._conn.execute(
                """
                SELECT task_id, idempotency_key, target_url, bearer_token, payload_json,
                       attempt_count, next_attempt_at, last_error
                FROM push_dead_letters
                ORDER BY sequence_no ASC
                """
            ).fetchall()

        def _to_task(row: sqlite3.Row) -> PushTask:
            return PushTask(
                task_id=str(row["task_id"]),
                idempotency_key=str(row["idempotency_key"]),
                target_url=str(row["target_url"]),
                bearer_token=str(row["bearer_token"]),
                payload=dict(json.loads(row["payload_json"])),
                attempt_count=int(row["attempt_count"]),
                next_attempt_at=datetime.fromisoformat(str(row["next_attempt_at"])),
                last_error=str(row["last_error"]) if row["last_error"] is not None else None,
            )

        tasks = tuple(_to_task(row) for row in queue_rows)
        dead = tuple(_to_task(row) for row in dead_rows)
        return PushState(tasks=tasks, dead_letters=dead)

    def replace_push_state(self, state: PushState) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("DELETE FROM push_queue")
            cur.execute("DELETE FROM push_dead_letters")

            for idx, task in enumerate(state.tasks):
                cur.execute(
                    """
                    INSERT INTO push_queue
                    (sequence_no, task_id, idempotency_key, target_url, bearer_token,
                     payload_json, attempt_count, next_attempt_at, last_error)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        idx,
                        task.task_id,
                        task.idempotency_key,
                        task.target_url,
                        task.bearer_token,
                        json.dumps(task.payload, sort_keys=True, separators=(",", ":")),
                        int(task.attempt_count),
                        task.next_attempt_at.isoformat(),
                        task.last_error,
                    ),
                )

            for idx, task in enumerate(state.dead_letters):
                cur.execute(
                    """
                    INSERT INTO push_dead_letters
                    (sequence_no, task_id, idempotency_key, target_url, bearer_token,
                     payload_json, attempt_count, next_attempt_at, last_error)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        idx,
                        task.task_id,
                        task.idempotency_key,
                        task.target_url,
                        task.bearer_token,
                        json.dumps(task.payload, sort_keys=True, separators=(",", ":")),
                        int(task.attempt_count),
                        task.next_attempt_at.isoformat(),
                        task.last_error,
                    ),
                )
            self._conn.commit()

    def load_event_state(self) -> EventState:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT dedupe_key, seen_at
                FROM event_seen_keys
                ORDER BY seen_at ASC
                """
            ).fetchall()

        seen = tuple(
            SeenDedupKey(
                dedupe_key=str(row["dedupe_key"]),
                seen_at=datetime.fromisoformat(str(row["seen_at"])),
            )
            for row in rows
        )
        return EventState(seen_keys=seen)

    def replace_event_state(self, state: EventState) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("DELETE FROM event_seen_keys")
            for item in state.seen_keys:
                cur.execute(
                    """
                    INSERT INTO event_seen_keys (dedupe_key, seen_at)
                    VALUES (?, ?)
                    """,
                    (item.dedupe_key, item.seen_at.isoformat()),
                )
            self._conn.commit()

    def load_network_policy(self) -> dict:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT policy_json
                FROM network_policy
                WHERE singleton_id = 1
                """
            ).fetchone()
        if row is None:
            return {"enforce_allowlist": False, "webhook_allowlist": []}
        return dict(json.loads(str(row["policy_json"])))

    def replace_network_policy(self, policy: dict) -> None:
        payload = json.dumps(policy, sort_keys=True, separators=(",", ":"))
        now = datetime.utcnow().isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO network_policy
                (singleton_id, policy_json, updated_at)
                VALUES (1, ?, ?)
                """,
                (payload, now),
            )
            self._conn.commit()

    def load_gray_rollout_policy(self) -> dict:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT policy_json
                FROM gray_rollout_policy
                WHERE singleton_id = 1
                """
            ).fetchone()
        if row is None:
            return {"enabled": False, "default_percent": 0, "overrides": []}
        return dict(json.loads(str(row["policy_json"])))

    def replace_gray_rollout_policy(self, policy: dict) -> None:
        payload = json.dumps(policy, sort_keys=True, separators=(",", ":"))
        now = datetime.utcnow().isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO gray_rollout_policy
                (singleton_id, policy_json, updated_at)
                VALUES (1, ?, ?)
                """,
                (payload, now),
            )
            self._conn.commit()

    def load_audit_records(self, limit: int = 2000) -> list[dict]:
        capped = max(1, min(5000, int(limit)))
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, at, action, details_json
                FROM audit_records
                ORDER BY id ASC
                LIMIT ?
                """,
                (capped,),
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "at": str(row["at"]),
                "action": str(row["action"]),
                "details": dict(json.loads(str(row["details_json"]))),
            }
            for row in rows
        ]

    def append_audit_record(self, record: dict) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO audit_records
                (id, at, action, details_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    int(record["id"]),
                    str(record["at"]),
                    str(record["action"]),
                    json.dumps(record.get("details", {}), sort_keys=True, separators=(",", ":")),
                ),
            )
            self._conn.commit()

    def prune_audit_records(self, max_records: int) -> None:
        capped = max(1, int(max_records))
        with self._lock:
            self._conn.execute(
                """
                DELETE FROM audit_records
                WHERE id NOT IN (
                  SELECT id
                  FROM audit_records
                  ORDER BY id DESC
                  LIMIT ?
                )
                """,
                (capped,),
            )
            self._conn.commit()

    def load_audit_policy(self) -> dict:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT policy_json
                FROM audit_policy
                WHERE singleton_id = 1
                """
            ).fetchone()
        if row is None:
            return {"max_records": 2000}
        return dict(json.loads(str(row["policy_json"])))

    def replace_audit_policy(self, policy: dict) -> None:
        payload = json.dumps(policy, sort_keys=True, separators=(",", ":"))
        now = datetime.utcnow().isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO audit_policy
                (singleton_id, policy_json, updated_at)
                VALUES (1, ?, ?)
                """,
                (payload, now),
            )
            self._conn.commit()

    def stats(self) -> dict:
        with self._lock:
            device_count = int(self._conn.execute("SELECT COUNT(1) FROM devices").fetchone()[0])
            algorithm_count = int(self._conn.execute("SELECT COUNT(1) FROM algorithms").fetchone()[0])
            base_library_count = int(self._conn.execute("SELECT COUNT(1) FROM base_libraries").fetchone()[0])
            base_library_mapping_count = int(self._conn.execute("SELECT COUNT(1) FROM base_library_mappings").fetchone()[0])
            base_library_compatibility_policy_count = int(
                self._conn.execute("SELECT COUNT(1) FROM base_library_compatibility_policy").fetchone()[0]
            )
            offline_executor_count = int(self._conn.execute("SELECT COUNT(1) FROM offline_executors").fetchone()[0])
            offline_job_count = int(self._conn.execute("SELECT COUNT(1) FROM offline_jobs").fetchone()[0])
            edge_agent_count = int(self._conn.execute("SELECT COUNT(1) FROM edge_agents").fetchone()[0])
            offline_sync_cursor_count = int(self._conn.execute("SELECT COUNT(1) FROM offline_sync_cursors").fetchone()[0])
            offline_sync_stream_cursor_count = int(
                self._conn.execute("SELECT COUNT(1) FROM offline_sync_stream_cursors").fetchone()[0]
            )
            push_queue_count = int(self._conn.execute("SELECT COUNT(1) FROM push_queue").fetchone()[0])
            dead_letter_count = int(self._conn.execute("SELECT COUNT(1) FROM push_dead_letters").fetchone()[0])
            event_seen_count = int(self._conn.execute("SELECT COUNT(1) FROM event_seen_keys").fetchone()[0])
            audit_count = int(self._conn.execute("SELECT COUNT(1) FROM audit_records").fetchone()[0])
            audit_policy_count = int(self._conn.execute("SELECT COUNT(1) FROM audit_policy").fetchone()[0])
            network_policy_count = int(self._conn.execute("SELECT COUNT(1) FROM network_policy").fetchone()[0])
            gray_rollout_policy_count = int(self._conn.execute("SELECT COUNT(1) FROM gray_rollout_policy").fetchone()[0])
        return {
            "db_path": self._db_path,
            "device_count": device_count,
            "algorithm_count": algorithm_count,
            "base_library_count": base_library_count,
            "base_library_mapping_count": base_library_mapping_count,
            "base_library_compatibility_policy_count": base_library_compatibility_policy_count,
            "offline_executor_count": offline_executor_count,
            "offline_job_count": offline_job_count,
            "edge_agent_count": edge_agent_count,
            "offline_sync_cursor_count": offline_sync_cursor_count,
            "offline_sync_stream_cursor_count": offline_sync_stream_cursor_count,
            "push_queue_count": push_queue_count,
            "dead_letter_count": dead_letter_count,
            "event_seen_count": event_seen_count,
            "audit_count": audit_count,
            "audit_policy_count": audit_policy_count,
            "network_policy_count": network_policy_count,
            "gray_rollout_policy_count": gray_rollout_policy_count,
        }

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._conn.close()
            self._closed = True
