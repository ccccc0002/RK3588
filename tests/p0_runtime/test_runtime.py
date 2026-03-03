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


if __name__ == "__main__":
    unittest.main()
