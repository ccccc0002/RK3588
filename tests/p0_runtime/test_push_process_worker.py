import threading
import time
import unittest
from datetime import datetime, timezone

from src.p0_runtime.http_server import create_server
from src.p0_runtime.push_process_worker import PushProcessWorker


class PushProcessWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = create_server(host="127.0.0.1", port=0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def test_worker_loop_processes_queue(self) -> None:
        # enqueue one event first
        from urllib.request import Request, urlopen
        import json

        req = Request(
            f"http://127.0.0.1:{self.port}/api/v1/events",
            data=json.dumps(
                {
                    "now": datetime.now(timezone.utc).isoformat(),
                    "event": {
                        "tenant_id": "t1",
                        "site_id": "s1",
                        "box_id": "b1",
                        "source_id": "cam-proc",
                        "event_type": "line_crossing",
                        "object_id": "p1",
                        "payload": {"confidence": 0.91},
                    },
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=3):
            pass

        worker = PushProcessWorker(
            base_url=f"http://127.0.0.1:{self.port}",
            interval_seconds=0.05,
            limit=10,
            mode="always_success",
            max_iterations=1,
        )
        result = worker.run_forever()

        self.assertEqual(1, result["iterations"])
        self.assertGreaterEqual(result["sent"], 1)


if __name__ == "__main__":
    unittest.main()
