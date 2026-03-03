import time
import unittest
from datetime import datetime, timedelta, timezone

from src.p0_runtime.runtime import P0Runtime


class P0PushDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 3, 3, 8, 0, 0, tzinfo=timezone.utc)
        self.runtime = P0Runtime(webhook_url="https://example.com/hook", webhook_token="token")

        self.event = {
            "tenant_id": "t1",
            "site_id": "s1",
            "box_id": "b1",
            "source_id": "cam-1",
            "event_type": "line_crossing",
            "object_id": "p1",
            "payload": {"confidence": 0.88},
        }

    def test_dispatch_success_drains_queue(self) -> None:
        self.runtime.ingest_event(self.event, now=self.now)

        sent = []

        def sender(task):
            sent.append(task.task_id)
            return True

        result = self.runtime.dispatch_pushes(now=self.now, sender=sender)

        self.assertEqual(1, result["sent"])
        self.assertEqual(0, result["failed"])
        snap = self.runtime.snapshot()
        self.assertEqual(0, snap["push_queue_size"])

        metrics = self.runtime.get_metrics()
        self.assertGreaterEqual(metrics["dispatch_runs"], 1)
        self.assertGreaterEqual(metrics["dispatch_sent"], 1)

    def test_dispatch_failure_retries_then_dead_letter(self) -> None:
        self.runtime.ingest_event(self.event, now=self.now)

        def always_fail(_task):
            return False

        self.runtime.dispatch_pushes(now=self.now, sender=always_fail)
        self.runtime.dispatch_pushes(now=self.now + timedelta(seconds=2), sender=always_fail)
        self.runtime.dispatch_pushes(now=self.now + timedelta(seconds=6), sender=always_fail)

        snap = self.runtime.snapshot()
        self.assertEqual(0, snap["push_queue_size"])
        self.assertEqual(1, snap["dead_letter_size"])

    def test_background_worker_drains_queue(self) -> None:
        self.runtime.ingest_event(self.event, now=self.now)

        started = self.runtime.start_push_worker(interval_seconds=0.05, max_items=10, sender=lambda _task: True)
        self.assertTrue(started["started"])

        deadline = time.time() + 1.0
        drained = False
        while time.time() < deadline:
            if self.runtime.snapshot()["push_queue_size"] == 0:
                drained = True
                break
            time.sleep(0.05)

        stopped = self.runtime.stop_push_worker()

        self.assertTrue(drained)
        self.assertTrue(stopped["stopped"])
        self.assertFalse(self.runtime.push_worker_status()["running"])


if __name__ == "__main__":
    unittest.main()
