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


if __name__ == "__main__":
    unittest.main()
