import json
import threading
import time
import unittest
from datetime import datetime, timezone
from urllib.request import Request, urlopen

from src.p0_runtime.dispatch_client import dispatch_once, get_metrics, issue_token
from src.p0_runtime.http_server import create_server


class DispatchClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = create_server(host="127.0.0.1", port=0)
        cls.port = cls.server.server_address[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.1)
        cls.operator_token = issue_token(cls.base_url, user_id="dispatch-client", role="operator")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def test_dispatch_once_success_mode(self) -> None:
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

        req = Request(
            f"{self.base_url}/api/v1/events",
            data=json.dumps(event_body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.operator_token}",
            },
            method="POST",
        )
        with urlopen(req, timeout=3):
            pass

        res = dispatch_once(self.base_url, mode="always_success", auth_token=self.operator_token)
        metrics = get_metrics(self.base_url, auth_token=self.operator_token)

        self.assertGreaterEqual(int(res.get("sent", 0)), 1)
        self.assertGreaterEqual(int(metrics.get("dispatch_sent", 0)), 1)


if __name__ == "__main__":
    unittest.main()
