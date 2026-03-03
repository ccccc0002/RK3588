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


if __name__ == "__main__":
    unittest.main()
