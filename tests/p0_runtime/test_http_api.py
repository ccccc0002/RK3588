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

    def test_algorithm_upsert_and_list_endpoints(self) -> None:
        upsert_status, upsert_payload = self._post(
            "/api/v1/algorithms/upsert",
            {
                "algorithm_id": "face-detector-http",
                "version": "1.0.0",
                "status": "active",
                "capabilities": ["face"],
            },
            token=self.operator_token,
        )
        self.assertEqual(200, upsert_status)
        self.assertTrue(upsert_payload["success"])
        self.assertEqual("face-detector-http", upsert_payload["data"]["algorithm_id"])

        list_status, list_payload = self._get("/api/v1/algorithms", token=self.viewer_token)
        self.assertEqual(200, list_status)
        self.assertTrue(list_payload["success"])
        ids = {(item["algorithm_id"], item["version"]) for item in list_payload["data"]["items"]}
        self.assertIn(("face-detector-http", "1.0.0"), ids)

    def test_base_library_and_mapping_endpoints(self) -> None:
        self._post(
            "/api/v1/devices/register",
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-lib-http",
                "protocol": "rtsp",
                "stream_url": "rtsp://10.0.0.130/live",
                "enabled": True,
            },
            token=self.operator_token,
        )

        lib_status, lib_payload = self._post(
            "/api/v1/base-libraries/upsert",
            {
                "library_id": "lib-face-http",
                "version": "2026.03",
                "capability": "face",
                "status": "active",
            },
            token=self.operator_token,
        )
        self.assertEqual(200, lib_status)
        self.assertTrue(lib_payload["success"])

        map_status, map_payload = self._post(
            "/api/v1/base-libraries/mappings/upsert",
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-lib-http",
                "capability": "face",
                "library_id": "lib-face-http",
                "library_version": "2026.03",
            },
            token=self.operator_token,
        )
        self.assertEqual(200, map_status)
        self.assertTrue(map_payload["success"])

        libs_status, libs_payload = self._get("/api/v1/base-libraries", token=self.viewer_token)
        self.assertEqual(200, libs_status)
        self.assertTrue(libs_payload["success"])
        self.assertEqual(1, len(libs_payload["data"]["items"]))

        maps_status, maps_payload = self._get("/api/v1/base-libraries/mappings", token=self.viewer_token)
        self.assertEqual(200, maps_status)
        self.assertTrue(maps_payload["success"])
        self.assertEqual(1, len(maps_payload["data"]["items"]))

    def test_base_library_compatibility_policy_endpoints(self) -> None:
        update_status, update_payload = self._post(
            "/api/v1/base-libraries/compatibility/policy",
            {
                "enforce_capability_match": True,
                "required_status": "active",
                "version_regex_by_capability": {"face": "^2026\\."},
                "semver_range_by_capability": {"face": {"min": "1.0.0", "max": "2.0.0"}},
            },
            token=self.operator_token,
        )
        self.assertEqual(200, update_status)
        self.assertTrue(update_payload["success"])
        self.assertEqual("active", update_payload["data"]["required_status"])
        self.assertIn("face", update_payload["data"]["semver_range_by_capability"])

        get_status, get_payload = self._get("/api/v1/base-libraries/compatibility/policy", token=self.viewer_token)
        self.assertEqual(200, get_status)
        self.assertTrue(get_payload["success"])
        self.assertIn("face", get_payload["data"]["version_regex_by_capability"])
        self.assertIn("face", get_payload["data"]["semver_range_by_capability"])

    def test_offline_executor_endpoints(self) -> None:
        upsert_status, upsert_payload = self._post(
            "/api/v1/offline-executors/upsert",
            {
                "executor_id": "exec-http-1",
                "endpoint": "http://executor.local:9101",
                "status": "active",
                "capabilities": ["face"],
            },
            token=self.operator_token,
        )
        self.assertEqual(200, upsert_status)
        self.assertTrue(upsert_payload["success"])
        self.assertEqual("exec-http-1", upsert_payload["data"]["executor_id"])

        list_status, list_payload = self._get("/api/v1/offline-executors", token=self.viewer_token)
        self.assertEqual(200, list_status)
        self.assertTrue(list_payload["success"])
        self.assertTrue(any(item["executor_id"] == "exec-http-1" for item in list_payload["data"]["items"]))

    def test_offline_executor_heartbeat_endpoint(self) -> None:
        self._post(
            "/api/v1/offline-executors/upsert",
            {
                "executor_id": "exec-http-heartbeat",
                "endpoint": "http://executor.local:9103",
                "status": "active",
                "capabilities": ["face"],
            },
            token=self.operator_token,
        )
        hb_status, hb_payload = self._post(
            "/api/v1/offline-executors/heartbeat",
            {
                "executor_id": "exec-http-heartbeat",
                "now": datetime.now(timezone.utc).isoformat(),
            },
            token=self.operator_token,
        )
        self.assertEqual(200, hb_status)
        self.assertTrue(hb_payload["success"])
        self.assertEqual("healthy", hb_payload["data"]["health_state"])
        self.assertTrue(bool(hb_payload["data"]["last_heartbeat_at"]))

    def test_edge_agent_and_offline_sync_endpoints(self) -> None:
        reg_status, reg_payload = self._post(
            "/api/v1/edge-agents/register",
            {
                "agent_id": "edge-http-1",
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "endpoint": "http://edge-agent.local:9501",
                "status": "active",
                "capabilities": ["sync", "rollout"],
            },
            token=self.operator_token,
        )
        self.assertEqual(200, reg_status)
        self.assertTrue(reg_payload["success"])
        self.assertEqual("edge-http-1", reg_payload["data"]["agent_id"])

        hb_status, hb_payload = self._post(
            "/api/v1/edge-agents/heartbeat",
            {
                "agent_id": "edge-http-1",
                "now": datetime.now(timezone.utc).isoformat(),
            },
            token=self.operator_token,
        )
        self.assertEqual(200, hb_status)
        self.assertTrue(hb_payload["success"])
        self.assertEqual("healthy", hb_payload["data"]["health_state"])

        list_status, list_payload = self._get("/api/v1/edge-agents", token=self.viewer_token)
        self.assertEqual(200, list_status)
        self.assertTrue(list_payload["success"])
        self.assertTrue(any(item["agent_id"] == "edge-http-1" for item in list_payload["data"]["items"]))

        cur_status, cur_payload = self._post(
            "/api/v1/offline-sync/cursors/upsert",
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "cursor": "evt-300",
            },
            token=self.operator_token,
        )
        self.assertEqual(200, cur_status)
        self.assertTrue(cur_payload["success"])
        self.assertEqual(1, cur_payload["data"]["version"])

        conflict_status, conflict_payload = self._post(
            "/api/v1/offline-sync/cursors/upsert",
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "cursor": "evt-301",
                "expected_version": 0,
            },
            token=self.operator_token,
        )
        self.assertEqual(400, conflict_status)
        self.assertFalse(conflict_payload["success"])
        self.assertEqual("bad_request", conflict_payload["error"]["code"])

        get_status, get_payload = self._get("/api/v1/offline-sync/cursors", token=self.viewer_token)
        self.assertEqual(200, get_status)
        self.assertTrue(get_payload["success"])
        self.assertTrue(any(item["cursor"] == "evt-300" for item in get_payload["data"]["items"]))

        s_cur_status, s_cur_payload = self._post(
            "/api/v1/offline-sync/streams/upsert",
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "stream_id": "cam-1",
                "cursor": "evt-s300",
            },
            token=self.operator_token,
        )
        self.assertEqual(200, s_cur_status)
        self.assertTrue(s_cur_payload["success"])
        self.assertEqual(1, s_cur_payload["data"]["version"])

        s_conflict_status, s_conflict_payload = self._post(
            "/api/v1/offline-sync/streams/upsert",
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "stream_id": "cam-1",
                "cursor": "evt-s301",
                "expected_version": 0,
            },
            token=self.operator_token,
        )
        self.assertEqual(400, s_conflict_status)
        self.assertFalse(s_conflict_payload["success"])
        self.assertEqual("bad_request", s_conflict_payload["error"]["code"])

        s_get_status, s_get_payload = self._get("/api/v1/offline-sync/streams", token=self.viewer_token)
        self.assertEqual(200, s_get_status)
        self.assertTrue(s_get_payload["success"])
        self.assertTrue(any(item["stream_id"] == "cam-1" for item in s_get_payload["data"]["items"]))

    def test_edge_agent_offline_job_lease_endpoint(self) -> None:
        self._post(
            "/api/v1/edge-agents/register",
            {
                "agent_id": "edge-http-lease",
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "endpoint": "http://edge-agent.local:9510",
                "status": "active",
                "capabilities": ["sync"],
            },
            token=self.operator_token,
        )
        self._post(
            "/api/v1/edge-agents/heartbeat",
            {
                "agent_id": "edge-http-lease",
                "now": datetime.now(timezone.utc).isoformat(),
            },
            token=self.operator_token,
        )
        self._post(
            "/api/v1/algorithms/upsert",
            {
                "algorithm_id": "offline-http-lease",
                "version": "1.0.0",
                "status": "active",
                "capabilities": ["face"],
            },
            token=self.operator_token,
        )
        self._post(
            "/api/v1/offline-jobs/create",
            {
                "job_id": "job-http-lease-1",
                "source_scope": {"tenant_id": "t1", "site_id": "s1", "box_id": "b1"},
                "algorithm_id": "offline-http-lease",
                "algorithm_version": "1.0.0",
            },
            token=self.operator_token,
        )

        lease_status, lease_payload = self._post(
            "/api/v1/edge-agents/offline-jobs/lease",
            {
                "agent_id": "edge-http-lease",
                "lease_seconds": 120,
                "now": datetime.now(timezone.utc).isoformat(),
            },
            token=self.operator_token,
        )
        self.assertEqual(200, lease_status)
        self.assertTrue(lease_payload["success"])
        self.assertTrue(lease_payload["data"]["leased"])
        self.assertEqual("edge-http-lease", lease_payload["data"]["agent_id"])
        self.assertEqual("job-http-lease-1", lease_payload["data"]["job"]["job_id"])
        self.assertEqual("edge-http-lease", lease_payload["data"]["job"]["lease_agent_id"])
        self.assertTrue(bool(lease_payload["data"]["job"]["lease_token"]))

    def test_edge_agent_offline_job_lease_renew_and_release_endpoints(self) -> None:
        self._post(
            "/api/v1/edge-agents/register",
            {
                "agent_id": "edge-http-lease-flow",
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "endpoint": "http://edge-agent.local:9511",
                "status": "active",
                "capabilities": ["sync"],
            },
            token=self.operator_token,
        )
        self._post(
            "/api/v1/edge-agents/heartbeat",
            {
                "agent_id": "edge-http-lease-flow",
                "now": datetime.now(timezone.utc).isoformat(),
            },
            token=self.operator_token,
        )
        self._post(
            "/api/v1/algorithms/upsert",
            {
                "algorithm_id": "offline-http-lease-flow",
                "version": "1.0.0",
                "status": "active",
                "capabilities": ["face"],
            },
            token=self.operator_token,
        )
        self._post(
            "/api/v1/offline-jobs/create",
            {
                "job_id": "job-http-lease-flow-1",
                "source_scope": {"tenant_id": "t1", "site_id": "s1", "box_id": "b1"},
                "algorithm_id": "offline-http-lease-flow",
                "algorithm_version": "1.0.0",
            },
            token=self.operator_token,
        )
        lease_status, lease_payload = self._post(
            "/api/v1/edge-agents/offline-jobs/lease",
            {
                "agent_id": "edge-http-lease-flow",
                "lease_seconds": 120,
                "now": datetime.now(timezone.utc).isoformat(),
            },
            token=self.operator_token,
        )
        self.assertEqual(200, lease_status)
        token = str(lease_payload["data"]["job"]["lease_token"])

        renew_status, renew_payload = self._post(
            "/api/v1/edge-agents/offline-jobs/lease/renew",
            {
                "agent_id": "edge-http-lease-flow",
                "job_id": "job-http-lease-flow-1",
                "lease_token": token,
                "lease_seconds": 180,
                "now": datetime.now(timezone.utc).isoformat(),
            },
            token=self.operator_token,
        )
        self.assertEqual(200, renew_status)
        self.assertTrue(renew_payload["success"])
        self.assertEqual("job-http-lease-flow-1", renew_payload["data"]["job_id"])
        self.assertEqual("edge-http-lease-flow", renew_payload["data"]["lease_agent_id"])
        self.assertEqual(token, renew_payload["data"]["lease_token"])

        start_status, start_payload = self._post(
            "/api/v1/edge-agents/offline-jobs/lease/start",
            {
                "agent_id": "edge-http-lease-flow",
                "job_id": "job-http-lease-flow-1",
                "lease_token": token,
                "now": datetime.now(timezone.utc).isoformat(),
            },
            token=self.operator_token,
        )
        self.assertEqual(200, start_status)
        self.assertTrue(start_payload["success"])
        self.assertEqual("job-http-lease-flow-1", start_payload["data"]["job_id"])
        self.assertEqual("running", start_payload["data"]["status"])

        release_status, release_payload = self._post(
            "/api/v1/edge-agents/offline-jobs/lease/release",
            {
                "agent_id": "edge-http-lease-flow",
                "job_id": "job-http-lease-flow-1",
                "lease_token": token,
                "now": datetime.now(timezone.utc).isoformat(),
            },
            token=self.operator_token,
        )
        self.assertEqual(200, release_status)
        self.assertTrue(release_payload["success"])
        self.assertEqual("job-http-lease-flow-1", release_payload["data"]["job_id"])
        self.assertEqual("", release_payload["data"]["lease_agent_id"])
        self.assertEqual("", release_payload["data"]["lease_token"])

    def test_edge_agent_offline_job_lease_complete_endpoint(self) -> None:
        self._post(
            "/api/v1/edge-agents/register",
            {
                "agent_id": "edge-http-lease-complete",
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "endpoint": "http://edge-agent.local:9512",
                "status": "active",
                "capabilities": ["sync"],
            },
            token=self.operator_token,
        )
        self._post(
            "/api/v1/edge-agents/heartbeat",
            {
                "agent_id": "edge-http-lease-complete",
                "now": datetime.now(timezone.utc).isoformat(),
            },
            token=self.operator_token,
        )
        self._post(
            "/api/v1/algorithms/upsert",
            {
                "algorithm_id": "offline-http-lease-complete",
                "version": "1.0.0",
                "status": "active",
                "capabilities": ["face"],
            },
            token=self.operator_token,
        )
        self._post(
            "/api/v1/offline-jobs/create",
            {
                "job_id": "job-http-lease-complete-1",
                "source_scope": {"tenant_id": "t1", "site_id": "s1", "box_id": "b1"},
                "algorithm_id": "offline-http-lease-complete",
                "algorithm_version": "1.0.0",
            },
            token=self.operator_token,
        )
        lease_status, lease_payload = self._post(
            "/api/v1/edge-agents/offline-jobs/lease",
            {
                "agent_id": "edge-http-lease-complete",
                "lease_seconds": 120,
                "now": datetime.now(timezone.utc).isoformat(),
            },
            token=self.operator_token,
        )
        self.assertEqual(200, lease_status)
        token = str(lease_payload["data"]["job"]["lease_token"])
        self._post(
            "/api/v1/edge-agents/offline-jobs/lease/start",
            {
                "agent_id": "edge-http-lease-complete",
                "job_id": "job-http-lease-complete-1",
                "lease_token": token,
                "now": datetime.now(timezone.utc).isoformat(),
            },
            token=self.operator_token,
        )

        complete_status, complete_payload = self._post(
            "/api/v1/edge-agents/offline-jobs/lease/complete",
            {
                "agent_id": "edge-http-lease-complete",
                "job_id": "job-http-lease-complete-1",
                "lease_token": token,
                "status": "succeeded",
                "result_ref": "s3://result/job-http-lease-complete-1.json",
                "now": datetime.now(timezone.utc).isoformat(),
            },
            token=self.operator_token,
        )
        self.assertEqual(200, complete_status)
        self.assertTrue(complete_payload["success"])
        self.assertEqual("job-http-lease-complete-1", complete_payload["data"]["job_id"])
        self.assertEqual("succeeded", complete_payload["data"]["status"])
        self.assertEqual("", complete_payload["data"]["lease_agent_id"])
        self.assertEqual("", complete_payload["data"]["lease_token"])

    def test_gray_rollout_policy_endpoints(self) -> None:
        update_status, update_payload = self._post(
            "/api/v1/gray-rollout/policy",
            {
                "enabled": True,
                "default_percent": 100,
                "dependencies": ["gray_ready"],
                "dependency_graph": {
                    "gray_ready": ["edge_sync_ready"],
                    "edge_sync_ready": ["base_library_ready"],
                },
                "overrides": [
                    {"tenant_id": "t1", "site_id": "s1", "box_id": "b1", "percent": 100},
                ],
            },
            token=self.operator_token,
        )
        self.assertEqual(200, update_status)
        self.assertTrue(update_payload["success"])
        self.assertTrue(update_payload["data"]["enabled"])

        get_status, get_payload = self._get("/api/v1/gray-rollout/policy", token=self.viewer_token)
        self.assertEqual(200, get_status)
        self.assertTrue(get_payload["success"])
        self.assertEqual(100, get_payload["data"]["default_percent"])
        self.assertEqual(["gray_ready"], get_payload["data"]["dependencies"])
        self.assertEqual(
            ["base_library_ready"],
            get_payload["data"]["dependency_graph"]["edge_sync_ready"],
        )
        self.assertEqual(
            ["edge_sync_ready"],
            get_payload["data"]["dependency_graph"]["gray_ready"],
        )

        eval_status, eval_payload = self._post(
            "/api/v1/gray-rollout/evaluate",
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "seed": "fixed-seed-001",
                "dependency_status": {
                    "gray_ready": True,
                    "edge_sync_ready": True,
                    "base_library_ready": False,
                },
            },
            token=self.viewer_token,
        )
        self.assertEqual(200, eval_status)
        self.assertTrue(eval_payload["success"])
        self.assertFalse(eval_payload["data"]["enabled"])
        self.assertEqual(100, eval_payload["data"]["percent"])
        self.assertEqual(["base_library_ready"], eval_payload["data"]["blocked_by"])

        eval_ok_status, eval_ok_payload = self._post(
            "/api/v1/gray-rollout/evaluate",
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "seed": "fixed-seed-001",
                "dependency_status": {
                    "gray_ready": True,
                    "edge_sync_ready": True,
                    "base_library_ready": True,
                },
            },
            token=self.viewer_token,
        )
        self.assertEqual(200, eval_ok_status)
        self.assertTrue(eval_ok_payload["success"])
        self.assertTrue(eval_ok_payload["data"]["enabled"])
        self.assertEqual([], eval_ok_payload["data"]["blocked_by"])

        plan_status, plan_payload = self._post(
            "/api/v1/gray-rollout/plan",
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "seed": "fixed-seed-001",
                "dependency_status": {
                    "gray_ready": True,
                    "edge_sync_ready": True,
                },
            },
            token=self.viewer_token,
        )
        self.assertEqual(200, plan_status)
        self.assertTrue(plan_payload["success"])
        self.assertEqual(["base_library_ready", "edge_sync_ready", "gray_ready"], plan_payload["data"]["execution_order"])
        self.assertEqual(["base_library_ready"], plan_payload["data"]["blocked_by"])
        self.assertEqual(["base_library_ready"], plan_payload["data"]["missing_status"])
        self.assertFalse(plan_payload["data"]["enabled"])
        self.assertEqual("base_library_ready", plan_payload["data"]["nodes"][0]["dependency"])
        self.assertFalse(plan_payload["data"]["nodes"][0]["ready"])
        self.assertEqual(["base_library_ready"], plan_payload["data"]["nodes"][0]["blocked_by"])

        batch_plan_status, batch_plan_payload = self._post(
            "/api/v1/gray-rollout/plan/batch",
            {
                "items": [
                    {
                        "tenant_id": "t1",
                        "site_id": "s1",
                        "box_id": "b1",
                        "seed": "fixed-seed-001",
                        "dependency_status": {
                            "gray_ready": True,
                            "edge_sync_ready": True,
                        },
                    },
                    {
                        "tenant_id": "t2",
                        "site_id": "s2",
                        "box_id": "b2",
                        "seed": "fixed-seed-002",
                        "dependency_status": {
                            "gray_ready": True,
                            "edge_sync_ready": True,
                            "base_library_ready": True,
                        },
                    },
                ]
            },
            token=self.viewer_token,
        )
        self.assertEqual(200, batch_plan_status)
        self.assertTrue(batch_plan_payload["success"])
        self.assertEqual(2, len(batch_plan_payload["data"]["items"]))
        self.assertEqual(["base_library_ready"], batch_plan_payload["data"]["items"][0]["missing_status"])
        self.assertFalse(batch_plan_payload["data"]["items"][0]["enabled"])
        self.assertEqual([], batch_plan_payload["data"]["items"][1]["missing_status"])
        self.assertTrue(batch_plan_payload["data"]["items"][1]["enabled"])

        batch_plan_coe_status, batch_plan_coe_payload = self._post(
            "/api/v1/gray-rollout/plan/batch",
            {
                "continue_on_error": True,
                "items": [
                    {
                        "site_id": "s1",
                        "box_id": "b1",
                        "dependency_status": {"gray_ready": True},
                    },
                    {
                        "tenant_id": "t2",
                        "site_id": "s2",
                        "box_id": "b2",
                        "seed": "fixed-seed-002",
                        "dependency_status": {
                            "gray_ready": True,
                            "edge_sync_ready": True,
                            "base_library_ready": True,
                        },
                    },
                ],
            },
            token=self.viewer_token,
        )
        self.assertEqual(200, batch_plan_coe_status)
        self.assertTrue(batch_plan_coe_payload["success"])
        self.assertTrue(batch_plan_coe_payload["data"]["continue_on_error"])
        self.assertEqual(0, batch_plan_coe_payload["data"]["start_index"])
        self.assertIsNone(batch_plan_coe_payload["data"]["next_start_index"])
        self.assertEqual([0, 2], batch_plan_coe_payload["data"]["applied_range"])
        self.assertEqual(2, batch_plan_coe_payload["data"]["total"])
        self.assertEqual(2, batch_plan_coe_payload["data"]["processed_count"])
        self.assertEqual(1, batch_plan_coe_payload["data"]["success_count"])
        self.assertEqual(1, batch_plan_coe_payload["data"]["error_count"])
        self.assertEqual([0], batch_plan_coe_payload["data"]["failed_indices"])
        self.assertFalse(batch_plan_coe_payload["data"]["retry_hint"]["should_retry"])
        self.assertIsNone(batch_plan_coe_payload["data"]["retry_hint"]["resume_from"])
        self.assertEqual(0, batch_plan_coe_payload["data"]["retry_hint"]["remaining_items"])
        self.assertEqual([0], batch_plan_coe_payload["data"]["retry_hint"]["failed_indices"])
        self.assertFalse(batch_plan_coe_payload["data"]["stopped_early"])
        self.assertIsNone(batch_plan_coe_payload["data"]["max_errors"])
        self.assertGreaterEqual(batch_plan_coe_payload["data"]["duration_ms"], 0)
        self.assertEqual(1, len(batch_plan_coe_payload["data"]["items"]))
        self.assertEqual(1, len(batch_plan_coe_payload["data"]["errors"]))
        self.assertEqual(0, batch_plan_coe_payload["data"]["errors"][0]["index"])
        self.assertIn("missing required field: tenant_id", batch_plan_coe_payload["data"]["errors"][0]["error"])

        batch_plan_stop_status, batch_plan_stop_payload = self._post(
            "/api/v1/gray-rollout/plan/batch",
            {
                "continue_on_error": True,
                "max_errors": 1,
                "items": [
                    {
                        "site_id": "s1",
                        "box_id": "b1",
                        "dependency_status": {"gray_ready": True},
                    },
                    {
                        "tenant_id": "t2",
                        "site_id": "s2",
                        "box_id": "b2",
                        "seed": "fixed-seed-002",
                        "dependency_status": {
                            "gray_ready": True,
                            "edge_sync_ready": True,
                            "base_library_ready": True,
                        },
                    },
                ],
            },
            token=self.viewer_token,
        )
        self.assertEqual(200, batch_plan_stop_status)
        self.assertTrue(batch_plan_stop_payload["success"])
        self.assertTrue(batch_plan_stop_payload["data"]["continue_on_error"])
        self.assertEqual(0, batch_plan_stop_payload["data"]["start_index"])
        self.assertEqual(1, batch_plan_stop_payload["data"]["next_start_index"])
        self.assertEqual([0, 1], batch_plan_stop_payload["data"]["applied_range"])
        self.assertEqual(1, batch_plan_stop_payload["data"]["max_errors"])
        self.assertEqual(2, batch_plan_stop_payload["data"]["total"])
        self.assertEqual(1, batch_plan_stop_payload["data"]["processed_count"])
        self.assertEqual(0, batch_plan_stop_payload["data"]["success_count"])
        self.assertEqual(1, batch_plan_stop_payload["data"]["error_count"])
        self.assertEqual([0], batch_plan_stop_payload["data"]["failed_indices"])
        self.assertTrue(batch_plan_stop_payload["data"]["retry_hint"]["should_retry"])
        self.assertEqual(1, batch_plan_stop_payload["data"]["retry_hint"]["resume_from"])
        self.assertEqual(1, batch_plan_stop_payload["data"]["retry_hint"]["remaining_items"])
        self.assertEqual([0], batch_plan_stop_payload["data"]["retry_hint"]["failed_indices"])
        self.assertTrue(batch_plan_stop_payload["data"]["stopped_early"])
        self.assertGreaterEqual(batch_plan_stop_payload["data"]["duration_ms"], 0)
        self.assertEqual(0, len(batch_plan_stop_payload["data"]["items"]))
        self.assertEqual(1, len(batch_plan_stop_payload["data"]["errors"]))
        self.assertEqual(0, batch_plan_stop_payload["data"]["errors"][0]["index"])

        batch_plan_offset_status, batch_plan_offset_payload = self._post(
            "/api/v1/gray-rollout/plan/batch",
            {
                "continue_on_error": True,
                "max_errors": 1,
                "start_index": 10,
                "items": [
                    {
                        "site_id": "s1",
                        "box_id": "b1",
                        "dependency_status": {"gray_ready": True},
                    },
                    {
                        "tenant_id": "t2",
                        "site_id": "s2",
                        "box_id": "b2",
                        "seed": "fixed-seed-002",
                        "dependency_status": {
                            "gray_ready": True,
                            "edge_sync_ready": True,
                            "base_library_ready": True,
                        },
                    },
                ],
            },
            token=self.viewer_token,
        )
        self.assertEqual(200, batch_plan_offset_status)
        self.assertTrue(batch_plan_offset_payload["success"])
        self.assertEqual(10, batch_plan_offset_payload["data"]["start_index"])
        self.assertEqual(11, batch_plan_offset_payload["data"]["next_start_index"])
        self.assertEqual([10, 11], batch_plan_offset_payload["data"]["applied_range"])
        self.assertEqual([10], batch_plan_offset_payload["data"]["failed_indices"])
        self.assertTrue(batch_plan_offset_payload["data"]["retry_hint"]["should_retry"])
        self.assertEqual(11, batch_plan_offset_payload["data"]["retry_hint"]["resume_from"])
        self.assertEqual(1, batch_plan_offset_payload["data"]["retry_hint"]["remaining_items"])
        self.assertEqual([10], batch_plan_offset_payload["data"]["retry_hint"]["failed_indices"])
        self.assertEqual(10, batch_plan_offset_payload["data"]["errors"][0]["index"])

        metrics_before_status, metrics_before_payload = self._get("/api/v1/metrics", token=self.viewer_token)
        self.assertEqual(200, metrics_before_status)
        self.assertTrue(metrics_before_payload["success"])
        cache_hits_before = int(metrics_before_payload["data"].get("gray_batch_plan_cache_hits", 0))
        cache_misses_before = int(metrics_before_payload["data"].get("gray_batch_plan_cache_misses", 0))
        cache_conflicts_before = int(metrics_before_payload["data"].get("gray_batch_plan_cache_conflicts", 0))
        cache_last_minute_requests_before = int(
            metrics_before_payload["data"].get("gray_batch_plan_cache_last_minute_requests", 0)
        )
        cache_last_minute_hits_before = int(
            metrics_before_payload["data"].get("gray_batch_plan_cache_last_minute_hits", 0)
        )
        cache_last_minute_misses_before = int(
            metrics_before_payload["data"].get("gray_batch_plan_cache_last_minute_misses", 0)
        )
        cache_last_minute_conflicts_before = int(
            metrics_before_payload["data"].get("gray_batch_plan_cache_last_minute_conflicts", 0)
        )

        batch_plan_idem_status, batch_plan_idem_payload = self._post(
            "/api/v1/gray-rollout/plan/batch",
            {
                "idempotency_key": "http-plan-idem-001",
                "continue_on_error": True,
                "items": [
                    {
                        "tenant_id": "t1",
                        "site_id": "s1",
                        "box_id": "b1",
                        "seed": "http-plan-idem-001",
                        "dependency_status": {"gray_ready": True},
                    }
                ],
            },
            token=self.viewer_token,
        )
        self.assertEqual(200, batch_plan_idem_status)
        self.assertTrue(batch_plan_idem_payload["success"])
        self.assertEqual("http-plan-idem-001", batch_plan_idem_payload["data"]["idempotency_key"])
        self.assertFalse(batch_plan_idem_payload["data"]["cache_hit"])
        self.assertIsNotNone(batch_plan_idem_payload["data"]["cache_key"])
        self.assertIsNotNone(batch_plan_idem_payload["data"]["cache_expires_at"])

        batch_plan_idem_hit_status, batch_plan_idem_hit_payload = self._post(
            "/api/v1/gray-rollout/plan/batch",
            {
                "idempotency_key": "http-plan-idem-001",
                "continue_on_error": True,
                "items": [
                    {
                        "tenant_id": "t1",
                        "site_id": "s1",
                        "box_id": "b1",
                        "seed": "http-plan-idem-001",
                        "dependency_status": {"gray_ready": True},
                    }
                ],
            },
            token=self.viewer_token,
        )
        self.assertEqual(200, batch_plan_idem_hit_status)
        self.assertTrue(batch_plan_idem_hit_payload["success"])
        self.assertEqual("http-plan-idem-001", batch_plan_idem_hit_payload["data"]["idempotency_key"])
        self.assertTrue(batch_plan_idem_hit_payload["data"]["cache_hit"])
        self.assertEqual(
            batch_plan_idem_payload["data"]["cache_key"],
            batch_plan_idem_hit_payload["data"]["cache_key"],
        )

        batch_plan_idem_conflict_status, batch_plan_idem_conflict_payload = self._post(
            "/api/v1/gray-rollout/plan/batch",
            {
                "idempotency_key": "http-plan-idem-001",
                "continue_on_error": True,
                "items": [
                    {
                        "tenant_id": "t9",
                        "site_id": "s9",
                        "box_id": "b9",
                        "seed": "http-plan-idem-conflict-002",
                        "dependency_status": {"gray_ready": True},
                    }
                ],
            },
            token=self.viewer_token,
        )
        self.assertEqual(400, batch_plan_idem_conflict_status)
        self.assertFalse(batch_plan_idem_conflict_payload["success"])
        self.assertEqual("bad_request", batch_plan_idem_conflict_payload["error"]["code"])
        self.assertIn("idempotency_key conflict with different payload", batch_plan_idem_conflict_payload["error"]["message"])

        metrics_after_status, metrics_after_payload = self._get("/api/v1/metrics", token=self.viewer_token)
        self.assertEqual(200, metrics_after_status)
        self.assertTrue(metrics_after_payload["success"])
        self.assertGreaterEqual(
            int(metrics_after_payload["data"]["gray_batch_plan_cache_hits"]),
            cache_hits_before + 1,
        )
        self.assertGreaterEqual(
            int(metrics_after_payload["data"]["gray_batch_plan_cache_misses"]),
            cache_misses_before + 1,
        )
        self.assertGreaterEqual(
            int(metrics_after_payload["data"]["gray_batch_plan_cache_conflicts"]),
            cache_conflicts_before + 1,
        )
        self.assertGreaterEqual(int(metrics_after_payload["data"]["gray_batch_plan_cache_entries"]), 1)
        self.assertGreaterEqual(
            int(metrics_after_payload["data"]["gray_batch_plan_cache_last_minute_requests"]),
            cache_last_minute_requests_before + 3,
        )
        self.assertGreaterEqual(
            int(metrics_after_payload["data"]["gray_batch_plan_cache_last_minute_hits"]),
            cache_last_minute_hits_before + 1,
        )
        self.assertGreaterEqual(
            int(metrics_after_payload["data"]["gray_batch_plan_cache_last_minute_misses"]),
            cache_last_minute_misses_before + 1,
        )
        self.assertGreaterEqual(
            int(metrics_after_payload["data"]["gray_batch_plan_cache_last_minute_conflicts"]),
            cache_last_minute_conflicts_before + 1,
        )
        self.assertGreaterEqual(
            int(metrics_after_payload["data"]["gray_batch_plan_cache_last_minute_hit_rate_percent"]),
            0,
        )
        self.assertLessEqual(
            int(metrics_after_payload["data"]["gray_batch_plan_cache_last_minute_hit_rate_percent"]),
            100,
        )
        self.assertIn("gray_batch_plan_cache_evicted_expired", metrics_after_payload["data"])
        self.assertIn("gray_batch_plan_cache_evicted_overflow", metrics_after_payload["data"])

        batch_plan_ttl_requires_key_status, batch_plan_ttl_requires_key_payload = self._post(
            "/api/v1/gray-rollout/plan/batch",
            {
                "cache_ttl_seconds": 10,
                "continue_on_error": True,
                "items": [
                    {
                        "tenant_id": "t1",
                        "site_id": "s1",
                        "box_id": "b1",
                        "seed": "http-plan-ttl-requires-key",
                        "dependency_status": {"gray_ready": True},
                    }
                ],
            },
            token=self.viewer_token,
        )
        self.assertEqual(400, batch_plan_ttl_requires_key_status)
        self.assertFalse(batch_plan_ttl_requires_key_payload["success"])
        self.assertIn("cache_ttl_seconds requires idempotency_key", batch_plan_ttl_requires_key_payload["error"]["message"])

        batch_plan_ttl_invalid_status, batch_plan_ttl_invalid_payload = self._post(
            "/api/v1/gray-rollout/plan/batch",
            {
                "idempotency_key": "http-plan-idem-ttl-invalid",
                "cache_ttl_seconds": 0,
                "continue_on_error": True,
                "items": [
                    {
                        "tenant_id": "t1",
                        "site_id": "s1",
                        "box_id": "b1",
                        "seed": "http-plan-idem-ttl-invalid",
                        "dependency_status": {"gray_ready": True},
                    }
                ],
            },
            token=self.viewer_token,
        )
        self.assertEqual(400, batch_plan_ttl_invalid_status)
        self.assertFalse(batch_plan_ttl_invalid_payload["success"])
        self.assertIn("cache_ttl_seconds must be a positive integer", batch_plan_ttl_invalid_payload["error"]["message"])

        batch_plan_fail_status, batch_plan_fail_payload = self._post(
            "/api/v1/gray-rollout/plan/batch",
            {
                "items": [
                    {
                        "site_id": "s1",
                        "box_id": "b1",
                        "dependency_status": {"gray_ready": True},
                    },
                ]
            },
            token=self.viewer_token,
        )
        self.assertEqual(400, batch_plan_fail_status)
        self.assertFalse(batch_plan_fail_payload["success"])
        self.assertEqual("bad_request", batch_plan_fail_payload["error"]["code"])
        self.assertIn("items[0]", batch_plan_fail_payload["error"]["message"])

    def test_gray_rollout_batch_cache_clear_endpoint(self) -> None:
        self._post(
            "/api/v1/gray-rollout/policy",
            {
                "enabled": True,
                "default_percent": 100,
                "dependencies": ["gray_ready"],
                "dependency_graph": {},
                "overrides": [],
            },
            token=self.operator_token,
        )
        self._post(
            "/api/v1/gray-rollout/plan/batch",
            {
                "idempotency_key": "http-clear-idem-001",
                "continue_on_error": True,
                "items": [
                    {
                        "tenant_id": "t1",
                        "site_id": "s1",
                        "box_id": "b1",
                        "seed": "http-clear-idem-001",
                        "dependency_status": {"gray_ready": True},
                    }
                ],
            },
            token=self.viewer_token,
        )
        self._post(
            "/api/v1/gray-rollout/plan/batch",
            {
                "idempotency_key": "http-clear-idem-002",
                "continue_on_error": True,
                "items": [
                    {
                        "tenant_id": "t2",
                        "site_id": "s2",
                        "box_id": "b2",
                        "seed": "http-clear-idem-002",
                        "dependency_status": {"gray_ready": True},
                    }
                ],
            },
            token=self.viewer_token,
        )
        clear_forbidden_status, clear_forbidden_payload = self._post(
            "/api/v1/gray-rollout/plan/batch/cache/clear",
            {"reset_counters": True},
            token=self.viewer_token,
        )
        self.assertEqual(403, clear_forbidden_status)
        self.assertFalse(clear_forbidden_payload["success"])
        self.assertEqual("forbidden", clear_forbidden_payload["error"]["code"])

        guard_status, guard_payload = self._post(
            "/api/v1/gray-rollout/plan/batch/cache/clear",
            {"max_clear_entries": 1},
            token=self.operator_token,
        )
        self.assertEqual(400, guard_status)
        self.assertFalse(guard_payload["success"])
        self.assertEqual("bad_request", guard_payload["error"]["code"])
        self.assertIn("max_clear_entries", guard_payload["error"]["message"])

        dry_run_status, dry_run_payload = self._post(
            "/api/v1/gray-rollout/plan/batch/cache/clear",
            {"dry_run": True, "reset_counters": True, "max_clear_entries": 1},
            token=self.operator_token,
        )
        self.assertEqual(200, dry_run_status)
        self.assertTrue(dry_run_payload["success"])
        self.assertTrue(dry_run_payload["data"]["dry_run"])
        self.assertEqual(0, int(dry_run_payload["data"]["cleared_entries"]))
        self.assertEqual(0, int(dry_run_payload["data"]["cleared_events"]))
        self.assertGreaterEqual(int(dry_run_payload["data"]["would_clear_entries"]), 2)
        self.assertFalse(dry_run_payload["data"]["reset_counters_applied"])
        self.assertEqual(1, int(dry_run_payload["data"]["max_clear_entries"]))
        self.assertGreaterEqual(int(dry_run_payload["data"]["gray_batch_plan_cache_entries"]), 1)

        clear_status, clear_payload = self._post(
            "/api/v1/gray-rollout/plan/batch/cache/clear",
            {"reset_counters": True, "max_clear_entries": 2},
            token=self.operator_token,
        )
        self.assertEqual(200, clear_status)
        self.assertTrue(clear_payload["success"])
        self.assertFalse(clear_payload["data"]["dry_run"])
        self.assertTrue(clear_payload["data"]["reset_counters"])
        self.assertTrue(clear_payload["data"]["reset_counters_applied"])
        self.assertGreaterEqual(int(clear_payload["data"]["cleared_entries"]), 2)
        self.assertEqual(2, int(clear_payload["data"]["max_clear_entries"]))
        self.assertEqual(0, clear_payload["data"]["gray_batch_plan_cache_entries"])
        self.assertEqual(0, clear_payload["data"]["gray_batch_plan_cache_hits"])
        self.assertEqual(0, clear_payload["data"]["gray_batch_plan_cache_misses"])
        self.assertEqual(0, clear_payload["data"]["gray_batch_plan_cache_conflicts"])

        metrics_status, metrics_payload = self._get("/api/v1/metrics", token=self.viewer_token)
        self.assertEqual(200, metrics_status)
        self.assertTrue(metrics_payload["success"])
        self.assertEqual(0, int(metrics_payload["data"]["gray_batch_plan_cache_entries"]))
        self.assertEqual(0, int(metrics_payload["data"]["gray_batch_plan_cache_hits"]))
        self.assertEqual(0, int(metrics_payload["data"]["gray_batch_plan_cache_misses"]))
        self.assertEqual(0, int(metrics_payload["data"]["gray_batch_plan_cache_conflicts"]))

    def test_gray_rollout_batch_cache_list_endpoint(self) -> None:
        self._post(
            "/api/v1/gray-rollout/policy",
            {
                "enabled": True,
                "default_percent": 100,
                "dependencies": ["gray_ready"],
                "dependency_graph": {},
                "overrides": [],
            },
            token=self.operator_token,
        )
        self._post(
            "/api/v1/gray-rollout/plan/batch",
            {
                "idempotency_key": "http-cache-list-001",
                "continue_on_error": True,
                "items": [
                    {
                        "tenant_id": "t1",
                        "site_id": "s1",
                        "box_id": "b1",
                        "seed": "http-cache-list-001",
                        "dependency_status": {"gray_ready": True},
                    }
                ],
            },
            token=self.viewer_token,
        )
        self._post(
            "/api/v1/gray-rollout/plan/batch",
            {
                "idempotency_key": "http-cache-list-002",
                "continue_on_error": True,
                "items": [
                    {
                        "tenant_id": "t2",
                        "site_id": "s2",
                        "box_id": "b2",
                        "seed": "http-cache-list-002",
                        "dependency_status": {"gray_ready": True},
                    }
                ],
            },
            token=self.viewer_token,
        )

        list_status, list_payload = self._get(
            "/api/v1/gray-rollout/plan/batch/cache?limit=1&include_events=true",
            token=self.viewer_token,
        )
        self.assertEqual(200, list_status)
        self.assertTrue(list_payload["success"])
        self.assertEqual(1, int(list_payload["data"]["returned_entries"]))
        self.assertEqual(1, int(list_payload["data"]["limit"]))
        self.assertGreaterEqual(int(list_payload["data"]["total_entries"]), 2)
        self.assertIn("event_window", list_payload["data"])
        self.assertGreaterEqual(int(list_payload["data"]["event_window"]["event_count"]), 2)
        self.assertEqual(1, len(list_payload["data"]["items"]))
        self.assertIn("idempotency_key", list_payload["data"]["items"][0])
        self.assertIn("ttl_remaining_seconds", list_payload["data"]["items"][0])

        bad_status, bad_payload = self._get(
            "/api/v1/gray-rollout/plan/batch/cache?limit=bad",
            token=self.viewer_token,
        )
        self.assertEqual(400, bad_status)
        self.assertFalse(bad_payload["success"])
        self.assertEqual("bad_request", bad_payload["error"]["code"])

    def test_offline_jobs_endpoints(self) -> None:
        self._post(
            "/api/v1/offline-executors/upsert",
            {
                "executor_id": "exec-http-job",
                "endpoint": "http://executor.local:9102",
                "status": "active",
                "capabilities": ["face"],
            },
            token=self.operator_token,
        )
        self._post(
            "/api/v1/algorithms/upsert",
            {
                "algorithm_id": "offline-http",
                "version": "1.0.0",
                "status": "active",
                "capabilities": ["face"],
            },
            token=self.operator_token,
        )

        create_status, create_payload = self._post(
            "/api/v1/offline-jobs/create",
            {
                "job_id": "job-http-1",
                "source_scope": {"tenant_id": "t1", "site_id": "s1"},
                "algorithm_id": "offline-http",
                "algorithm_version": "1.0.0",
            },
            token=self.operator_token,
        )
        self.assertEqual(200, create_status)
        self.assertTrue(create_payload["success"])
        self.assertEqual("queued", create_payload["data"]["status"])

        status_status, status_payload = self._post(
            "/api/v1/offline-jobs/status",
            {
                "job_id": "job-http-1",
                "status": "running",
            },
            token=self.operator_token,
        )
        self.assertEqual(200, status_status)
        self.assertTrue(status_payload["success"])

        list_status, list_payload = self._get("/api/v1/offline-jobs", token=self.viewer_token)
        self.assertEqual(200, list_status)
        self.assertTrue(list_payload["success"])
        self.assertTrue(any(item["job_id"] == "job-http-1" for item in list_payload["data"]["items"]))

    def test_batch_governance_endpoints(self) -> None:
        self._post(
            "/api/v1/base-libraries/compatibility/policy",
            {
                "enforce_capability_match": True,
                "required_status": "active",
                "version_regex_by_capability": {},
                "semver_range_by_capability": {},
            },
            token=self.operator_token,
        )
        self._post(
            "/api/v1/devices/register",
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-lib-batch-http",
                "protocol": "rtsp",
                "stream_url": "rtsp://10.0.0.131/live",
                "enabled": True,
            },
            token=self.operator_token,
        )
        self._post(
            "/api/v1/base-libraries/upsert",
            {
                "library_id": "lib-face-batch-http",
                "version": "2026.06",
                "capability": "face",
                "status": "active",
            },
            token=self.operator_token,
        )
        map_status, map_payload = self._post(
            "/api/v1/base-libraries/mappings/batch-upsert",
            {
                "items": [
                    {
                        "tenant_id": "t1",
                        "site_id": "s1",
                        "box_id": "b1",
                        "device_id": "cam-lib-batch-http",
                        "capability": "face",
                        "library_id": "lib-face-batch-http",
                        "library_version": "2026.06",
                    }
                ]
            },
            token=self.operator_token,
        )
        self.assertEqual(200, map_status)
        self.assertTrue(map_payload["success"])
        self.assertEqual(1, len(map_payload["data"]["items"]))

        self._post(
            "/api/v1/algorithms/upsert",
            {
                "algorithm_id": "offline-http-batch",
                "version": "1.0.0",
                "status": "active",
                "capabilities": ["face"],
            },
            token=self.operator_token,
        )
        self._post(
            "/api/v1/offline-jobs/create",
            {
                "job_id": "job-http-batch-1",
                "source_scope": {"tenant_id": "t1", "site_id": "s1"},
                "algorithm_id": "offline-http-batch",
                "algorithm_version": "1.0.0",
            },
            token=self.operator_token,
        )
        status_status, status_payload = self._post(
            "/api/v1/offline-jobs/status/batch",
            {
                "items": [
                    {"job_id": "job-http-batch-1", "status": "running"},
                ]
            },
            token=self.operator_token,
        )
        self.assertEqual(200, status_status)
        self.assertTrue(status_payload["success"])
        self.assertEqual(1, len(status_payload["data"]["items"]))
        self.assertEqual("running", status_payload["data"]["items"][0]["status"])

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

    def test_update_device_capabilities_endpoint(self) -> None:
        self._post(
            "/api/v1/devices/register",
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-cap",
                "protocol": "rtsp",
                "stream_url": "rtsp://10.0.0.10/live",
                "enabled": True,
            },
            token=self.operator_token,
        )

        update_status, update_payload = self._post(
            "/api/v1/devices/capabilities",
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-cap",
                "capabilities": {"ocr": True, "face": True},
            },
            token=self.operator_token,
        )
        self.assertEqual(200, update_status)
        self.assertTrue(update_payload["success"])
        self.assertEqual({"ocr": True, "face": True}, update_payload["data"]["capabilities"])

    def test_runtime_schedule_endpoint(self) -> None:
        self._post(
            "/api/v1/devices/register",
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-schedule-face",
                "protocol": "rtsp",
                "stream_url": "rtsp://10.0.0.30/live",
                "capabilities": {"ocr": True, "face": True},
                "enabled": True,
            },
            token=self.operator_token,
        )
        self._post(
            "/api/v1/devices/register",
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-schedule-basic",
                "protocol": "rtsp",
                "stream_url": "rtsp://10.0.0.31/live",
                "capabilities": {"ocr": False, "face": False},
                "enabled": True,
            },
            token=self.operator_token,
        )

        status, payload = self._post("/api/v1/runtime/schedule", {"budget": 10.0}, token=self.viewer_token)
        self.assertEqual(200, status)
        self.assertTrue(payload["success"])
        streams = {item["device_id"]: item for item in payload["data"]["streams"]}
        self.assertIn("cam-schedule-face", streams)
        self.assertIn("cam-schedule-basic", streams)
        self.assertGreaterEqual(
            streams["cam-schedule-face"]["sample_fps"],
            streams["cam-schedule-basic"]["sample_fps"],
        )

    def test_runtime_telemetry_endpoint_influences_schedule(self) -> None:
        self._post(
            "/api/v1/devices/register",
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-telemetry-low-http",
                "protocol": "rtsp",
                "stream_url": "rtsp://10.0.0.60/live",
                "capabilities": {"ocr": False, "face": False},
                "enabled": True,
            },
            token=self.operator_token,
        )
        self._post(
            "/api/v1/devices/register",
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-telemetry-high-http",
                "protocol": "rtsp",
                "stream_url": "rtsp://10.0.0.61/live",
                "capabilities": {"ocr": False, "face": False},
                "enabled": True,
            },
            token=self.operator_token,
        )

        low_status, low_payload = self._post(
            "/api/v1/runtime/telemetry",
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-telemetry-low-http",
                "fps_in": 2.0,
            },
            token=self.operator_token,
        )
        self.assertEqual(200, low_status)
        self.assertTrue(low_payload["success"])

        high_status, high_payload = self._post(
            "/api/v1/runtime/telemetry",
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-telemetry-high-http",
                "fps_in": 16.0,
            },
            token=self.operator_token,
        )
        self.assertEqual(200, high_status)
        self.assertTrue(high_payload["success"])

        telemetry_status, telemetry_payload = self._get("/api/v1/runtime/telemetry", token=self.viewer_token)
        self.assertEqual(200, telemetry_status)
        self.assertTrue(telemetry_payload["success"])

        status, payload = self._post("/api/v1/runtime/schedule", {"budget": 100.0}, token=self.viewer_token)
        self.assertEqual(200, status)
        self.assertTrue(payload["success"])
        streams = {item["device_id"]: item for item in payload["data"]["streams"]}
        self.assertGreater(
            streams["cam-telemetry-high-http"]["sample_fps"],
            streams["cam-telemetry-low-http"]["sample_fps"],
        )

    def test_audit_recent_endpoint_requires_operator_role(self) -> None:
        self._post(
            "/api/v1/devices/register",
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-audit-http",
                "protocol": "rtsp",
                "stream_url": "rtsp://10.0.0.41/live",
                "enabled": True,
            },
            token=self.operator_token,
        )
        self._post(
            "/api/v1/devices/capabilities",
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-audit-http",
                "capabilities": {"ocr": True, "face": False},
            },
            token=self.operator_token,
        )

        viewer_status, viewer_payload = self._get("/api/v1/audit/recent?limit=5", token=self.viewer_token)
        self.assertEqual(403, viewer_status)
        self.assertFalse(viewer_payload["success"])
        self.assertEqual("forbidden", viewer_payload["error"]["code"])

        op_status, op_payload = self._get("/api/v1/audit/recent?limit=5", token=self.operator_token)
        self.assertEqual(200, op_status)
        self.assertTrue(op_payload["success"])
        actions = [item["action"] for item in op_payload["data"]["items"]]
        self.assertIn("device.register", actions)
        self.assertIn("device.capabilities.update", actions)

    def test_audit_policy_endpoints(self) -> None:
        update_status, update_payload = self._post(
            "/api/v1/audit/policy",
            {"max_records": 128},
            token=self.operator_token,
        )
        self.assertEqual(200, update_status)
        self.assertTrue(update_payload["success"])
        self.assertEqual(128, update_payload["data"]["max_records"])

        get_status, get_payload = self._get("/api/v1/audit/policy", token=self.viewer_token)
        self.assertEqual(200, get_status)
        self.assertTrue(get_payload["success"])
        self.assertEqual(128, get_payload["data"]["max_records"])

    def test_network_policy_endpoints(self) -> None:
        update_status, update_payload = self._post(
            "/api/v1/network/policy",
            {
                "enforce_allowlist": True,
                "webhook_allowlist": ["https://hooks.example.com", "http://10.0.0.5:8080"],
            },
            token=self.operator_token,
        )
        self.assertEqual(200, update_status)
        self.assertTrue(update_payload["success"])
        self.assertTrue(update_payload["data"]["enforce_allowlist"])

        get_status, get_payload = self._get("/api/v1/network/policy", token=self.viewer_token)
        self.assertEqual(200, get_status)
        self.assertTrue(get_payload["success"])
        self.assertEqual(2, len(get_payload["data"]["webhook_allowlist"]))

    def test_push_worker_and_metrics_endpoints(self) -> None:
        self._post(
            "/api/v1/network/policy",
            {
                "enforce_allowlist": False,
                "webhook_allowlist": [],
            },
            token=self.operator_token,
        )

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

    def test_runtime_snapshot_includes_gray_batch_cache_observability(self) -> None:
        self._post(
            "/api/v1/gray-rollout/policy",
            {
                "enabled": True,
                "default_percent": 100,
                "dependencies": ["gray_ready"],
                "dependency_graph": {},
                "overrides": [],
            },
            token=self.operator_token,
        )
        self._post(
            "/api/v1/gray-rollout/plan/batch",
            {
                "idempotency_key": "http-snapshot-idem-001",
                "continue_on_error": True,
                "items": [
                    {
                        "tenant_id": "t1",
                        "site_id": "s1",
                        "box_id": "b1",
                        "seed": "http-snapshot-idem-001",
                        "dependency_status": {"gray_ready": True},
                    }
                ],
            },
            token=self.viewer_token,
        )
        self._post(
            "/api/v1/gray-rollout/plan/batch",
            {
                "idempotency_key": "http-snapshot-idem-001",
                "continue_on_error": True,
                "items": [
                    {
                        "tenant_id": "t1",
                        "site_id": "s1",
                        "box_id": "b1",
                        "seed": "http-snapshot-idem-001",
                        "dependency_status": {"gray_ready": True},
                    }
                ],
            },
            token=self.viewer_token,
        )
        self._post(
            "/api/v1/gray-rollout/plan/batch",
            {
                "idempotency_key": "http-snapshot-idem-001",
                "continue_on_error": True,
                "items": [
                    {
                        "tenant_id": "t9",
                        "site_id": "s9",
                        "box_id": "b9",
                        "seed": "http-snapshot-idem-conflict-001",
                        "dependency_status": {"gray_ready": True},
                    }
                ],
            },
            token=self.viewer_token,
        )
        status, payload = self._get("/api/v1/runtime/snapshot", token=self.viewer_token)
        self.assertEqual(200, status)
        self.assertTrue(payload["success"])
        self.assertIn("gray_batch_plan_cache_entries", payload["data"])
        self.assertIn("gray_batch_plan_cache_hits", payload["data"])
        self.assertIn("gray_batch_plan_cache_misses", payload["data"])
        self.assertIn("gray_batch_plan_cache_conflicts", payload["data"])
        self.assertIn("gray_batch_plan_cache_evicted_expired", payload["data"])
        self.assertIn("gray_batch_plan_cache_evicted_overflow", payload["data"])
        self.assertIn("gray_batch_plan_cache_last_minute_requests", payload["data"])
        self.assertIn("gray_batch_plan_cache_last_minute_hits", payload["data"])
        self.assertIn("gray_batch_plan_cache_last_minute_misses", payload["data"])
        self.assertIn("gray_batch_plan_cache_last_minute_conflicts", payload["data"])
        self.assertIn("gray_batch_plan_cache_last_minute_hit_rate_percent", payload["data"])
        self.assertGreaterEqual(int(payload["data"]["gray_batch_plan_cache_entries"]), 1)
        self.assertGreaterEqual(int(payload["data"]["gray_batch_plan_cache_hits"]), 1)
        self.assertGreaterEqual(int(payload["data"]["gray_batch_plan_cache_misses"]), 1)
        self.assertGreaterEqual(int(payload["data"]["gray_batch_plan_cache_conflicts"]), 1)
        self.assertGreaterEqual(int(payload["data"]["gray_batch_plan_cache_last_minute_requests"]), 3)
        self.assertGreaterEqual(int(payload["data"]["gray_batch_plan_cache_last_minute_hits"]), 1)
        self.assertGreaterEqual(int(payload["data"]["gray_batch_plan_cache_last_minute_misses"]), 1)
        self.assertGreaterEqual(int(payload["data"]["gray_batch_plan_cache_last_minute_conflicts"]), 1)
        self.assertGreaterEqual(int(payload["data"]["gray_batch_plan_cache_last_minute_hit_rate_percent"]), 0)
        self.assertLessEqual(int(payload["data"]["gray_batch_plan_cache_last_minute_hit_rate_percent"]), 100)

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

    def test_p2_write_endpoints_reject_viewer_role(self) -> None:
        p2_write_cases = [
            ("/api/v1/base-libraries/upsert", {"library_id": "x", "version": "1", "capability": "face", "status": "active"}),
            (
                "/api/v1/base-libraries/mappings/upsert",
                {
                    "tenant_id": "t1",
                    "site_id": "s1",
                    "box_id": "b1",
                    "device_id": "cam-1",
                    "capability": "face",
                    "library_id": "lib-face-core",
                    "library_version": "2026.03",
                },
            ),
            (
                "/api/v1/offline-jobs/create",
                {
                    "job_id": "job-viewer-forbidden",
                    "source_scope": {"tenant_id": "t1", "site_id": "s1"},
                    "algorithm_id": "any",
                    "algorithm_version": "1.0.0",
                },
            ),
            (
                "/api/v1/offline-jobs/status",
                {
                    "job_id": "job-viewer-forbidden",
                    "status": "running",
                },
            ),
            (
                "/api/v1/base-libraries/mappings/batch-upsert",
                {
                    "items": [
                        {
                            "tenant_id": "t1",
                            "site_id": "s1",
                            "box_id": "b1",
                            "device_id": "cam-1",
                            "capability": "face",
                            "library_id": "lib-face-core",
                            "library_version": "2026.03",
                        }
                    ]
                },
            ),
            (
                "/api/v1/offline-jobs/status/batch",
                {
                    "items": [
                        {
                            "job_id": "job-viewer-forbidden",
                            "status": "running",
                        }
                    ]
                },
            ),
            (
                "/api/v1/offline-executors/heartbeat",
                {
                    "executor_id": "exec-http-heartbeat",
                },
            ),
            (
                "/api/v1/edge-agents/register",
                {
                    "agent_id": "edge-forbidden",
                    "tenant_id": "t1",
                    "site_id": "s1",
                    "box_id": "b1",
                    "endpoint": "http://edge-agent.local:9509",
                    "status": "active",
                    "capabilities": ["sync"],
                },
            ),
            (
                "/api/v1/edge-agents/heartbeat",
                {
                    "agent_id": "edge-forbidden",
                },
            ),
            (
                "/api/v1/edge-agents/offline-jobs/lease",
                {
                    "agent_id": "edge-forbidden",
                },
            ),
            (
                "/api/v1/edge-agents/offline-jobs/lease/renew",
                {
                    "agent_id": "edge-forbidden",
                    "job_id": "job-forbidden",
                    "lease_token": "x",
                },
            ),
            (
                "/api/v1/edge-agents/offline-jobs/lease/start",
                {
                    "agent_id": "edge-forbidden",
                    "job_id": "job-forbidden",
                    "lease_token": "x",
                },
            ),
            (
                "/api/v1/edge-agents/offline-jobs/lease/release",
                {
                    "agent_id": "edge-forbidden",
                    "job_id": "job-forbidden",
                    "lease_token": "x",
                },
            ),
            (
                "/api/v1/edge-agents/offline-jobs/lease/complete",
                {
                    "agent_id": "edge-forbidden",
                    "job_id": "job-forbidden",
                    "lease_token": "x",
                    "status": "succeeded",
                },
            ),
            (
                "/api/v1/offline-sync/cursors/upsert",
                {
                    "tenant_id": "t1",
                    "site_id": "s1",
                    "box_id": "b1",
                    "cursor": "evt-forbidden",
                },
            ),
            (
                "/api/v1/offline-sync/streams/upsert",
                {
                    "tenant_id": "t1",
                    "site_id": "s1",
                    "box_id": "b1",
                    "stream_id": "cam-forbidden",
                    "cursor": "evt-stream-forbidden",
                },
            ),
            (
                "/api/v1/gray-rollout/policy",
                {
                    "enabled": True,
                    "default_percent": 20,
                    "overrides": [],
                },
            ),
        ]

        for path, body in p2_write_cases:
            status, payload = self._post(path, body, token=self.viewer_token)
            self.assertEqual(403, status)
            self.assertFalse(payload["success"])
            self.assertEqual("forbidden", payload["error"]["code"])


if __name__ == "__main__":
    unittest.main()
