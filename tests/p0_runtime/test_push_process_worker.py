import json
import threading
import time
import unittest
from datetime import datetime, timezone
from urllib.request import Request, urlopen

from src.p0_runtime.dispatch_client import issue_token
from src.p0_runtime.http_server import create_server
from src.p0_runtime.push_process_worker import PushProcessWorker


class PushProcessWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = create_server(host="127.0.0.1", port=0)
        cls.port = cls.server.server_address[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.1)
        cls.operator_token = issue_token(cls.base_url, user_id="push-worker-test", role="operator")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def test_worker_loop_processes_queue(self) -> None:
        req = Request(
            f"{self.base_url}/api/v1/events",
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
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.operator_token}",
            },
            method="POST",
        )
        with urlopen(req, timeout=3):
            pass

        worker = PushProcessWorker(
            base_url=self.base_url,
            interval_seconds=0.05,
            limit=10,
            mode="always_success",
            max_iterations=1,
            auth_token=self.operator_token,
        )
        result = worker.run_forever()

        self.assertEqual(1, result["iterations"])
        self.assertGreaterEqual(result["sent"], 1)


if __name__ == "__main__":
    unittest.main()
