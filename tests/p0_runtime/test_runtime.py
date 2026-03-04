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
