import unittest
from datetime import datetime, timezone

from src.p0_runtime.runtime import P0Runtime


class P0RuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 3, 3, 8, 0, 0, tzinfo=timezone.utc)
        self.runtime = P0Runtime(webhook_url="https://example.com/hook", webhook_token="token")

    def test_join_leave_flow_returns_expected_states(self) -> None:
        join_res = self.runtime.viewer_join(stream_id="cam-1", now=self.now)
        self.assertEqual("RESUMING", join_res["state"])

        self.runtime.tick(now=self.now.replace(second=6))
        leave_res = self.runtime.viewer_leave(stream_id="cam-1", now=self.now.replace(second=8))

        self.assertEqual("IDLE_PENDING", leave_res["state"])

    def test_event_duplicate_returns_conflict(self) -> None:
        payload = {
            "tenant_id": "t1",
            "site_id": "s1",
            "box_id": "b1",
            "source_id": "cam-1",
            "event_type": "line_crossing",
            "object_id": "p1",
            "payload": {"confidence": 0.92},
        }

        first = self.runtime.ingest_event(payload, now=self.now)
        second = self.runtime.ingest_event(payload, now=self.now.replace(second=10))

        self.assertEqual(202, first["status"])
        self.assertEqual(409, second["status"])

    def test_issue_token_and_authz(self) -> None:
        token_res = self.runtime.issue_token(user_id="u1", role="admin", now=self.now)
        ok, context = self.runtime.authorize(
            token=token_res["token"],
            required_action="license:update",
            now=self.now.replace(second=10),
        )

        self.assertTrue(ok)
        self.assertEqual("admin", context["role"])

    def test_update_device_capabilities(self) -> None:
        self.runtime.register_device(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-1",
                "protocol": "rtsp",
                "stream_url": "rtsp://10.0.0.2/live",
                "enabled": True,
            }
        )
        updated = self.runtime.update_device_capabilities(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-1",
                "capabilities": {"ocr": True, "face": False},
            }
        )

        self.assertEqual({"ocr": True, "face": False}, updated["capabilities"])
        listed = self.runtime.list_devices()
        self.assertEqual({"ocr": True, "face": False}, listed[0]["capabilities"])

    def test_upsert_and_list_algorithms(self) -> None:
        created = self.runtime.upsert_algorithm(
            {
                "algorithm_id": "face-detector",
                "version": "1.0.0",
                "status": "active",
                "capabilities": ["face"],
            }
        )
        self.assertEqual("face-detector", created["algorithm_id"])
        self.assertEqual("1.0.0", created["version"])
        self.assertEqual("active", created["status"])

        self.runtime.upsert_algorithm(
            {
                "algorithm_id": "ocr-engine",
                "version": "2.1.0",
                "status": "draft",
                "capabilities": ["ocr"],
            }
        )

        items = self.runtime.list_algorithms()
        pairs = {(item["algorithm_id"], item["version"]) for item in items}
        self.assertIn(("face-detector", "1.0.0"), pairs)
        self.assertIn(("ocr-engine", "2.1.0"), pairs)

    def test_upsert_base_library_and_mapping(self) -> None:
        self.runtime.register_device(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-lib",
                "protocol": "rtsp",
                "stream_url": "rtsp://10.0.0.111/live",
                "enabled": True,
            }
        )
        library = self.runtime.upsert_base_library(
            {
                "library_id": "lib-face-core",
                "version": "2026.03",
                "capability": "face",
                "status": "active",
                "metadata": {"vendor": "rk"},
            }
        )
        self.assertEqual("lib-face-core", library["library_id"])

        mapping = self.runtime.upsert_base_library_mapping(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-lib",
                "capability": "face",
                "library_id": "lib-face-core",
                "library_version": "2026.03",
            }
        )
        self.assertEqual("cam-lib", mapping["device_id"])
        self.assertEqual("lib-face-core", mapping["library_id"])

        libs = self.runtime.list_base_libraries()
        self.assertEqual(1, len(libs))
        mappings = self.runtime.list_base_library_mappings()
        self.assertEqual(1, len(mappings))

    def test_base_library_compatibility_policy_rejects_version_mismatch(self) -> None:
        self.runtime.register_device(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-lib-policy",
                "protocol": "rtsp",
                "stream_url": "rtsp://10.0.0.112/live",
                "enabled": True,
            }
        )
        self.runtime.upsert_base_library(
            {
                "library_id": "lib-ocr-policy",
                "version": "2026.03",
                "capability": "ocr",
                "status": "active",
            }
        )
        updated_policy = self.runtime.update_base_library_compatibility_policy(
            {
                "enforce_capability_match": True,
                "required_status": "active",
                "version_regex_by_capability": {"ocr": r"^2027\\."},
            }
        )
        self.assertEqual("active", updated_policy["required_status"])

        with self.assertRaises(ValueError):
            self.runtime.upsert_base_library_mapping(
                {
                    "tenant_id": "t1",
                    "site_id": "s1",
                    "box_id": "b1",
                    "device_id": "cam-lib-policy",
                    "capability": "ocr",
                    "library_id": "lib-ocr-policy",
                    "library_version": "2026.03",
                }
            )

    def test_offline_executor_binding_auto_selects_active_executor(self) -> None:
        self.runtime.upsert_algorithm(
            {
                "algorithm_id": "offline-detector-exec",
                "version": "1.0.0",
                "status": "active",
                "capabilities": ["face"],
            }
        )
        self.runtime.upsert_offline_executor(
            {
                "executor_id": "exec-1",
                "endpoint": "http://executor.local:9001",
                "status": "active",
                "capabilities": ["face"],
            }
        )
        job = self.runtime.create_offline_job(
            {
                "job_id": "job-exec-001",
                "source_scope": {"tenant_id": "t1", "site_id": "s1"},
                "algorithm_id": "offline-detector-exec",
                "algorithm_version": "1.0.0",
            },
            now=self.now,
        )
        self.assertEqual("exec-1", job["executor_id"])

    def test_batch_mapping_upsert_and_offline_status_update(self) -> None:
        self.runtime.register_device(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-batch-1",
                "protocol": "rtsp",
                "stream_url": "rtsp://10.0.0.121/live",
                "enabled": True,
            }
        )
        self.runtime.register_device(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-batch-2",
                "protocol": "rtsp",
                "stream_url": "rtsp://10.0.0.122/live",
                "enabled": True,
            }
        )
        self.runtime.upsert_base_library(
            {
                "library_id": "lib-face-batch",
                "version": "2026.05",
                "capability": "face",
                "status": "active",
            }
        )

        mappings = self.runtime.batch_upsert_base_library_mappings(
            {
                "items": [
                    {
                        "tenant_id": "t1",
                        "site_id": "s1",
                        "box_id": "b1",
                        "device_id": "cam-batch-1",
                        "capability": "face",
                        "library_id": "lib-face-batch",
                        "library_version": "2026.05",
                    },
                    {
                        "tenant_id": "t1",
                        "site_id": "s1",
                        "box_id": "b1",
                        "device_id": "cam-batch-2",
                        "capability": "face",
                        "library_id": "lib-face-batch",
                        "library_version": "2026.05",
                    },
                ]
            }
        )
        self.assertEqual(2, len(mappings))

        self.runtime.upsert_algorithm(
            {
                "algorithm_id": "offline-batch",
                "version": "1.0.0",
                "status": "active",
                "capabilities": ["face"],
            }
        )
        self.runtime.create_offline_job(
            {
                "job_id": "job-batch-1",
                "source_scope": {"tenant_id": "t1", "site_id": "s1"},
                "algorithm_id": "offline-batch",
                "algorithm_version": "1.0.0",
            },
            now=self.now,
        )
        self.runtime.create_offline_job(
            {
                "job_id": "job-batch-2",
                "source_scope": {"tenant_id": "t1", "site_id": "s1"},
                "algorithm_id": "offline-batch",
                "algorithm_version": "1.0.0",
            },
            now=self.now,
        )

        updates = self.runtime.batch_update_offline_job_status(
            {
                "items": [
                    {"job_id": "job-batch-1", "status": "running"},
                    {"job_id": "job-batch-2", "status": "running"},
                ]
            },
            now=self.now.replace(second=8),
        )
        self.assertEqual(2, len(updates))
        self.assertTrue(all(item["status"] == "running" for item in updates))

    def test_offline_job_lifecycle(self) -> None:
        self.runtime.upsert_algorithm(
            {
                "algorithm_id": "offline-detector",
                "version": "1.0.0",
                "status": "active",
                "capabilities": ["face"],
            }
        )
        job = self.runtime.create_offline_job(
            {
                "job_id": "job-001",
                "source_scope": {"tenant_id": "t1", "site_id": "s1"},
                "algorithm_id": "offline-detector",
                "algorithm_version": "1.0.0",
            },
            now=self.now,
        )
        self.assertEqual("queued", job["status"])

        running = self.runtime.update_offline_job_status(
            {
                "job_id": "job-001",
                "status": "running",
            },
            now=self.now.replace(second=5),
        )
        self.assertEqual("running", running["status"])

        done = self.runtime.update_offline_job_status(
            {
                "job_id": "job-001",
                "status": "succeeded",
                "result_ref": "s3://bucket/job-001.json",
            },
            now=self.now.replace(second=10),
        )
        self.assertEqual("succeeded", done["status"])

        with self.assertRaises(ValueError):
            self.runtime.update_offline_job_status(
                {
                    "job_id": "job-001",
                    "status": "running",
                },
                now=self.now.replace(second=15),
            )

    def test_capability_schedule_prioritizes_face_stream(self) -> None:
        self.runtime.register_device(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-face",
                "protocol": "rtsp",
                "stream_url": "rtsp://10.0.0.20/live",
                "capabilities": {"ocr": True, "face": True},
                "enabled": True,
            }
        )
        self.runtime.register_device(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-basic",
                "protocol": "rtsp",
                "stream_url": "rtsp://10.0.0.21/live",
                "capabilities": {"ocr": False, "face": False},
                "enabled": True,
            }
        )

        plan = self.runtime.plan_capability_schedule(budget=10.0)
        streams = {item["device_id"]: item for item in plan["streams"]}

        self.assertTrue(plan["degraded"])
        self.assertIn("cam-face", streams)
        self.assertIn("cam-basic", streams)
        self.assertGreaterEqual(streams["cam-face"]["sample_fps"], streams["cam-basic"]["sample_fps"])

    def test_capability_schedule_uses_stream_telemetry_fps(self) -> None:
        self.runtime.register_device(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-telemetry-low",
                "protocol": "rtsp",
                "stream_url": "rtsp://10.0.0.50/live",
                "enabled": True,
            }
        )
        self.runtime.register_device(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-telemetry-high",
                "protocol": "rtsp",
                "stream_url": "rtsp://10.0.0.51/live",
                "enabled": True,
            }
        )
        self.runtime.update_stream_telemetry(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-telemetry-low",
                "fps_in": 2.0,
            },
            now=self.now,
        )
        self.runtime.update_stream_telemetry(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-telemetry-high",
                "fps_in": 16.0,
            },
            now=self.now,
        )

        plan = self.runtime.plan_capability_schedule(budget=100.0)
        streams = {item["device_id"]: item for item in plan["streams"]}
        self.assertGreater(streams["cam-telemetry-high"]["sample_fps"], streams["cam-telemetry-low"]["sample_fps"])
        self.assertLessEqual(streams["cam-telemetry-low"]["sample_fps"], 2.0)

    def test_audit_records_capture_device_changes(self) -> None:
        self.runtime.register_device(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-audit",
                "protocol": "rtsp",
                "stream_url": "rtsp://10.0.0.40/live",
                "enabled": True,
            }
        )
        self.runtime.update_device_capabilities(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-audit",
                "capabilities": {"ocr": True, "face": False},
            }
        )

        records = self.runtime.list_audit_records(limit=10)
        actions = [item["action"] for item in records]
        self.assertIn("device.register", actions)
        self.assertIn("device.capabilities.update", actions)

    def test_audit_policy_limits_record_count(self) -> None:
        updated = self.runtime.update_audit_policy({"max_records": 3})
        self.assertEqual(3, updated["max_records"])
        self.assertEqual(3, self.runtime.get_audit_policy()["max_records"])

        for idx in range(6):
            self.runtime.register_device(
                {
                    "tenant_id": "t1",
                    "site_id": "s1",
                    "box_id": "b1",
                    "device_id": f"cam-retain-{idx}",
                    "protocol": "rtsp",
                    "stream_url": f"rtsp://10.0.0.{70 + idx}/live",
                    "enabled": True,
                }
            )

        records = self.runtime.list_audit_records(limit=20)
        self.assertLessEqual(len(records), 3)

    def test_update_and_get_network_policy(self) -> None:
        updated = self.runtime.update_network_policy(
            {
                "enforce_allowlist": True,
                "webhook_allowlist": ["https://hooks.example.com", "http://10.0.0.5:8080"],
            }
        )
        self.assertTrue(updated["enforce_allowlist"])
        self.assertEqual(2, len(updated["webhook_allowlist"]))

        current = self.runtime.get_network_policy()
        self.assertEqual(updated, current)

    def test_dispatch_respects_network_policy_allowlist(self) -> None:
        self.runtime.update_network_policy(
            {
                "enforce_allowlist": True,
                "webhook_allowlist": ["https://hooks.example.com"],
            }
        )
        self.runtime.ingest_event(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "source_id": "cam-1",
                "event_type": "line_crossing",
                "object_id": "p1",
                "payload": {"confidence": 0.88},
            },
            now=self.now,
        )

        sent_targets = []

        def sender(task) -> bool:
            sent_targets.append(task.target_url)
            return True

        result = self.runtime.dispatch_pushes(now=self.now, sender=sender)
        self.assertEqual(0, result["sent"])
        self.assertEqual(1, result["failed"])
        self.assertEqual([], sent_targets)
        first_snap = self.runtime.snapshot()
        self.assertEqual(0, first_snap["push_queue_size"])
        self.assertEqual(1, first_snap["dead_letter_size"])

        second = self.runtime.dispatch_pushes(now=self.now.replace(second=20), sender=sender)
        self.assertEqual(0, second["processed"])
        self.assertEqual(0, second["failed"])


if __name__ == "__main__":
    unittest.main()
