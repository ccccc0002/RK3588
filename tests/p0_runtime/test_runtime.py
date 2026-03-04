import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

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

    def test_update_device_capabilities(self) -> None:
        self.runtime.register_device(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-1",
                "protocol": "rtsp",
                "stream_url": "rtsp://10.0.0.2/live",
                "enabled": True,
            }
        )
        updated = self.runtime.update_device_capabilities(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-1",
                "capabilities": {"ocr": True, "face": False},
            }
        )

        self.assertEqual({"ocr": True, "face": False}, updated["capabilities"])
        listed = self.runtime.list_devices()
        self.assertEqual({"ocr": True, "face": False}, listed[0]["capabilities"])

    def test_upsert_and_list_algorithms(self) -> None:
        created = self.runtime.upsert_algorithm(
            {
                "algorithm_id": "face-detector",
                "version": "1.0.0",
                "status": "active",
                "capabilities": ["face"],
            }
        )
        self.assertEqual("face-detector", created["algorithm_id"])
        self.assertEqual("1.0.0", created["version"])
        self.assertEqual("active", created["status"])

        self.runtime.upsert_algorithm(
            {
                "algorithm_id": "ocr-engine",
                "version": "2.1.0",
                "status": "draft",
                "capabilities": ["ocr"],
            }
        )

        items = self.runtime.list_algorithms()
        pairs = {(item["algorithm_id"], item["version"]) for item in items}
        self.assertIn(("face-detector", "1.0.0"), pairs)
        self.assertIn(("ocr-engine", "2.1.0"), pairs)

    def test_upsert_base_library_and_mapping(self) -> None:
        self.runtime.register_device(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-lib",
                "protocol": "rtsp",
                "stream_url": "rtsp://10.0.0.111/live",
                "enabled": True,
            }
        )
        library = self.runtime.upsert_base_library(
            {
                "library_id": "lib-face-core",
                "version": "2026.03",
                "capability": "face",
                "status": "active",
                "metadata": {"vendor": "rk"},
            }
        )
        self.assertEqual("lib-face-core", library["library_id"])

        mapping = self.runtime.upsert_base_library_mapping(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-lib",
                "capability": "face",
                "library_id": "lib-face-core",
                "library_version": "2026.03",
            }
        )
        self.assertEqual("cam-lib", mapping["device_id"])
        self.assertEqual("lib-face-core", mapping["library_id"])

        libs = self.runtime.list_base_libraries()
        self.assertEqual(1, len(libs))
        mappings = self.runtime.list_base_library_mappings()
        self.assertEqual(1, len(mappings))

    def test_base_library_compatibility_policy_rejects_version_mismatch(self) -> None:
        self.runtime.register_device(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-lib-policy",
                "protocol": "rtsp",
                "stream_url": "rtsp://10.0.0.112/live",
                "enabled": True,
            }
        )
        self.runtime.upsert_base_library(
            {
                "library_id": "lib-ocr-policy",
                "version": "2026.03",
                "capability": "ocr",
                "status": "active",
            }
        )
        updated_policy = self.runtime.update_base_library_compatibility_policy(
            {
                "enforce_capability_match": True,
                "required_status": "active",
                "version_regex_by_capability": {"ocr": r"^2027\\."},
            }
        )
        self.assertEqual("active", updated_policy["required_status"])

        with self.assertRaises(ValueError):
            self.runtime.upsert_base_library_mapping(
                {
                    "tenant_id": "t1",
                    "site_id": "s1",
                    "box_id": "b1",
                    "device_id": "cam-lib-policy",
                    "capability": "ocr",
                    "library_id": "lib-ocr-policy",
                    "library_version": "2026.03",
                }
            )

    def test_base_library_compatibility_policy_rejects_semver_out_of_range(self) -> None:
        self.runtime.register_device(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-lib-semver",
                "protocol": "rtsp",
                "stream_url": "rtsp://10.0.0.113/live",
                "enabled": True,
            }
        )
        self.runtime.upsert_base_library(
            {
                "library_id": "lib-face-semver",
                "version": "1.2.0",
                "capability": "face",
                "status": "active",
            }
        )
        self.runtime.update_base_library_compatibility_policy(
            {
                "enforce_capability_match": True,
                "required_status": "active",
                "version_regex_by_capability": {},
                "semver_range_by_capability": {"face": {"min": "1.3.0", "max": "2.0.0"}},
            }
        )

        with self.assertRaises(ValueError):
            self.runtime.upsert_base_library_mapping(
                {
                    "tenant_id": "t1",
                    "site_id": "s1",
                    "box_id": "b1",
                    "device_id": "cam-lib-semver",
                    "capability": "face",
                    "library_id": "lib-face-semver",
                    "library_version": "1.2.0",
                }
            )

    def test_offline_executor_binding_auto_selects_active_executor(self) -> None:
        self.runtime.upsert_algorithm(
            {
                "algorithm_id": "offline-detector-exec",
                "version": "1.0.0",
                "status": "active",
                "capabilities": ["face"],
            }
        )
        self.runtime.upsert_offline_executor(
            {
                "executor_id": "exec-1",
                "endpoint": "http://executor.local:9001",
                "status": "active",
                "capabilities": ["face"],
            }
        )
        job = self.runtime.create_offline_job(
            {
                "job_id": "job-exec-001",
                "source_scope": {"tenant_id": "t1", "site_id": "s1"},
                "algorithm_id": "offline-detector-exec",
                "algorithm_version": "1.0.0",
            },
            now=self.now,
        )
        self.assertEqual("exec-1", job["executor_id"])

    def test_offline_executor_heartbeat_prefers_fresh_executor(self) -> None:
        self.runtime.upsert_algorithm(
            {
                "algorithm_id": "offline-detector-heartbeat",
                "version": "1.0.0",
                "status": "active",
                "capabilities": ["face"],
            }
        )
        self.runtime.upsert_offline_executor(
            {
                "executor_id": "exec-stale",
                "endpoint": "http://executor.local:9201",
                "status": "active",
                "capabilities": ["face"],
                "last_heartbeat_at": (self.now - timedelta(minutes=10)).isoformat(),
            }
        )
        self.runtime.upsert_offline_executor(
            {
                "executor_id": "exec-fresh",
                "endpoint": "http://executor.local:9202",
                "status": "active",
                "capabilities": ["face"],
                "last_heartbeat_at": (self.now - timedelta(seconds=15)).isoformat(),
            }
        )
        self.runtime.heartbeat_offline_executor({"executor_id": "exec-fresh"}, now=self.now)

        job = self.runtime.create_offline_job(
            {
                "job_id": "job-heartbeat-001",
                "source_scope": {"tenant_id": "t1", "site_id": "s1"},
                "algorithm_id": "offline-detector-heartbeat",
                "algorithm_version": "1.0.0",
            },
            now=self.now,
        )
        self.assertEqual("exec-fresh", job["executor_id"])

    def test_edge_agent_register_heartbeat_and_list(self) -> None:
        registered = self.runtime.register_edge_agent(
            {
                "agent_id": "edge-agent-1",
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "endpoint": "http://edge-agent.local:9301",
                "status": "active",
                "capabilities": ["sync", "rollout"],
            }
        )
        self.assertEqual("edge-agent-1", registered["agent_id"])
        self.assertEqual("unknown", registered["health_state"])

        heartbeat = self.runtime.heartbeat_edge_agent({"agent_id": "edge-agent-1"}, now=self.now)
        self.assertEqual("healthy", heartbeat["health_state"])
        self.assertTrue(bool(heartbeat["last_heartbeat_at"]))

        listed = self.runtime.list_edge_agents(now=self.now)
        self.assertEqual(1, len(listed))
        self.assertEqual("edge-agent-1", listed[0]["agent_id"])
        self.assertEqual("healthy", listed[0]["health_state"])

    def test_edge_agent_offline_job_lease_assigns_scope_matched_queued_job(self) -> None:
        self.runtime.register_edge_agent(
            {
                "agent_id": "edge-agent-lease-1",
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "endpoint": "http://edge-agent.local:9601",
                "status": "active",
                "capabilities": ["sync"],
            }
        )
        self.runtime.heartbeat_edge_agent({"agent_id": "edge-agent-lease-1"}, now=self.now)
        self.runtime.register_edge_agent(
            {
                "agent_id": "edge-agent-lease-2",
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "endpoint": "http://edge-agent.local:9602",
                "status": "active",
                "capabilities": ["sync"],
            }
        )
        self.runtime.heartbeat_edge_agent({"agent_id": "edge-agent-lease-2"}, now=self.now)
        self.runtime.upsert_algorithm(
            {
                "algorithm_id": "offline-lease",
                "version": "1.0.0",
                "status": "active",
                "capabilities": ["face"],
            }
        )
        self.runtime.create_offline_job(
            {
                "job_id": "job-lease-001",
                "source_scope": {"tenant_id": "t1", "site_id": "s1", "box_id": "b1"},
                "algorithm_id": "offline-lease",
                "algorithm_version": "1.0.0",
            },
            now=self.now,
        )
        self.runtime.create_offline_job(
            {
                "job_id": "job-lease-002",
                "source_scope": {"tenant_id": "t9", "site_id": "s9", "box_id": "b9"},
                "algorithm_id": "offline-lease",
                "algorithm_version": "1.0.0",
            },
            now=self.now,
        )

        leased = self.runtime.lease_offline_job_to_edge_agent(
            {"agent_id": "edge-agent-lease-1", "lease_seconds": 120},
            now=self.now,
        )
        self.assertTrue(leased["leased"])
        self.assertEqual("edge-agent-lease-1", leased["agent_id"])
        self.assertIsNotNone(leased["job"])
        self.assertEqual("job-lease-001", leased["job"]["job_id"])
        self.assertEqual("edge-agent-lease-1", leased["job"]["lease_agent_id"])
        self.assertTrue(bool(leased["job"]["lease_token"]))
        self.assertTrue(bool(leased["job"]["lease_expires_at"]))

        second = self.runtime.lease_offline_job_to_edge_agent(
            {"agent_id": "edge-agent-lease-2", "lease_seconds": 120},
            now=self.now,
        )
        self.assertFalse(second["leased"])
        self.assertIsNone(second["job"])

    def test_edge_agent_offline_job_lease_rejects_stale_agent(self) -> None:
        self.runtime.register_edge_agent(
            {
                "agent_id": "edge-agent-stale",
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "endpoint": "http://edge-agent.local:9603",
                "status": "active",
                "capabilities": ["sync"],
                "last_heartbeat_at": (self.now - timedelta(minutes=10)).isoformat(),
            }
        )
        self.runtime.upsert_algorithm(
            {
                "algorithm_id": "offline-lease-stale",
                "version": "1.0.0",
                "status": "active",
                "capabilities": ["face"],
            }
        )
        self.runtime.create_offline_job(
            {
                "job_id": "job-lease-stale-001",
                "source_scope": {"tenant_id": "t1", "site_id": "s1", "box_id": "b1"},
                "algorithm_id": "offline-lease-stale",
                "algorithm_version": "1.0.0",
            },
            now=self.now,
        )

        with self.assertRaises(ValueError):
            self.runtime.lease_offline_job_to_edge_agent(
                {"agent_id": "edge-agent-stale", "lease_seconds": 120},
                now=self.now,
            )

    def test_edge_agent_offline_job_lease_renew_and_release(self) -> None:
        self.runtime.register_edge_agent(
            {
                "agent_id": "edge-agent-lease-flow-1",
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "endpoint": "http://edge-agent.local:9604",
                "status": "active",
                "capabilities": ["sync"],
            }
        )
        self.runtime.heartbeat_edge_agent({"agent_id": "edge-agent-lease-flow-1"}, now=self.now)
        self.runtime.register_edge_agent(
            {
                "agent_id": "edge-agent-lease-flow-2",
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "endpoint": "http://edge-agent.local:9605",
                "status": "active",
                "capabilities": ["sync"],
            }
        )
        self.runtime.heartbeat_edge_agent({"agent_id": "edge-agent-lease-flow-2"}, now=self.now)
        self.runtime.upsert_algorithm(
            {
                "algorithm_id": "offline-lease-flow",
                "version": "1.0.0",
                "status": "active",
                "capabilities": ["face"],
            }
        )
        self.runtime.create_offline_job(
            {
                "job_id": "job-lease-flow-001",
                "source_scope": {"tenant_id": "t1", "site_id": "s1", "box_id": "b1"},
                "algorithm_id": "offline-lease-flow",
                "algorithm_version": "1.0.0",
            },
            now=self.now,
        )

        leased = self.runtime.lease_offline_job_to_edge_agent(
            {"agent_id": "edge-agent-lease-flow-1", "lease_seconds": 60},
            now=self.now,
        )
        self.assertTrue(leased["leased"])
        token = leased["job"]["lease_token"]
        expires_at_before = leased["job"]["lease_expires_at"]

        renewed = self.runtime.renew_offline_job_lease(
            {
                "agent_id": "edge-agent-lease-flow-1",
                "job_id": "job-lease-flow-001",
                "lease_token": token,
                "lease_seconds": 180,
            },
            now=self.now + timedelta(seconds=30),
        )
        self.assertEqual("job-lease-flow-001", renewed["job_id"])
        self.assertEqual("edge-agent-lease-flow-1", renewed["lease_agent_id"])
        self.assertEqual(token, renewed["lease_token"])
        self.assertGreater(renewed["lease_expires_at"], expires_at_before)

        released = self.runtime.release_offline_job_lease(
            {
                "agent_id": "edge-agent-lease-flow-1",
                "job_id": "job-lease-flow-001",
                "lease_token": token,
            },
            now=self.now + timedelta(seconds=35),
        )
        self.assertEqual("job-lease-flow-001", released["job_id"])
        self.assertEqual("", released["lease_agent_id"])
        self.assertEqual("", released["lease_token"])
        self.assertEqual("", released["lease_expires_at"])

        leased_again = self.runtime.lease_offline_job_to_edge_agent(
            {"agent_id": "edge-agent-lease-flow-2", "lease_seconds": 90},
            now=self.now + timedelta(seconds=40),
        )
        self.assertTrue(leased_again["leased"])
        self.assertEqual("edge-agent-lease-flow-2", leased_again["job"]["lease_agent_id"])

    def test_edge_agent_offline_job_lease_renew_rejects_invalid_token(self) -> None:
        self.runtime.register_edge_agent(
            {
                "agent_id": "edge-agent-lease-invalid",
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "endpoint": "http://edge-agent.local:9606",
                "status": "active",
                "capabilities": ["sync"],
            }
        )
        self.runtime.heartbeat_edge_agent({"agent_id": "edge-agent-lease-invalid"}, now=self.now)
        self.runtime.upsert_algorithm(
            {
                "algorithm_id": "offline-lease-invalid",
                "version": "1.0.0",
                "status": "active",
                "capabilities": ["face"],
            }
        )
        self.runtime.create_offline_job(
            {
                "job_id": "job-lease-invalid-001",
                "source_scope": {"tenant_id": "t1", "site_id": "s1", "box_id": "b1"},
                "algorithm_id": "offline-lease-invalid",
                "algorithm_version": "1.0.0",
            },
            now=self.now,
        )
        self.runtime.lease_offline_job_to_edge_agent(
            {"agent_id": "edge-agent-lease-invalid", "lease_seconds": 60},
            now=self.now,
        )

        with self.assertRaises(ValueError):
            self.runtime.renew_offline_job_lease(
                {
                    "agent_id": "edge-agent-lease-invalid",
                    "job_id": "job-lease-invalid-001",
                    "lease_token": "invalid-token",
                },
                now=self.now + timedelta(seconds=10),
            )

    def test_edge_agent_offline_job_lease_start_sets_running(self) -> None:
        self.runtime.register_edge_agent(
            {
                "agent_id": "edge-agent-lease-start",
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "endpoint": "http://edge-agent.local:9607",
                "status": "active",
                "capabilities": ["sync"],
            }
        )
        self.runtime.heartbeat_edge_agent({"agent_id": "edge-agent-lease-start"}, now=self.now)
        self.runtime.upsert_algorithm(
            {
                "algorithm_id": "offline-lease-start",
                "version": "1.0.0",
                "status": "active",
                "capabilities": ["face"],
            }
        )
        self.runtime.create_offline_job(
            {
                "job_id": "job-lease-start-001",
                "source_scope": {"tenant_id": "t1", "site_id": "s1", "box_id": "b1"},
                "algorithm_id": "offline-lease-start",
                "algorithm_version": "1.0.0",
            },
            now=self.now,
        )
        leased = self.runtime.lease_offline_job_to_edge_agent(
            {"agent_id": "edge-agent-lease-start", "lease_seconds": 90},
            now=self.now,
        )
        token = str(leased["job"]["lease_token"])

        started = self.runtime.start_offline_job_with_lease(
            {
                "agent_id": "edge-agent-lease-start",
                "job_id": "job-lease-start-001",
                "lease_token": token,
            },
            now=self.now + timedelta(seconds=5),
        )
        self.assertEqual("job-lease-start-001", started["job_id"])
        self.assertEqual("running", started["status"])
        self.assertEqual("edge-agent-lease-start", started["lease_agent_id"])
        self.assertEqual(token, started["lease_token"])
        self.assertTrue(bool(started["lease_updated_at"]))

    def test_edge_agent_offline_job_lease_start_rejects_invalid_token(self) -> None:
        self.runtime.register_edge_agent(
            {
                "agent_id": "edge-agent-lease-start-invalid",
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "endpoint": "http://edge-agent.local:9608",
                "status": "active",
                "capabilities": ["sync"],
            }
        )
        self.runtime.heartbeat_edge_agent({"agent_id": "edge-agent-lease-start-invalid"}, now=self.now)
        self.runtime.upsert_algorithm(
            {
                "algorithm_id": "offline-lease-start-invalid",
                "version": "1.0.0",
                "status": "active",
                "capabilities": ["face"],
            }
        )
        self.runtime.create_offline_job(
            {
                "job_id": "job-lease-start-invalid-001",
                "source_scope": {"tenant_id": "t1", "site_id": "s1", "box_id": "b1"},
                "algorithm_id": "offline-lease-start-invalid",
                "algorithm_version": "1.0.0",
            },
            now=self.now,
        )
        self.runtime.lease_offline_job_to_edge_agent(
            {"agent_id": "edge-agent-lease-start-invalid", "lease_seconds": 90},
            now=self.now,
        )

        with self.assertRaises(ValueError):
            self.runtime.start_offline_job_with_lease(
                {
                    "agent_id": "edge-agent-lease-start-invalid",
                    "job_id": "job-lease-start-invalid-001",
                    "lease_token": "invalid-token",
                },
                now=self.now + timedelta(seconds=5),
            )

    def test_edge_agent_offline_job_lease_complete_sets_terminal_and_clears_lease(self) -> None:
        self.runtime.register_edge_agent(
            {
                "agent_id": "edge-agent-lease-complete",
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "endpoint": "http://edge-agent.local:9609",
                "status": "active",
                "capabilities": ["sync"],
            }
        )
        self.runtime.heartbeat_edge_agent({"agent_id": "edge-agent-lease-complete"}, now=self.now)
        self.runtime.upsert_algorithm(
            {
                "algorithm_id": "offline-lease-complete",
                "version": "1.0.0",
                "status": "active",
                "capabilities": ["face"],
            }
        )
        self.runtime.create_offline_job(
            {
                "job_id": "job-lease-complete-001",
                "source_scope": {"tenant_id": "t1", "site_id": "s1", "box_id": "b1"},
                "algorithm_id": "offline-lease-complete",
                "algorithm_version": "1.0.0",
            },
            now=self.now,
        )
        leased = self.runtime.lease_offline_job_to_edge_agent(
            {"agent_id": "edge-agent-lease-complete", "lease_seconds": 90},
            now=self.now,
        )
        token = str(leased["job"]["lease_token"])
        self.runtime.start_offline_job_with_lease(
            {
                "agent_id": "edge-agent-lease-complete",
                "job_id": "job-lease-complete-001",
                "lease_token": token,
            },
            now=self.now + timedelta(seconds=5),
        )

        completed = self.runtime.complete_offline_job_with_lease(
            {
                "agent_id": "edge-agent-lease-complete",
                "job_id": "job-lease-complete-001",
                "lease_token": token,
                "status": "succeeded",
                "result_ref": "s3://result/job-lease-complete-001.json",
            },
            now=self.now + timedelta(seconds=10),
        )
        self.assertEqual("succeeded", completed["status"])
        self.assertEqual("s3://result/job-lease-complete-001.json", completed["result_ref"])
        self.assertEqual("", completed["lease_agent_id"])
        self.assertEqual("", completed["lease_token"])
        self.assertEqual("", completed["lease_expires_at"])

    def test_edge_agent_offline_job_lease_complete_rejects_non_terminal_status(self) -> None:
        self.runtime.register_edge_agent(
            {
                "agent_id": "edge-agent-lease-complete-invalid",
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "endpoint": "http://edge-agent.local:9610",
                "status": "active",
                "capabilities": ["sync"],
            }
        )
        self.runtime.heartbeat_edge_agent({"agent_id": "edge-agent-lease-complete-invalid"}, now=self.now)
        self.runtime.upsert_algorithm(
            {
                "algorithm_id": "offline-lease-complete-invalid",
                "version": "1.0.0",
                "status": "active",
                "capabilities": ["face"],
            }
        )
        self.runtime.create_offline_job(
            {
                "job_id": "job-lease-complete-invalid-001",
                "source_scope": {"tenant_id": "t1", "site_id": "s1", "box_id": "b1"},
                "algorithm_id": "offline-lease-complete-invalid",
                "algorithm_version": "1.0.0",
            },
            now=self.now,
        )
        leased = self.runtime.lease_offline_job_to_edge_agent(
            {"agent_id": "edge-agent-lease-complete-invalid", "lease_seconds": 90},
            now=self.now,
        )
        token = str(leased["job"]["lease_token"])

        with self.assertRaises(ValueError):
            self.runtime.complete_offline_job_with_lease(
                {
                    "agent_id": "edge-agent-lease-complete-invalid",
                    "job_id": "job-lease-complete-invalid-001",
                    "lease_token": token,
                    "status": "running",
                },
                now=self.now + timedelta(seconds=10),
            )

    def test_offline_sync_cursor_conflict_detection(self) -> None:
        created = self.runtime.upsert_offline_sync_cursor(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "cursor": "evt-100",
            },
            now=self.now,
        )
        self.assertEqual(1, created["version"])

        with self.assertRaises(ValueError):
            self.runtime.upsert_offline_sync_cursor(
                {
                    "tenant_id": "t1",
                    "site_id": "s1",
                    "box_id": "b1",
                    "cursor": "evt-101",
                    "expected_version": 0,
                },
                now=self.now,
            )

        updated = self.runtime.upsert_offline_sync_cursor(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "cursor": "evt-102",
                "expected_version": 1,
            },
            now=self.now,
        )
        self.assertEqual(2, updated["version"])

    def test_offline_sync_stream_cursor_conflict_detection(self) -> None:
        created = self.runtime.upsert_offline_sync_stream_cursor(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "stream_id": "cam-1",
                "cursor": "evt-s100",
            },
            now=self.now,
        )
        self.assertEqual(1, created["version"])

        with self.assertRaises(ValueError):
            self.runtime.upsert_offline_sync_stream_cursor(
                {
                    "tenant_id": "t1",
                    "site_id": "s1",
                    "box_id": "b1",
                    "stream_id": "cam-1",
                    "cursor": "evt-s101",
                    "expected_version": 0,
                },
                now=self.now,
            )

        updated = self.runtime.upsert_offline_sync_stream_cursor(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "stream_id": "cam-1",
                "cursor": "evt-s102",
                "expected_version": 1,
            },
            now=self.now,
        )
        self.assertEqual(2, updated["version"])

        listed = self.runtime.list_offline_sync_stream_cursors()
        self.assertEqual(1, len(listed))
        self.assertEqual("cam-1", listed[0]["stream_id"])
        self.assertEqual("evt-s102", listed[0]["cursor"])

    def test_gray_rollout_policy_evaluation_uses_scope_override(self) -> None:
        updated = self.runtime.update_gray_rollout_policy(
            {
                "enabled": True,
                "default_percent": 0,
                "overrides": [
                    {"tenant_id": "t1", "site_id": "s1", "box_id": "b1", "percent": 100},
                ],
            }
        )
        self.assertTrue(updated["enabled"])
        self.assertEqual(0, updated["default_percent"])

        decision = self.runtime.evaluate_gray_rollout(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "seed": str(uuid4()),
            }
        )
        self.assertTrue(decision["enabled"])
        self.assertEqual(100, decision["percent"])

        other = self.runtime.evaluate_gray_rollout(
            {
                "tenant_id": "t9",
                "site_id": "s9",
                "box_id": "b9",
                "seed": str(uuid4()),
            }
        )
        self.assertFalse(other["enabled"])
        self.assertEqual(0, other["percent"])

    def test_gray_rollout_evaluation_respects_dependency_status(self) -> None:
        updated = self.runtime.update_gray_rollout_policy(
            {
                "enabled": True,
                "default_percent": 100,
                "overrides": [],
                "dependencies": ["edge_sync_ready", "base_library_ready"],
            }
        )
        self.assertEqual(["base_library_ready", "edge_sync_ready"], updated["dependencies"])

        blocked = self.runtime.evaluate_gray_rollout(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "seed": "dep-seed-001",
                "dependency_status": {"edge_sync_ready": True, "base_library_ready": False},
            }
        )
        self.assertFalse(blocked["enabled"])
        self.assertEqual(["base_library_ready"], blocked["blocked_by"])

        allowed = self.runtime.evaluate_gray_rollout(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "seed": "dep-seed-001",
                "dependency_status": {"edge_sync_ready": True, "base_library_ready": True},
            }
        )
        self.assertTrue(allowed["enabled"])
        self.assertEqual([], allowed["blocked_by"])

    def test_gray_rollout_dependency_graph_blocks_transitive_dependencies(self) -> None:
        updated = self.runtime.update_gray_rollout_policy(
            {
                "enabled": True,
                "default_percent": 100,
                "overrides": [],
                "dependencies": ["gray_ready"],
                "dependency_graph": {
                    "gray_ready": ["edge_sync_ready"],
                    "edge_sync_ready": ["base_library_ready"],
                },
            }
        )
        self.assertEqual(["gray_ready"], updated["dependencies"])
        self.assertEqual(["edge_sync_ready"], updated["dependency_graph"]["gray_ready"])

        blocked = self.runtime.evaluate_gray_rollout(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "seed": "dep-graph-seed-001",
                "dependency_status": {
                    "gray_ready": True,
                    "edge_sync_ready": True,
                    "base_library_ready": False,
                },
            }
        )
        self.assertFalse(blocked["enabled"])
        self.assertEqual(["base_library_ready"], blocked["blocked_by"])

        allowed = self.runtime.evaluate_gray_rollout(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "seed": "dep-graph-seed-001",
                "dependency_status": {
                    "gray_ready": True,
                    "edge_sync_ready": True,
                    "base_library_ready": True,
                },
            }
        )
        self.assertTrue(allowed["enabled"])
        self.assertEqual([], allowed["blocked_by"])

    def test_gray_rollout_dependency_graph_rejects_cycles(self) -> None:
        with self.assertRaisesRegex(ValueError, "dependency_graph must be acyclic"):
            self.runtime.update_gray_rollout_policy(
                {
                    "enabled": True,
                    "default_percent": 100,
                    "overrides": [],
                    "dependencies": ["gray_ready"],
                    "dependency_graph": {
                        "gray_ready": ["edge_sync_ready"],
                        "edge_sync_ready": ["gray_ready"],
                    },
                }
            )

    def test_gray_rollout_dependency_plan_returns_topology_and_blockers(self) -> None:
        self.runtime.update_gray_rollout_policy(
            {
                "enabled": True,
                "default_percent": 100,
                "overrides": [],
                "dependencies": ["gray_ready"],
                "dependency_graph": {
                    "gray_ready": ["edge_sync_ready"],
                    "edge_sync_ready": ["base_library_ready"],
                },
            }
        )

        plan = self.runtime.plan_gray_rollout_dependencies(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "seed": "dep-plan-seed-001",
                "dependency_status": {
                    "gray_ready": True,
                    "edge_sync_ready": True,
                },
            }
        )
        self.assertEqual(["gray_ready"], plan["dependencies"])
        self.assertEqual(["base_library_ready", "edge_sync_ready", "gray_ready"], plan["execution_order"])
        self.assertEqual(["base_library_ready"], plan["blocked_by"])
        self.assertEqual(["base_library_ready"], plan["missing_status"])
        self.assertFalse(plan["enabled"])
        self.assertEqual("base_library_ready", plan["nodes"][0]["dependency"])
        self.assertFalse(plan["nodes"][0]["ready"])
        self.assertEqual(["base_library_ready"], plan["nodes"][0]["blocked_by"])

    def test_gray_rollout_dependency_plan_batch(self) -> None:
        self.runtime.update_gray_rollout_policy(
            {
                "enabled": True,
                "default_percent": 100,
                "overrides": [],
                "dependencies": ["gray_ready"],
                "dependency_graph": {
                    "gray_ready": ["edge_sync_ready"],
                    "edge_sync_ready": ["base_library_ready"],
                },
            }
        )

        result = self.runtime.batch_plan_gray_rollout_dependencies(
            {
                "items": [
                    {
                        "tenant_id": "t1",
                        "site_id": "s1",
                        "box_id": "b1",
                        "seed": "dep-plan-batch-001",
                        "dependency_status": {
                            "gray_ready": True,
                            "edge_sync_ready": True,
                        },
                    },
                    {
                        "tenant_id": "t2",
                        "site_id": "s2",
                        "box_id": "b2",
                        "seed": "dep-plan-batch-002",
                        "dependency_status": {
                            "gray_ready": True,
                            "edge_sync_ready": True,
                            "base_library_ready": True,
                        },
                    },
                ]
            }
        )
        self.assertEqual(2, len(result))
        self.assertEqual(["base_library_ready"], result[0]["missing_status"])
        self.assertFalse(result[0]["enabled"])
        self.assertEqual([], result[1]["missing_status"])
        self.assertTrue(result[1]["enabled"])

    def test_gray_rollout_dependency_plan_batch_continue_on_error(self) -> None:
        self.runtime.update_gray_rollout_policy(
            {
                "enabled": True,
                "default_percent": 100,
                "overrides": [],
                "dependencies": ["gray_ready"],
                "dependency_graph": {
                    "gray_ready": ["edge_sync_ready"],
                    "edge_sync_ready": ["base_library_ready"],
                },
            }
        )

        report = self.runtime.batch_plan_gray_rollout_dependencies_report(
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
                        "seed": "dep-plan-batch-coe-002",
                        "dependency_status": {
                            "gray_ready": True,
                            "edge_sync_ready": True,
                            "base_library_ready": True,
                        },
                    },
                ],
            }
        )
        self.assertTrue(report["continue_on_error"])
        self.assertEqual(2, report["total"])
        self.assertEqual(2, report["processed_count"])
        self.assertEqual(1, report["success_count"])
        self.assertEqual(1, report["error_count"])
        self.assertFalse(report["stopped_early"])
        self.assertIsNone(report["max_errors"])
        self.assertGreaterEqual(report["duration_ms"], 0)
        self.assertEqual(1, len(report["items"]))
        self.assertTrue(report["items"][0]["enabled"])
        self.assertEqual(1, len(report["errors"]))
        self.assertEqual(0, report["errors"][0]["index"])
        self.assertIn("missing required field: tenant_id", report["errors"][0]["error"])

    def test_gray_rollout_dependency_plan_batch_max_errors_stops_early(self) -> None:
        self.runtime.update_gray_rollout_policy(
            {
                "enabled": True,
                "default_percent": 100,
                "overrides": [],
                "dependencies": ["gray_ready"],
                "dependency_graph": {
                    "gray_ready": ["edge_sync_ready"],
                    "edge_sync_ready": ["base_library_ready"],
                },
            }
        )

        report = self.runtime.batch_plan_gray_rollout_dependencies_report(
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
                        "seed": "dep-plan-batch-stop-002",
                        "dependency_status": {
                            "gray_ready": True,
                            "edge_sync_ready": True,
                            "base_library_ready": True,
                        },
                    },
                ],
            }
        )
        self.assertTrue(report["continue_on_error"])
        self.assertEqual(1, report["max_errors"])
        self.assertEqual(2, report["total"])
        self.assertEqual(1, report["processed_count"])
        self.assertEqual(0, report["success_count"])
        self.assertEqual(1, report["error_count"])
        self.assertTrue(report["stopped_early"])
        self.assertGreaterEqual(report["duration_ms"], 0)
        self.assertEqual(0, len(report["items"]))
        self.assertEqual(1, len(report["errors"]))
        self.assertEqual(0, report["errors"][0]["index"])

    def test_batch_mapping_upsert_and_offline_status_update(self) -> None:
        self.runtime.register_device(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-batch-1",
                "protocol": "rtsp",
                "stream_url": "rtsp://10.0.0.121/live",
                "enabled": True,
            }
        )
        self.runtime.register_device(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-batch-2",
                "protocol": "rtsp",
                "stream_url": "rtsp://10.0.0.122/live",
                "enabled": True,
            }
        )
        self.runtime.upsert_base_library(
            {
                "library_id": "lib-face-batch",
                "version": "2026.05",
                "capability": "face",
                "status": "active",
            }
        )

        mappings = self.runtime.batch_upsert_base_library_mappings(
            {
                "items": [
                    {
                        "tenant_id": "t1",
                        "site_id": "s1",
                        "box_id": "b1",
                        "device_id": "cam-batch-1",
                        "capability": "face",
                        "library_id": "lib-face-batch",
                        "library_version": "2026.05",
                    },
                    {
                        "tenant_id": "t1",
                        "site_id": "s1",
                        "box_id": "b1",
                        "device_id": "cam-batch-2",
                        "capability": "face",
                        "library_id": "lib-face-batch",
                        "library_version": "2026.05",
                    },
                ]
            }
        )
        self.assertEqual(2, len(mappings))

        self.runtime.upsert_algorithm(
            {
                "algorithm_id": "offline-batch",
                "version": "1.0.0",
                "status": "active",
                "capabilities": ["face"],
            }
        )
        self.runtime.create_offline_job(
            {
                "job_id": "job-batch-1",
                "source_scope": {"tenant_id": "t1", "site_id": "s1"},
                "algorithm_id": "offline-batch",
                "algorithm_version": "1.0.0",
            },
            now=self.now,
        )
        self.runtime.create_offline_job(
            {
                "job_id": "job-batch-2",
                "source_scope": {"tenant_id": "t1", "site_id": "s1"},
                "algorithm_id": "offline-batch",
                "algorithm_version": "1.0.0",
            },
            now=self.now,
        )

        updates = self.runtime.batch_update_offline_job_status(
            {
                "items": [
                    {"job_id": "job-batch-1", "status": "running"},
                    {"job_id": "job-batch-2", "status": "running"},
                ]
            },
            now=self.now.replace(second=8),
        )
        self.assertEqual(2, len(updates))
        self.assertTrue(all(item["status"] == "running" for item in updates))

    def test_offline_job_lifecycle(self) -> None:
        self.runtime.upsert_algorithm(
            {
                "algorithm_id": "offline-detector",
                "version": "1.0.0",
                "status": "active",
                "capabilities": ["face"],
            }
        )
        job = self.runtime.create_offline_job(
            {
                "job_id": "job-001",
                "source_scope": {"tenant_id": "t1", "site_id": "s1"},
                "algorithm_id": "offline-detector",
                "algorithm_version": "1.0.0",
            },
            now=self.now,
        )
        self.assertEqual("queued", job["status"])

        running = self.runtime.update_offline_job_status(
            {
                "job_id": "job-001",
                "status": "running",
            },
            now=self.now.replace(second=5),
        )
        self.assertEqual("running", running["status"])

        done = self.runtime.update_offline_job_status(
            {
                "job_id": "job-001",
                "status": "succeeded",
                "result_ref": "s3://bucket/job-001.json",
            },
            now=self.now.replace(second=10),
        )
        self.assertEqual("succeeded", done["status"])

        with self.assertRaises(ValueError):
            self.runtime.update_offline_job_status(
                {
                    "job_id": "job-001",
                    "status": "running",
                },
                now=self.now.replace(second=15),
            )

    def test_capability_schedule_prioritizes_face_stream(self) -> None:
        self.runtime.register_device(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-face",
                "protocol": "rtsp",
                "stream_url": "rtsp://10.0.0.20/live",
                "capabilities": {"ocr": True, "face": True},
                "enabled": True,
            }
        )
        self.runtime.register_device(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-basic",
                "protocol": "rtsp",
                "stream_url": "rtsp://10.0.0.21/live",
                "capabilities": {"ocr": False, "face": False},
                "enabled": True,
            }
        )

        plan = self.runtime.plan_capability_schedule(budget=10.0)
        streams = {item["device_id"]: item for item in plan["streams"]}

        self.assertTrue(plan["degraded"])
        self.assertIn("cam-face", streams)
        self.assertIn("cam-basic", streams)
        self.assertGreaterEqual(streams["cam-face"]["sample_fps"], streams["cam-basic"]["sample_fps"])

    def test_capability_schedule_uses_stream_telemetry_fps(self) -> None:
        self.runtime.register_device(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-telemetry-low",
                "protocol": "rtsp",
                "stream_url": "rtsp://10.0.0.50/live",
                "enabled": True,
            }
        )
        self.runtime.register_device(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-telemetry-high",
                "protocol": "rtsp",
                "stream_url": "rtsp://10.0.0.51/live",
                "enabled": True,
            }
        )
        self.runtime.update_stream_telemetry(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-telemetry-low",
                "fps_in": 2.0,
            },
            now=self.now,
        )
        self.runtime.update_stream_telemetry(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-telemetry-high",
                "fps_in": 16.0,
            },
            now=self.now,
        )

        plan = self.runtime.plan_capability_schedule(budget=100.0)
        streams = {item["device_id"]: item for item in plan["streams"]}
        self.assertGreater(streams["cam-telemetry-high"]["sample_fps"], streams["cam-telemetry-low"]["sample_fps"])
        self.assertLessEqual(streams["cam-telemetry-low"]["sample_fps"], 2.0)

    def test_audit_records_capture_device_changes(self) -> None:
        self.runtime.register_device(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-audit",
                "protocol": "rtsp",
                "stream_url": "rtsp://10.0.0.40/live",
                "enabled": True,
            }
        )
        self.runtime.update_device_capabilities(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-audit",
                "capabilities": {"ocr": True, "face": False},
            }
        )

        records = self.runtime.list_audit_records(limit=10)
        actions = [item["action"] for item in records]
        self.assertIn("device.register", actions)
        self.assertIn("device.capabilities.update", actions)

    def test_audit_policy_limits_record_count(self) -> None:
        updated = self.runtime.update_audit_policy({"max_records": 3})
        self.assertEqual(3, updated["max_records"])
        self.assertEqual(3, self.runtime.get_audit_policy()["max_records"])

        for idx in range(6):
            self.runtime.register_device(
                {
                    "tenant_id": "t1",
                    "site_id": "s1",
                    "box_id": "b1",
                    "device_id": f"cam-retain-{idx}",
                    "protocol": "rtsp",
                    "stream_url": f"rtsp://10.0.0.{70 + idx}/live",
                    "enabled": True,
                }
            )

        records = self.runtime.list_audit_records(limit=20)
        self.assertLessEqual(len(records), 3)

    def test_update_and_get_network_policy(self) -> None:
        updated = self.runtime.update_network_policy(
            {
                "enforce_allowlist": True,
                "webhook_allowlist": ["https://hooks.example.com", "http://10.0.0.5:8080"],
            }
        )
        self.assertTrue(updated["enforce_allowlist"])
        self.assertEqual(2, len(updated["webhook_allowlist"]))

        current = self.runtime.get_network_policy()
        self.assertEqual(updated, current)

    def test_dispatch_respects_network_policy_allowlist(self) -> None:
        self.runtime.update_network_policy(
            {
                "enforce_allowlist": True,
                "webhook_allowlist": ["https://hooks.example.com"],
            }
        )
        self.runtime.ingest_event(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "source_id": "cam-1",
                "event_type": "line_crossing",
                "object_id": "p1",
                "payload": {"confidence": 0.88},
            },
            now=self.now,
        )

        sent_targets = []

        def sender(task) -> bool:
            sent_targets.append(task.target_url)
            return True

        result = self.runtime.dispatch_pushes(now=self.now, sender=sender)
        self.assertEqual(0, result["sent"])
        self.assertEqual(1, result["failed"])
        self.assertEqual([], sent_targets)
        first_snap = self.runtime.snapshot()
        self.assertEqual(0, first_snap["push_queue_size"])
        self.assertEqual(1, first_snap["dead_letter_size"])

        second = self.runtime.dispatch_pushes(now=self.now.replace(second=20), sender=sender)
        self.assertEqual(0, second["processed"])
        self.assertEqual(0, second["failed"])


if __name__ == "__main__":
    unittest.main()
