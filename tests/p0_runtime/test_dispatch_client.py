import threading
import time
import unittest
from datetime import datetime, timezone

from src.p0_runtime.dispatch_client import dispatch_once, get_metrics
from src.p0_runtime.http_server import create_server


class DispatchClientTests(unittest.TestCase):
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

    def test_dispatch_once_success_mode(self) -> None:
        # Arrange queue
        event_body = {
            "now": datetime.now(timezone.utc).isoformat(),
            "event": {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "source_id": "cam-client",
                "event_type": "line_crossing",
                "object_id": "p1",
                "payload": {"confidence": 0.8},
            },
        }
        from urllib.request import Request, urlopen
        import json

        req = Request(
            f"http://127.0.0.1:{self.port}/api/v1/events",
            data=json.dumps(event_body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=3):
            pass

        res = dispatch_once(f"http://127.0.0.1:{self.port}", mode="always_success")
        metrics = get_metrics(f"http://127.0.0.1:{self.port}")

        self.assertGreaterEqual(int(res.get("sent", 0)), 1)
        self.assertGreaterEqual(int(metrics.get("dispatch_sent", 0)), 1)


if __name__ == "__main__":
    unittest.main()
