import json
import threading
import time
import unittest
from datetime import datetime, timezone
from urllib.error import HTTPError
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
        cls.viewer_token = cls._issue_token("viewer")
        cls.operator_token = cls._issue_token("operator")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    @classmethod
    def _issue_token(cls, role: str) -> str:
        body = json.dumps({"user_id": "test-user", "role": role}).encode("utf-8")
        req = Request(
            url=f"http://127.0.0.1:{cls.port}/api/v1/auth/token",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=3) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return str(payload["data"]["token"])

    def _post(self, path: str, data: dict, token: str = "", extra_headers=None):
        body = json.dumps(data).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if extra_headers:
            headers.update(extra_headers)
        req = Request(
            url=f"http://127.0.0.1:{self.port}{path}",
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(req, timeout=3) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def _get(self, path: str, token: str = ""):
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = Request(url=f"http://127.0.0.1:{self.port}{path}", headers=headers, method="GET")
        try:
            with urlopen(req, timeout=3) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_issue_token_endpoint(self) -> None:
        status, payload = self._post("/api/v1/auth/token", {"user_id": "u1", "role": "operator"})
        self.assertEqual(200, status)
        self.assertTrue(payload["success"])
        self.assertIn("token", payload["data"])

    def test_issue_admin_token_requires_bootstrap(self) -> None:
        status, payload = self._post("/api/v1/auth/token", {"user_id": "u1", "role": "admin"})
        self.assertEqual(403, status)
        self.assertFalse(payload["success"])
        self.assertEqual("forbidden", payload["error"]["code"])

    def test_join_endpoint(self) -> None:
        status, payload = self._post(
            "/api/v1/viewer-sessions/cam-1/join",
            {"now": datetime.now(timezone.utc).isoformat()},
            token=self.viewer_token,
        )
        self.assertEqual(200, status)
        self.assertTrue(payload["success"])
        self.assertIn("state", payload["data"])

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
            token=self.operator_token,
        )
        self.assertEqual(202, status)
        self.assertTrue(payload["success"])
        self.assertIn("event_id", payload["data"])

    def test_register_and_list_devices_endpoints(self) -> None:
        reg_status, reg_payload = self._post(
            "/api/v1/devices/register",
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-2",
                "protocol": "rtsp",
                "stream_url": "rtsp://10.0.0.4/live",
                "enabled": True,
            },
            token=self.operator_token,
        )
        self.assertEqual(200, reg_status)
        self.assertTrue(reg_payload["success"])
        self.assertEqual("cam-2", reg_payload["data"]["device_id"])

        list_status, list_payload = self._get("/api/v1/devices", token=self.viewer_token)
        self.assertEqual(200, list_status)
        self.assertTrue(list_payload["success"])
        self.assertTrue(any(item["device_id"] == "cam-2" for item in list_payload["data"]["items"]))

    def test_register_gb28181_device_endpoint(self) -> None:
        reg_status, reg_payload = self._post(
            "/api/v1/devices/register",
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-gb-http",
                "protocol": "gb28181",
                "sip_server": "10.0.0.8",
                "sip_port": 5060,
                "channel_id": "34020000001320000001",
                "transport": "udp",
                "enabled": True,
            },
            token=self.operator_token,
        )
        self.assertEqual(200, reg_status)
        self.assertTrue(reg_payload["success"])
        self.assertEqual("gb28181", reg_payload["data"]["protocol"])
        self.assertEqual("", reg_payload["data"]["stream_url"])
        self.assertEqual("10.0.0.8", reg_payload["data"]["ingest_spec"]["sip_server"])

    def test_register_rtsp_without_stream_url_rejected(self) -> None:
        status, payload = self._post(
            "/api/v1/devices/register",
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-missing-url",
                "protocol": "rtsp",
                "enabled": True,
            },
            token=self.operator_token,
        )
        self.assertEqual(400, status)
        self.assertFalse(payload["success"])
        self.assertEqual("bad_request", payload["error"]["code"])

    def test_push_worker_and_metrics_endpoints(self) -> None:
        self._post(
            "/api/v1/events",
            {
                "now": datetime.now(timezone.utc).isoformat(),
                "event": {
                    "tenant_id": "t1",
                    "site_id": "s1",
                    "box_id": "b1",
                    "source_id": "cam-worker",
                    "event_type": "line_crossing",
                    "object_id": "p1",
                    "payload": {"confidence": 0.93},
                },
            },
            token=self.operator_token,
        )

        start_status, start_payload = self._post(
            "/api/v1/push/worker/start",
            {"interval_ms": 30, "limit": 10, "mode": "always_success"},
            token=self.operator_token,
        )
        self.assertEqual(200, start_status)
        self.assertTrue(start_payload["success"])
        self.assertIn("started", start_payload["data"])

        deadline = time.time() + 1.0
        processed = False
        while time.time() < deadline:
            _, metrics = self._get("/api/v1/metrics", token=self.viewer_token)
            if metrics["data"]["dispatch_sent"] >= 1:
                processed = True
                break
            time.sleep(0.05)

        stop_status, stop_payload = self._post("/api/v1/push/worker/stop", {}, token=self.operator_token)
        status_code, worker_status = self._get("/api/v1/push/worker/status", token=self.viewer_token)

        self.assertEqual(200, stop_status)
        self.assertTrue(stop_payload["success"])
        self.assertTrue(processed)
        self.assertEqual(200, status_code)
        self.assertTrue(worker_status["success"])
        self.assertFalse(worker_status["data"]["running"])

    def test_auth_guard_requires_bearer_token(self) -> None:
        status, payload = self._get("/api/v1/metrics")
        self.assertEqual(401, status)
        self.assertFalse(payload["success"])
        self.assertEqual("unauthorized", payload["error"]["code"])

    def test_auth_guard_rejects_invalid_token(self) -> None:
        status, payload = self._get("/api/v1/devices", token="invalid-token")
        self.assertEqual(401, status)
        self.assertFalse(payload["success"])
        self.assertEqual("invalid_token", payload["error"]["code"])

    def test_auth_guard_rejects_forbidden_role(self) -> None:
        status, payload = self._post(
            "/api/v1/devices/register",
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-forbidden",
                "protocol": "rtsp",
                "stream_url": "rtsp://10.0.0.9/live",
                "enabled": True,
            },
            token=self.viewer_token,
        )
        self.assertEqual(403, status)
        self.assertFalse(payload["success"])
        self.assertEqual("forbidden", payload["error"]["code"])


if __name__ == "__main__":
    unittest.main()
