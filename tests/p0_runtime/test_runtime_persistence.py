import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from src.p0_runtime.runtime import P0Runtime


class P0RuntimePersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 3, 3, 8, 0, 0, tzinfo=timezone.utc)
        self.event = {
            "tenant_id": "t1",
            "site_id": "s1",
            "box_id": "b1",
            "source_id": "cam-1",
            "event_type": "line_crossing",
            "object_id": "p1",
            "payload": {"confidence": 0.9},
        }

    def _runtime(self, db_path: str) -> P0Runtime:
        return P0Runtime(
            webhook_url="https://example.com/hook",
            webhook_token="token",
            storage_db_path=db_path,
        )

    def test_device_registry_recovers_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "runtime.db")
            rt1 = self._runtime(db_path)
            rt2 = None
            try:
                rt1.register_device(
                    {
                        "tenant_id": "t1",
                        "site_id": "s1",
                        "box_id": "b1",
                        "device_id": "cam-persist",
                        "protocol": "rtsp",
                        "stream_url": "rtsp://10.0.0.8/live",
                        "enabled": True,
                    }
                )

                rt2 = self._runtime(db_path)
                devices = rt2.list_devices()
                self.assertEqual(1, len(devices))
                self.assertEqual("cam-persist", devices[0]["device_id"])
            finally:
                rt1.close()
                if rt2 is not None:
                    rt2.close()

    def test_algorithm_registry_recovers_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "runtime.db")
            rt1 = self._runtime(db_path)
            rt2 = None
            try:
                rt1.upsert_algorithm(
                    {
                        "algorithm_id": "detector-a",
                        "version": "1.0.0",
                        "status": "active",
                        "capabilities": ["face"],
                    }
                )

                rt2 = self._runtime(db_path)
                items = rt2.list_algorithms()
                self.assertEqual(1, len(items))
                self.assertEqual("detector-a", items[0]["algorithm_id"])
                self.assertEqual("1.0.0", items[0]["version"])
            finally:
                rt1.close()
                if rt2 is not None:
                    rt2.close()

    def test_base_library_and_mapping_recover_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "runtime.db")
            rt1 = self._runtime(db_path)
            rt2 = None
            try:
                rt1.register_device(
                    {
                        "tenant_id": "t1",
                        "site_id": "s1",
                        "box_id": "b1",
                        "device_id": "cam-lib-persist",
                        "protocol": "rtsp",
                        "stream_url": "rtsp://10.0.0.120/live",
                        "enabled": True,
                    }
                )
                rt1.upsert_base_library(
                    {
                        "library_id": "lib-ocr-core",
                        "version": "2026.03",
                        "capability": "ocr",
                        "status": "active",
                    }
                )
                rt1.upsert_base_library_mapping(
                    {
                        "tenant_id": "t1",
                        "site_id": "s1",
                        "box_id": "b1",
                        "device_id": "cam-lib-persist",
                        "capability": "ocr",
                        "library_id": "lib-ocr-core",
                        "library_version": "2026.03",
                    }
                )

                rt2 = self._runtime(db_path)
                self.assertEqual(1, len(rt2.list_base_libraries()))
                self.assertEqual(1, len(rt2.list_base_library_mappings()))
            finally:
                rt1.close()
                if rt2 is not None:
                    rt2.close()

    def test_base_library_compatibility_policy_recovers_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "runtime.db")
            rt1 = self._runtime(db_path)
            rt2 = None
            try:
                rt1.update_base_library_compatibility_policy(
                    {
                        "enforce_capability_match": True,
                        "required_status": "active",
                        "version_regex_by_capability": {"face": r"^2026\\."},
                        "semver_range_by_capability": {"face": {"min": "1.0.0", "max": "2.0.0"}},
                    }
                )

                rt2 = self._runtime(db_path)
                policy = rt2.get_base_library_compatibility_policy()
                self.assertTrue(policy["enforce_capability_match"])
                self.assertEqual("active", policy["required_status"])
                self.assertIn("face", policy["version_regex_by_capability"])
                self.assertIn("face", policy["semver_range_by_capability"])
            finally:
                rt1.close()
                if rt2 is not None:
                    rt2.close()

    def test_offline_executor_registry_recovers_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "runtime.db")
            rt1 = self._runtime(db_path)
            rt2 = None
            try:
                rt1.upsert_offline_executor(
                    {
                        "executor_id": "exec-persist-1",
                        "endpoint": "http://executor.local:9002",
                        "status": "active",
                        "capabilities": ["ocr"],
                        "last_heartbeat_at": self.now.isoformat(),
                    }
                )

                rt2 = self._runtime(db_path)
                executors = rt2.list_offline_executors()
                self.assertEqual(1, len(executors))
                self.assertEqual("exec-persist-1", executors[0]["executor_id"])
                self.assertEqual(self.now.isoformat(), executors[0]["last_heartbeat_at"])
            finally:
                rt1.close()
                if rt2 is not None:
                    rt2.close()

    def test_offline_jobs_recover_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "runtime.db")
            rt1 = self._runtime(db_path)
            rt2 = None
            try:
                rt1.upsert_algorithm(
                    {
                        "algorithm_id": "offline-detector-persist",
                        "version": "1.0.0",
                        "status": "active",
                        "capabilities": ["face"],
                    }
                )
                rt1.create_offline_job(
                    {
                        "job_id": "job-persist-1",
                        "source_scope": {"tenant_id": "t1", "site_id": "s1"},
                        "algorithm_id": "offline-detector-persist",
                        "algorithm_version": "1.0.0",
                    },
                    now=self.now,
                )

                rt2 = self._runtime(db_path)
                jobs = rt2.list_offline_jobs()
                self.assertEqual(1, len(jobs))
                self.assertEqual("job-persist-1", jobs[0]["job_id"])
            finally:
                rt1.close()
                if rt2 is not None:
                    rt2.close()

    def test_offline_job_lease_fields_recover_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "runtime.db")
            rt1 = self._runtime(db_path)
            rt2 = None
            try:
                rt1.register_edge_agent(
                    {
                        "agent_id": "edge-agent-lease-persist",
                        "tenant_id": "t1",
                        "site_id": "s1",
                        "box_id": "b1",
                        "endpoint": "http://edge-agent.local:9402",
                        "status": "active",
                        "capabilities": ["sync"],
                    }
                )
                rt1.heartbeat_edge_agent({"agent_id": "edge-agent-lease-persist"}, now=self.now)
                rt1.upsert_algorithm(
                    {
                        "algorithm_id": "offline-detector-lease-persist",
                        "version": "1.0.0",
                        "status": "active",
                        "capabilities": ["face"],
                    }
                )
                rt1.create_offline_job(
                    {
                        "job_id": "job-lease-persist-1",
                        "source_scope": {"tenant_id": "t1", "site_id": "s1", "box_id": "b1"},
                        "algorithm_id": "offline-detector-lease-persist",
                        "algorithm_version": "1.0.0",
                    },
                    now=self.now,
                )
                rt1.lease_offline_job_to_edge_agent(
                    {"agent_id": "edge-agent-lease-persist", "lease_seconds": 120},
                    now=self.now,
                )

                rt2 = self._runtime(db_path)
                jobs = rt2.list_offline_jobs()
                self.assertEqual(1, len(jobs))
                self.assertEqual("job-lease-persist-1", jobs[0]["job_id"])
                self.assertEqual("edge-agent-lease-persist", jobs[0]["lease_agent_id"])
                self.assertTrue(bool(jobs[0]["lease_token"]))
                self.assertTrue(bool(jobs[0]["lease_expires_at"]))
            finally:
                rt1.close()
                if rt2 is not None:
                    rt2.close()

    def test_edge_agent_registry_recovers_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "runtime.db")
            rt1 = self._runtime(db_path)
            rt2 = None
            try:
                rt1.register_edge_agent(
                    {
                        "agent_id": "edge-agent-persist",
                        "tenant_id": "t1",
                        "site_id": "s1",
                        "box_id": "b1",
                        "endpoint": "http://edge-agent.local:9401",
                        "status": "active",
                        "capabilities": ["sync"],
                    }
                )
                rt1.heartbeat_edge_agent({"agent_id": "edge-agent-persist"}, now=self.now)

                rt2 = self._runtime(db_path)
                agents = rt2.list_edge_agents(now=self.now)
                self.assertEqual(1, len(agents))
                self.assertEqual("edge-agent-persist", agents[0]["agent_id"])
                self.assertEqual("healthy", agents[0]["health_state"])
            finally:
                rt1.close()
                if rt2 is not None:
                    rt2.close()

    def test_offline_sync_cursor_recovers_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "runtime.db")
            rt1 = self._runtime(db_path)
            rt2 = None
            try:
                rt1.upsert_offline_sync_cursor(
                    {
                        "tenant_id": "t1",
                        "site_id": "s1",
                        "box_id": "b1",
                        "cursor": "evt-200",
                    },
                    now=self.now,
                )

                rt2 = self._runtime(db_path)
                cursors = rt2.list_offline_sync_cursors()
                self.assertEqual(1, len(cursors))
                self.assertEqual("evt-200", cursors[0]["cursor"])
                self.assertEqual(1, cursors[0]["version"])
            finally:
                rt1.close()
                if rt2 is not None:
                    rt2.close()

    def test_gray_rollout_policy_recovers_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "runtime.db")
            rt1 = self._runtime(db_path)
            rt2 = None
            try:
                rt1.update_gray_rollout_policy(
                    {
                        "enabled": True,
                        "default_percent": 15,
                        "overrides": [
                            {"tenant_id": "t1", "site_id": "s1", "box_id": "b1", "percent": 100},
                        ],
                    }
                )

                rt2 = self._runtime(db_path)
                policy = rt2.get_gray_rollout_policy()
                self.assertTrue(policy["enabled"])
                self.assertEqual(15, policy["default_percent"])
                self.assertEqual(1, len(policy["overrides"]))
            finally:
                rt1.close()
                if rt2 is not None:
                    rt2.close()

    def test_push_queue_recovers_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "runtime.db")
            rt1 = self._runtime(db_path)
            rt2 = None
            try:
                rt1.ingest_event(self.event, now=self.now)
                self.assertEqual(1, rt1.snapshot()["push_queue_size"])

                rt2 = self._runtime(db_path)
                self.assertEqual(1, rt2.snapshot()["push_queue_size"])
                result = rt2.dispatch_pushes(now=self.now, sender=lambda _task: True)
                self.assertEqual(1, result["sent"])
                self.assertEqual(0, rt2.snapshot()["push_queue_size"])
            finally:
                rt1.close()
                if rt2 is not None:
                    rt2.close()

    def test_dead_letter_recovers_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "runtime.db")
            rt1 = self._runtime(db_path)
            rt2 = None
            try:
                rt1.ingest_event(self.event, now=self.now)

                always_fail = lambda _task: False
                rt1.dispatch_pushes(now=self.now, sender=always_fail)
                rt1.dispatch_pushes(now=self.now + timedelta(seconds=2), sender=always_fail)
                rt1.dispatch_pushes(now=self.now + timedelta(seconds=6), sender=always_fail)
                self.assertEqual(1, rt1.snapshot()["dead_letter_size"])

                rt2 = self._runtime(db_path)
                self.assertEqual(1, rt2.snapshot()["dead_letter_size"])
            finally:
                rt1.close()
                if rt2 is not None:
                    rt2.close()

    def test_event_dedupe_window_recovers_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "runtime.db")
            rt1 = self._runtime(db_path)
            rt2 = None
            try:
                first = rt1.ingest_event(self.event, now=self.now)
                self.assertEqual(202, first["status"])

                rt2 = self._runtime(db_path)
                second = rt2.ingest_event(self.event, now=self.now + timedelta(seconds=10))
                self.assertEqual(409, second["status"])
            finally:
                rt1.close()
                if rt2 is not None:
                    rt2.close()

    def test_metrics_expose_storage_stats(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "runtime.db")
            rt = self._runtime(db_path)
            try:
                rt.register_device(
                    {
                        "tenant_id": "t1",
                        "site_id": "s1",
                        "box_id": "b1",
                        "device_id": "cam-metrics",
                        "protocol": "rtsp",
                        "stream_url": "rtsp://10.0.0.10/live",
                        "enabled": True,
                    }
                )
                rt.ingest_event(self.event, now=self.now)

                metrics = rt.get_metrics()
                self.assertTrue(metrics["storage_enabled"])
                self.assertIsNotNone(metrics["storage"])
                self.assertEqual(1, metrics["storage"]["device_count"])
                self.assertEqual(1, metrics["storage"]["push_queue_count"])
            finally:
                rt.close()

    def test_network_policy_recovers_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "runtime.db")
            rt1 = self._runtime(db_path)
            rt2 = None
            try:
                rt1.update_network_policy(
                    {
                        "enforce_allowlist": True,
                        "webhook_allowlist": ["https://hooks.example.com"],
                    }
                )

                rt2 = self._runtime(db_path)
                policy = rt2.get_network_policy()
                self.assertTrue(policy["enforce_allowlist"])
                self.assertEqual(["https://hooks.example.com"], policy["webhook_allowlist"])
            finally:
                rt1.close()
                if rt2 is not None:
                    rt2.close()

    def test_audit_records_recover_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "runtime.db")
            rt1 = self._runtime(db_path)
            rt2 = None
            try:
                rt1.register_device(
                    {
                        "tenant_id": "t1",
                        "site_id": "s1",
                        "box_id": "b1",
                        "device_id": "cam-audit-persist",
                        "protocol": "rtsp",
                        "stream_url": "rtsp://10.0.0.88/live",
                        "enabled": True,
                    }
                )

                rt2 = self._runtime(db_path)
                records = rt2.list_audit_records(limit=10)
                actions = [item["action"] for item in records]
                self.assertIn("device.register", actions)
            finally:
                rt1.close()
                if rt2 is not None:
                    rt2.close()

    def test_audit_policy_recovers_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "runtime.db")
            rt1 = self._runtime(db_path)
            rt2 = None
            try:
                rt1.update_audit_policy({"max_records": 2})
                for idx in range(4):
                    rt1.register_device(
                        {
                            "tenant_id": "t1",
                            "site_id": "s1",
                            "box_id": "b1",
                            "device_id": f"cam-audit-policy-{idx}",
                            "protocol": "rtsp",
                            "stream_url": f"rtsp://10.0.1.{idx}/live",
                            "enabled": True,
                        }
                    )

                rt2 = self._runtime(db_path)
                policy = rt2.get_audit_policy()
                self.assertEqual(2, policy["max_records"])
                self.assertLessEqual(len(rt2.list_audit_records(limit=20)), 2)
            finally:
                rt1.close()
                if rt2 is not None:
                    rt2.close()


if __name__ == "__main__":
    unittest.main()
