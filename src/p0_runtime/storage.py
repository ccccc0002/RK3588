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
                CREATE TABLE IF NOT EXISTS audit_records (
                  id INTEGER PRIMARY KEY,
                  at TEXT NOT NULL,
                  action TEXT NOT NULL,
                  details_json TEXT NOT NULL
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

    def stats(self) -> dict:
        with self._lock:
            device_count = int(self._conn.execute("SELECT COUNT(1) FROM devices").fetchone()[0])
            push_queue_count = int(self._conn.execute("SELECT COUNT(1) FROM push_queue").fetchone()[0])
            dead_letter_count = int(self._conn.execute("SELECT COUNT(1) FROM push_dead_letters").fetchone()[0])
            event_seen_count = int(self._conn.execute("SELECT COUNT(1) FROM event_seen_keys").fetchone()[0])
            audit_count = int(self._conn.execute("SELECT COUNT(1) FROM audit_records").fetchone()[0])
            network_policy_count = int(self._conn.execute("SELECT COUNT(1) FROM network_policy").fetchone()[0])
        return {
            "db_path": self._db_path,
            "device_count": device_count,
            "push_queue_count": push_queue_count,
            "dead_letter_count": dead_letter_count,
            "event_seen_count": event_seen_count,
            "audit_count": audit_count,
            "network_policy_count": network_policy_count,
        }

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._conn.close()
            self._closed = True
