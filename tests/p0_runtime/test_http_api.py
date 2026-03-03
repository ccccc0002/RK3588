import json
import threading
import time
import unittest
from datetime import datetime, timezone
from urllib.request import Request, urlopen

from src.p0_runtime.http_server import create_server


class P0HttpApiTests(unittest.TestCase):
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

    def _post(self, path: str, data: dict):
        body = json.dumps(data).encode("utf-8")
        req = Request(
            url=f"http://127.0.0.1:{self.port}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=3) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_issue_token_endpoint(self) -> None:
        status, payload = self._post("/api/v1/auth/token", {"user_id": "u1", "role": "admin"})
        self.assertEqual(200, status)
        self.assertIn("token", payload)

    def test_join_endpoint(self) -> None:
        status, payload = self._post("/api/v1/viewer-sessions/cam-1/join", {"now": datetime.now(timezone.utc).isoformat()})
        self.assertEqual(200, status)
        self.assertIn("state", payload)

    def test_event_endpoint(self) -> None:
        status, payload = self._post(
            "/api/v1/events",
            {
                "now": datetime.now(timezone.utc).isoformat(),
                "event": {
                    "tenant_id": "t1",
                    "site_id": "s1",
                    "box_id": "b1",
                    "source_id": "cam-1",
                    "event_type": "line_crossing",
                    "object_id": "p1",
                    "payload": {"confidence": 0.88},
                },
            },
        )
        self.assertEqual(202, status)
        self.assertIn("event_id", payload)


if __name__ == "__main__":
    unittest.main()
