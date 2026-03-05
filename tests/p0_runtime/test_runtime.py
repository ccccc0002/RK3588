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
        self.assertEqual(0, report["start_index"])
        self.assertIsNone(report["next_start_index"])
        self.assertEqual([0, 2], report["applied_range"])
        self.assertEqual(2, report["total"])
        self.assertEqual(2, report["processed_count"])
        self.assertEqual(1, report["success_count"])
        self.assertEqual(1, report["error_count"])
        self.assertEqual([0], report["failed_indices"])
        self.assertFalse(report["retry_hint"]["should_retry"])
        self.assertIsNone(report["retry_hint"]["resume_from"])
        self.assertEqual(0, report["retry_hint"]["remaining_items"])
        self.assertEqual([0], report["retry_hint"]["failed_indices"])
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
        self.assertEqual(0, report["start_index"])
        self.assertEqual(1, report["next_start_index"])
        self.assertEqual([0, 1], report["applied_range"])
        self.assertEqual(1, report["max_errors"])
        self.assertEqual(2, report["total"])
        self.assertEqual(1, report["processed_count"])
        self.assertEqual(0, report["success_count"])
        self.assertEqual(1, report["error_count"])
        self.assertEqual([0], report["failed_indices"])
        self.assertTrue(report["retry_hint"]["should_retry"])
        self.assertEqual(1, report["retry_hint"]["resume_from"])
        self.assertEqual(1, report["retry_hint"]["remaining_items"])
        self.assertEqual([0], report["retry_hint"]["failed_indices"])
        self.assertTrue(report["stopped_early"])
        self.assertGreaterEqual(report["duration_ms"], 0)
        self.assertEqual(0, len(report["items"]))
        self.assertEqual(1, len(report["errors"]))
        self.assertEqual(0, report["errors"][0]["index"])

    def test_gray_rollout_dependency_plan_batch_start_index_offsets_error_indices(self) -> None:
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
                        "seed": "dep-plan-batch-offset-002",
                        "dependency_status": {
                            "gray_ready": True,
                            "edge_sync_ready": True,
                            "base_library_ready": True,
                        },
                    },
                ],
            }
        )
        self.assertEqual(10, report["start_index"])
        self.assertEqual(11, report["next_start_index"])
        self.assertEqual([10, 11], report["applied_range"])
        self.assertEqual([10], report["failed_indices"])
        self.assertTrue(report["retry_hint"]["should_retry"])
        self.assertEqual(11, report["retry_hint"]["resume_from"])
        self.assertEqual(1, report["retry_hint"]["remaining_items"])
        self.assertEqual([10], report["retry_hint"]["failed_indices"])
        self.assertEqual(1, len(report["errors"]))
        self.assertEqual(10, report["errors"][0]["index"])

    def test_gray_rollout_dependency_plan_batch_idempotency_cache_hit(self) -> None:
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
        payload = {
            "idempotency_key": "plan-batch-001",
            "continue_on_error": True,
            "items": [
                {
                    "tenant_id": "t1",
                    "site_id": "s1",
                    "box_id": "b1",
                    "seed": "plan-idem-001",
                    "dependency_status": {
                        "gray_ready": True,
                        "edge_sync_ready": True,
                    },
                },
            ],
        }
        first = self.runtime.batch_plan_gray_rollout_dependencies_report(dict(payload))
        second = self.runtime.batch_plan_gray_rollout_dependencies_report(dict(payload))
        self.assertEqual("plan-batch-001", first["idempotency_key"])
        self.assertFalse(first["cache_hit"])
        self.assertIsNotNone(first["cache_key"])
        self.assertIsNotNone(first["cache_expires_at"])
        self.assertEqual("plan-batch-001", second["idempotency_key"])
        self.assertTrue(second["cache_hit"])
        self.assertEqual(first["cache_key"], second["cache_key"])
        self.assertEqual(first["items"], second["items"])
        self.assertEqual(first["errors"], second["errors"])

    def test_gray_rollout_dependency_plan_batch_idempotency_conflict(self) -> None:
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
        first_payload = {
            "idempotency_key": "plan-batch-conflict-001",
            "continue_on_error": True,
            "items": [
                {
                    "tenant_id": "t1",
                    "site_id": "s1",
                    "box_id": "b1",
                    "seed": "plan-idem-conflict-001",
                    "dependency_status": {"gray_ready": True},
                },
            ],
        }
        self.runtime.batch_plan_gray_rollout_dependencies_report(dict(first_payload))

        conflict_payload = {
            "idempotency_key": "plan-batch-conflict-001",
            "continue_on_error": True,
            "items": [
                {
                    "tenant_id": "t2",
                    "site_id": "s2",
                    "box_id": "b2",
                    "seed": "plan-idem-conflict-002",
                    "dependency_status": {"gray_ready": True},
                },
            ],
        }
        with self.assertRaisesRegex(ValueError, "idempotency_key conflict with different payload"):
            self.runtime.batch_plan_gray_rollout_dependencies_report(dict(conflict_payload))

    def test_gray_rollout_dependency_plan_batch_cache_ttl_requires_idempotency_key(self) -> None:
        self.runtime.update_gray_rollout_policy(
            {
                "enabled": True,
                "default_percent": 100,
                "overrides": [],
                "dependencies": ["gray_ready"],
                "dependency_graph": {},
            }
        )
        with self.assertRaisesRegex(ValueError, "cache_ttl_seconds requires idempotency_key"):
            self.runtime.batch_plan_gray_rollout_dependencies_report(
                {
                    "cache_ttl_seconds": 10,
                    "continue_on_error": True,
                    "items": [
                        {
                            "tenant_id": "t1",
                            "site_id": "s1",
                            "box_id": "b1",
                            "dependency_status": {"gray_ready": True},
                        },
                    ],
                }
            )

    def test_gray_rollout_dependency_plan_batch_cache_ttl_validation(self) -> None:
        self.runtime.update_gray_rollout_policy(
            {
                "enabled": True,
                "default_percent": 100,
                "overrides": [],
                "dependencies": ["gray_ready"],
                "dependency_graph": {},
            }
        )
        with self.assertRaisesRegex(ValueError, "cache_ttl_seconds must be a positive integer"):
            self.runtime.batch_plan_gray_rollout_dependencies_report(
                {
                    "idempotency_key": "plan-batch-ttl-001",
                    "cache_ttl_seconds": 0,
                    "continue_on_error": True,
                    "items": [
                        {
                            "tenant_id": "t1",
                            "site_id": "s1",
                            "box_id": "b1",
                            "dependency_status": {"gray_ready": True},
                        },
                    ],
                }
            )
        with self.assertRaisesRegex(ValueError, "cache_ttl_seconds must be <= 3600"):
            self.runtime.batch_plan_gray_rollout_dependencies_report(
                {
                    "idempotency_key": "plan-batch-ttl-002",
                    "cache_ttl_seconds": 3601,
                    "continue_on_error": True,
                    "items": [
                        {
                            "tenant_id": "t1",
                            "site_id": "s1",
                            "box_id": "b1",
                            "dependency_status": {"gray_ready": True},
                        },
                    ],
                }
            )

    def test_gray_rollout_dependency_plan_batch_cache_metrics(self) -> None:
        self.runtime.update_gray_rollout_policy(
            {
                "enabled": True,
                "default_percent": 100,
                "overrides": [],
                "dependencies": ["gray_ready"],
                "dependency_graph": {},
            }
        )
        payload = {
            "idempotency_key": "plan-batch-metrics-001",
            "continue_on_error": True,
            "items": [
                {
                    "tenant_id": "t1",
                    "site_id": "s1",
                    "box_id": "b1",
                    "seed": "plan-metrics-seed-001",
                    "dependency_status": {"gray_ready": True},
                },
            ],
        }
        self.runtime.batch_plan_gray_rollout_dependencies_report(dict(payload))
        self.runtime.batch_plan_gray_rollout_dependencies_report(dict(payload))
        with self.assertRaisesRegex(ValueError, "idempotency_key conflict with different payload"):
            self.runtime.batch_plan_gray_rollout_dependencies_report(
                {
                    "idempotency_key": "plan-batch-metrics-001",
                    "continue_on_error": True,
                    "items": [
                        {
                            "tenant_id": "t9",
                            "site_id": "s9",
                            "box_id": "b9",
                            "seed": "plan-metrics-seed-conflict",
                            "dependency_status": {"gray_ready": True},
                        },
                    ],
                }
            )

        metrics = self.runtime.get_metrics()
        self.assertEqual(1, metrics["gray_batch_plan_cache_entries"])
        self.assertEqual(1, metrics["gray_batch_plan_cache_hits"])
        self.assertEqual(1, metrics["gray_batch_plan_cache_misses"])
        self.assertEqual(1, metrics["gray_batch_plan_cache_conflicts"])
        self.assertEqual(3, metrics["gray_batch_plan_cache_last_minute_requests"])
        self.assertEqual(1, metrics["gray_batch_plan_cache_last_minute_hits"])
        self.assertEqual(1, metrics["gray_batch_plan_cache_last_minute_misses"])
        self.assertEqual(1, metrics["gray_batch_plan_cache_last_minute_conflicts"])
        self.assertEqual(50, metrics["gray_batch_plan_cache_last_minute_hit_rate_percent"])
        self.assertIsNone(metrics["gray_batch_cache_policy_default_max_clear_entries"])
        self.assertFalse(metrics["gray_batch_cache_policy_enabled"])

    def test_gray_rollout_dependency_plan_batch_cache_evicted_expired_metric(self) -> None:
        self.runtime.update_gray_rollout_policy(
            {
                "enabled": True,
                "default_percent": 100,
                "overrides": [],
                "dependencies": ["gray_ready"],
                "dependency_graph": {},
            }
        )
        self.runtime.batch_plan_gray_rollout_dependencies_report(
            {
                "idempotency_key": "plan-batch-evict-expired-001",
                "cache_ttl_seconds": 60,
                "continue_on_error": True,
                "items": [
                    {
                        "tenant_id": "t1",
                        "site_id": "s1",
                        "box_id": "b1",
                        "seed": "plan-evict-expired-seed-001",
                        "dependency_status": {"gray_ready": True},
                    },
                ],
            }
        )
        with self.runtime._lock:
            self.runtime._gray_rollout_batch_plan_cache["plan-batch-evict-expired-001"]["expires_at"] = (
                self.now - timedelta(seconds=1)
            )

        metrics = self.runtime.get_metrics()
        self.assertEqual(0, metrics["gray_batch_plan_cache_entries"])
        self.assertGreaterEqual(metrics["gray_batch_plan_cache_evicted_expired"], 1)

    def test_gray_rollout_dependency_plan_batch_cache_evicted_overflow_metric(self) -> None:
        self.runtime.update_gray_rollout_policy(
            {
                "enabled": True,
                "default_percent": 100,
                "overrides": [],
                "dependencies": ["gray_ready"],
                "dependency_graph": {},
            }
        )
        original_limit = self.runtime._GRAY_BATCH_PLAN_CACHE_MAX_ENTRIES
        self.runtime._GRAY_BATCH_PLAN_CACHE_MAX_ENTRIES = 1
        try:
            self.runtime.batch_plan_gray_rollout_dependencies_report(
                {
                    "idempotency_key": "plan-batch-evict-overflow-001",
                    "continue_on_error": True,
                    "items": [
                        {
                            "tenant_id": "t1",
                            "site_id": "s1",
                            "box_id": "b1",
                            "seed": "plan-evict-overflow-seed-001",
                            "dependency_status": {"gray_ready": True},
                        },
                    ],
                }
            )
            self.runtime.batch_plan_gray_rollout_dependencies_report(
                {
                    "idempotency_key": "plan-batch-evict-overflow-002",
                    "continue_on_error": True,
                    "items": [
                        {
                            "tenant_id": "t2",
                            "site_id": "s2",
                            "box_id": "b2",
                            "seed": "plan-evict-overflow-seed-002",
                            "dependency_status": {"gray_ready": True},
                        },
                    ],
                }
            )
        finally:
            self.runtime._GRAY_BATCH_PLAN_CACHE_MAX_ENTRIES = original_limit

        metrics = self.runtime.get_metrics()
        self.assertEqual(1, metrics["gray_batch_plan_cache_entries"])
        self.assertGreaterEqual(metrics["gray_batch_plan_cache_evicted_overflow"], 1)

    def test_snapshot_includes_gray_batch_cache_observability(self) -> None:
        self.runtime.update_gray_rollout_batch_plan_cache_policy({"default_max_clear_entries": 9})
        self.runtime.update_gray_rollout_policy(
            {
                "enabled": True,
                "default_percent": 100,
                "overrides": [],
                "dependencies": ["gray_ready"],
                "dependency_graph": {},
            }
        )
        payload = {
            "idempotency_key": "plan-batch-snapshot-001",
            "continue_on_error": True,
            "items": [
                {
                    "tenant_id": "t1",
                    "site_id": "s1",
                    "box_id": "b1",
                    "seed": "plan-snapshot-seed-001",
                    "dependency_status": {"gray_ready": True},
                },
            ],
        }
        self.runtime.batch_plan_gray_rollout_dependencies_report(dict(payload))
        self.runtime.batch_plan_gray_rollout_dependencies_report(dict(payload))
        with self.assertRaisesRegex(ValueError, "idempotency_key conflict with different payload"):
            self.runtime.batch_plan_gray_rollout_dependencies_report(
                {
                    "idempotency_key": "plan-batch-snapshot-001",
                    "continue_on_error": True,
                    "items": [
                        {
                            "tenant_id": "t9",
                            "site_id": "s9",
                            "box_id": "b9",
                            "seed": "plan-snapshot-seed-conflict",
                            "dependency_status": {"gray_ready": True},
                        },
                    ],
                }
            )

        snap = self.runtime.snapshot()
        self.assertEqual(1, snap["gray_batch_plan_cache_entries"])
        self.assertEqual(1, snap["gray_batch_plan_cache_hits"])
        self.assertEqual(1, snap["gray_batch_plan_cache_misses"])
        self.assertEqual(1, snap["gray_batch_plan_cache_conflicts"])
        self.assertGreaterEqual(snap["gray_batch_plan_cache_evicted_expired"], 0)
        self.assertGreaterEqual(snap["gray_batch_plan_cache_evicted_overflow"], 0)
        self.assertEqual(3, snap["gray_batch_plan_cache_last_minute_requests"])
        self.assertEqual(1, snap["gray_batch_plan_cache_last_minute_hits"])
        self.assertEqual(1, snap["gray_batch_plan_cache_last_minute_misses"])
        self.assertEqual(1, snap["gray_batch_plan_cache_last_minute_conflicts"])
        self.assertEqual(50, snap["gray_batch_plan_cache_last_minute_hit_rate_percent"])
        self.assertEqual(9, snap["gray_batch_cache_policy_default_max_clear_entries"])
        self.assertTrue(snap["gray_batch_cache_policy_enabled"])

    def test_clear_gray_rollout_batch_plan_cache(self) -> None:
        self.runtime.update_gray_rollout_policy(
            {
                "enabled": True,
                "default_percent": 100,
                "overrides": [],
                "dependencies": ["gray_ready"],
                "dependency_graph": {},
            }
        )
        payload = {
            "idempotency_key": "plan-batch-clear-001",
            "continue_on_error": True,
            "items": [
                {
                    "tenant_id": "t1",
                    "site_id": "s1",
                    "box_id": "b1",
                    "seed": "plan-clear-seed-001",
                    "dependency_status": {"gray_ready": True},
                },
            ],
        }
        self.runtime.batch_plan_gray_rollout_dependencies_report(dict(payload))
        self.runtime.batch_plan_gray_rollout_dependencies_report(dict(payload))
        with self.assertRaisesRegex(ValueError, "idempotency_key conflict with different payload"):
            self.runtime.batch_plan_gray_rollout_dependencies_report(
                {
                    "idempotency_key": "plan-batch-clear-001",
                    "continue_on_error": True,
                    "items": [
                        {
                            "tenant_id": "t9",
                            "site_id": "s9",
                            "box_id": "b9",
                            "seed": "plan-clear-seed-conflict",
                            "dependency_status": {"gray_ready": True},
                        },
                    ],
                }
            )
        dry_run_result = self.runtime.clear_gray_rollout_batch_plan_cache(
            {"dry_run": True, "reset_counters": True}
        )
        self.assertTrue(dry_run_result["dry_run"])
        self.assertEqual(0, dry_run_result["cleared_entries"])
        self.assertEqual(0, dry_run_result["cleared_events"])
        self.assertEqual(1, dry_run_result["would_clear_entries"])
        self.assertGreaterEqual(dry_run_result["would_clear_events"], 3)
        self.assertTrue(dry_run_result["reset_counters"])
        self.assertFalse(dry_run_result["reset_counters_applied"])
        self.assertEqual(1, dry_run_result["gray_batch_plan_cache_entries"])
        self.assertEqual(1, dry_run_result["gray_batch_plan_cache_hits"])
        self.assertEqual(1, dry_run_result["gray_batch_plan_cache_misses"])
        self.assertEqual(1, dry_run_result["gray_batch_plan_cache_conflicts"])

        cleared_no_reset = self.runtime.clear_gray_rollout_batch_plan_cache({"reset_counters": False})
        self.assertEqual(1, cleared_no_reset["cleared_entries"])
        self.assertGreaterEqual(cleared_no_reset["cleared_events"], 3)
        self.assertFalse(cleared_no_reset["dry_run"])
        self.assertEqual(cleared_no_reset["cleared_entries"], cleared_no_reset["would_clear_entries"])
        self.assertEqual(cleared_no_reset["cleared_events"], cleared_no_reset["would_clear_events"])
        self.assertFalse(cleared_no_reset["reset_counters"])
        self.assertFalse(cleared_no_reset["reset_counters_applied"])
        self.assertEqual(0, cleared_no_reset["gray_batch_plan_cache_entries"])
        self.assertEqual(1, cleared_no_reset["gray_batch_plan_cache_hits"])
        self.assertEqual(1, cleared_no_reset["gray_batch_plan_cache_misses"])
        self.assertEqual(1, cleared_no_reset["gray_batch_plan_cache_conflicts"])

        self.runtime.batch_plan_gray_rollout_dependencies_report(
            {
                "idempotency_key": "plan-batch-clear-002",
                "continue_on_error": True,
                "items": [
                    {
                        "tenant_id": "t2",
                        "site_id": "s2",
                        "box_id": "b2",
                        "seed": "plan-clear-seed-002",
                        "dependency_status": {"gray_ready": True},
                    },
                ],
            }
        )
        cleared_with_reset = self.runtime.clear_gray_rollout_batch_plan_cache({"reset_counters": True})
        self.assertFalse(cleared_with_reset["dry_run"])
        self.assertTrue(cleared_with_reset["reset_counters"])
        self.assertTrue(cleared_with_reset["reset_counters_applied"])
        self.assertEqual(0, cleared_with_reset["gray_batch_plan_cache_entries"])
        self.assertEqual(0, cleared_with_reset["gray_batch_plan_cache_hits"])
        self.assertEqual(0, cleared_with_reset["gray_batch_plan_cache_misses"])
        self.assertEqual(0, cleared_with_reset["gray_batch_plan_cache_conflicts"])
        self.assertEqual(0, cleared_with_reset["gray_batch_plan_cache_evicted_expired"])
        self.assertEqual(0, cleared_with_reset["gray_batch_plan_cache_evicted_overflow"])

    def test_list_gray_rollout_batch_plan_cache(self) -> None:
        self.runtime.update_gray_rollout_policy(
            {
                "enabled": True,
                "default_percent": 100,
                "overrides": [],
                "dependencies": ["gray_ready"],
                "dependency_graph": {},
            }
        )
        self.runtime.batch_plan_gray_rollout_dependencies_report(
            {
                "idempotency_key": "plan-batch-list-001",
                "continue_on_error": True,
                "items": [
                    {
                        "tenant_id": "t1",
                        "site_id": "s1",
                        "box_id": "b1",
                        "seed": "plan-list-seed-001",
                        "dependency_status": {"gray_ready": True},
                    },
                ],
            }
        )
        self.runtime.batch_plan_gray_rollout_dependencies_report(
            {
                "idempotency_key": "plan-batch-list-002",
                "continue_on_error": True,
                "items": [
                    {
                        "tenant_id": "t2",
                        "site_id": "s2",
                        "box_id": "b2",
                        "seed": "plan-list-seed-002",
                        "dependency_status": {"gray_ready": True},
                    },
                ],
            }
        )

        listed = self.runtime.list_gray_rollout_batch_plan_cache()
        self.assertEqual(2, listed["total_entries"])
        self.assertEqual(2, listed["returned_entries"])
        self.assertEqual(20, listed["limit"])
        self.assertEqual(200, listed["max_limit"])
        self.assertEqual(512, listed["max_entries"])
        self.assertEqual(300, listed["default_ttl_seconds"])
        self.assertEqual(3600, listed["max_ttl_seconds"])
        self.assertEqual(2, len(listed["items"]))
        self.assertNotIn("event_window", listed)
        self.assertIn("idempotency_key", listed["items"][0])
        self.assertIn("created_at", listed["items"][0])
        self.assertIn("expires_at", listed["items"][0])
        self.assertIn("ttl_remaining_seconds", listed["items"][0])
        self.assertIn("age_seconds", listed["items"][0])

        listed_with_events = self.runtime.list_gray_rollout_batch_plan_cache({"limit": 1, "include_events": True})
        self.assertEqual(1, listed_with_events["returned_entries"])
        self.assertIn("event_window", listed_with_events)
        self.assertGreaterEqual(int(listed_with_events["event_window"]["event_count"]), 2)

        with self.assertRaisesRegex(ValueError, "limit must be within \\[1, 200\\]"):
            self.runtime.list_gray_rollout_batch_plan_cache({"limit": 0})
        with self.assertRaisesRegex(ValueError, "limit must be within \\[1, 200\\]"):
            self.runtime.list_gray_rollout_batch_plan_cache({"limit": 201})
        with self.assertRaisesRegex(ValueError, "limit must be an integer"):
            self.runtime.list_gray_rollout_batch_plan_cache({"limit": "bad"})

    def test_clear_gray_rollout_batch_plan_cache_max_clear_entries_guard(self) -> None:
        self.runtime.update_gray_rollout_policy(
            {
                "enabled": True,
                "default_percent": 100,
                "overrides": [],
                "dependencies": ["gray_ready"],
                "dependency_graph": {},
            }
        )
        self.runtime.batch_plan_gray_rollout_dependencies_report(
            {
                "idempotency_key": "plan-batch-guard-001",
                "continue_on_error": True,
                "items": [
                    {
                        "tenant_id": "t1",
                        "site_id": "s1",
                        "box_id": "b1",
                        "seed": "plan-guard-seed-001",
                        "dependency_status": {"gray_ready": True},
                    },
                ],
            }
        )
        self.runtime.batch_plan_gray_rollout_dependencies_report(
            {
                "idempotency_key": "plan-batch-guard-002",
                "continue_on_error": True,
                "items": [
                    {
                        "tenant_id": "t2",
                        "site_id": "s2",
                        "box_id": "b2",
                        "seed": "plan-guard-seed-002",
                        "dependency_status": {"gray_ready": True},
                    },
                ],
            }
        )

        with self.assertRaisesRegex(ValueError, "exceeds max_clear_entries"):
            self.runtime.clear_gray_rollout_batch_plan_cache({"max_clear_entries": 1})

        guard_dry_run = self.runtime.clear_gray_rollout_batch_plan_cache(
            {"dry_run": True, "max_clear_entries": 1}
        )
        self.assertTrue(guard_dry_run["dry_run"])
        self.assertEqual(0, guard_dry_run["cleared_entries"])
        self.assertEqual(2, guard_dry_run["would_clear_entries"])
        self.assertEqual(1, guard_dry_run["max_clear_entries"])

        guard_clear = self.runtime.clear_gray_rollout_batch_plan_cache(
            {"max_clear_entries": 2, "reset_counters": True}
        )
        self.assertFalse(guard_clear["dry_run"])
        self.assertEqual(2, guard_clear["cleared_entries"])
        self.assertEqual(2, guard_clear["max_clear_entries"])
        self.assertEqual(0, guard_clear["gray_batch_plan_cache_entries"])

        with self.assertRaisesRegex(ValueError, "max_clear_entries must be a positive integer"):
            self.runtime.clear_gray_rollout_batch_plan_cache({"max_clear_entries": 0})
        with self.assertRaisesRegex(ValueError, "max_clear_entries must be a positive integer"):
            self.runtime.clear_gray_rollout_batch_plan_cache({"max_clear_entries": "bad"})

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

    def test_list_audit_records_before_id_cursor(self) -> None:
        for idx in range(3):
            self.runtime.register_device(
                {
                    "tenant_id": "t1",
                    "site_id": "s1",
                    "box_id": "b1",
                    "device_id": f"cam-audit-cursor-{idx}",
                    "protocol": "rtsp",
                    "stream_url": f"rtsp://10.0.1.{idx}/live",
                    "enabled": True,
                }
            )

        items = self.runtime.list_audit_records(limit=10)
        self.assertGreaterEqual(len(items), 3)
        anchor_id = int(items[1]["id"])
        older_items = self.runtime.list_audit_records(limit=10, before_id=anchor_id)
        self.assertGreaterEqual(len(older_items), 1)
        self.assertTrue(all(int(item["id"]) < anchor_id for item in older_items))

        with self.assertRaisesRegex(ValueError, "before_id must be a positive integer"):
            self.runtime.list_audit_records(limit=10, before_id=0)
        with self.assertRaisesRegex(ValueError, "before_id must be a positive integer"):
            self.runtime.list_audit_records(limit=10, before_id="bad")
        with self.assertRaisesRegex(ValueError, "limit must be within \\[1, 200\\]"):
            self.runtime.list_audit_records(limit=0)
        with self.assertRaisesRegex(ValueError, "limit must be an integer"):
            self.runtime.list_audit_records(limit="bad")

        page = self.runtime.list_audit_records_page(limit=1)
        self.assertEqual(1, page["limit"])
        self.assertIsNone(page["before_id"])
        self.assertEqual("limit=1&include_total=false", page["query_string"])
        self.assertIn("snapshot_at", page)
        datetime.fromisoformat(str(page["snapshot_at"]))
        self.assertEqual(1, page["returned_items"])
        self.assertEqual(int(page["items"][0]["id"]), int(page["window_max_id"]))
        self.assertEqual(int(page["items"][-1]["id"]), int(page["window_min_id"]))
        self.assertEqual(
            int(page["window_max_id"]) - int(page["window_min_id"]) + 1,
            int(page["window_span"]),
        )
        self.assertEqual(bool(int(page["window_span"]) == int(page["returned_items"])), bool(page["dense_window"]))
        self.assertEqual(max(0, int(page["window_span"]) - int(page["returned_items"])), int(page["id_gap_count"]))
        self.assertEqual(bool(int(page["id_gap_count"]) == 0), bool(page["dense_window"]))
        self.assertAlmostEqual(
            float(page["returned_items"]) / float(page["window_span"]),
            float(page["window_density"]),
            places=6,
        )
        self.assertEqual(str(page["items"][0]["at"]), page["window_newest_at"])
        self.assertEqual(str(page["items"][-1]["at"]), page["window_oldest_at"])
        self.assertTrue(bool(page["window_time_parseable"]))
        self.assertEqual(0, int(page["window_time_unparseable_count"]))
        self.assertAlmostEqual(0.0, float(page["window_time_unparseable_ratio"]), places=6)
        self.assertEqual(
            max(
                0,
                int(
                    (
                        datetime.fromisoformat(str(page["items"][0]["at"]))
                        - datetime.fromisoformat(str(page["items"][-1]["at"]))
                    ).total_seconds()
                ),
            ),
            int(page["window_time_span_seconds"]),
        )
        self.assertEqual(
            all(
                datetime.fromisoformat(str(page["items"][i]["at"]))
                >= datetime.fromisoformat(str(page["items"][i + 1]["at"]))
                for i in range(len(page["items"]) - 1)
            ),
            bool(page["window_time_desc_order"]),
        )
        self.assertEqual(
            max(
                abs(
                    int(
                        (
                            datetime.fromisoformat(str(page["items"][i]["at"]))
                            - datetime.fromisoformat(str(page["items"][i + 1]["at"]))
                        ).total_seconds()
                    )
                )
                for i in range(len(page["items"]) - 1)
            )
            if len(page["items"]) > 1
            else 0,
            int(page["window_time_gap_max_seconds"]),
        )
        self.assertEqual(0, int(page["window_time_gap_min_seconds"]))
        self.assertEqual(0, int(page["window_time_gap_count"]))
        self.assertAlmostEqual(0.0, float(page["window_time_gap_total_seconds"]), places=6)
        self.assertAlmostEqual(
            (
                sum(
                    abs(
                        (
                            datetime.fromisoformat(str(page["items"][i]["at"]))
                            - datetime.fromisoformat(str(page["items"][i + 1]["at"]))
                        ).total_seconds()
                    )
                    for i in range(len(page["items"]) - 1)
                )
                / float(len(page["items"]) - 1)
            )
            if len(page["items"]) > 1
            else 0.0,
            float(page["window_time_gap_avg_seconds"]),
            places=6,
        )
        self.assertEqual("id_desc", page["order"])
        self.assertIsNone(page["total_candidates"])
        self.assertIsNone(page["remaining_candidates"])
        self.assertTrue(page["has_more"])
        self.assertIsNotNone(page["next_before_id"])
        self.assertIsNotNone(page["next_query"])
        self.assertIsNotNone(page["next_query_string"])
        self.assertIn(f"before_id={page['next_before_id']}", page["next_query_string"])
        self.assertEqual(page["next_before_id"], page["next_query"]["before_id"])
        self.assertFalse(page["next_query"]["include_total"])
        self.assertEqual(1, len(page["items"]))

        page_with_cursor = self.runtime.list_audit_records_page(limit=1, before_id=anchor_id)
        self.assertEqual(anchor_id, page_with_cursor["before_id"])
        self.assertEqual(f"limit=1&before_id={anchor_id}&include_total=false", page_with_cursor["query_string"])
        self.assertEqual("id_desc", page_with_cursor["order"])
        self.assertIsNone(page_with_cursor["total_candidates"])
        self.assertIsNone(page_with_cursor["remaining_candidates"])
        if page_with_cursor["items"]:
            self.assertEqual(int(page_with_cursor["items"][0]["id"]), int(page_with_cursor["window_max_id"]))
            self.assertEqual(int(page_with_cursor["items"][-1]["id"]), int(page_with_cursor["window_min_id"]))
            self.assertEqual(
                int(page_with_cursor["window_max_id"]) - int(page_with_cursor["window_min_id"]) + 1,
                int(page_with_cursor["window_span"]),
            )
            self.assertEqual(
                bool(int(page_with_cursor["window_span"]) == int(page_with_cursor["returned_items"])),
                bool(page_with_cursor["dense_window"]),
            )
            self.assertEqual(
                max(0, int(page_with_cursor["window_span"]) - int(page_with_cursor["returned_items"])),
                int(page_with_cursor["id_gap_count"]),
            )
            self.assertEqual(bool(int(page_with_cursor["id_gap_count"]) == 0), bool(page_with_cursor["dense_window"]))
            self.assertAlmostEqual(
                float(page_with_cursor["returned_items"]) / float(page_with_cursor["window_span"]),
                float(page_with_cursor["window_density"]),
                places=6,
            )
            self.assertEqual(str(page_with_cursor["items"][0]["at"]), page_with_cursor["window_newest_at"])
            self.assertEqual(str(page_with_cursor["items"][-1]["at"]), page_with_cursor["window_oldest_at"])
            self.assertTrue(bool(page_with_cursor["window_time_parseable"]))
            self.assertEqual(0, int(page_with_cursor["window_time_unparseable_count"]))
            self.assertAlmostEqual(0.0, float(page_with_cursor["window_time_unparseable_ratio"]), places=6)
            self.assertEqual(
                max(
                    0,
                    int(
                        (
                            datetime.fromisoformat(str(page_with_cursor["items"][0]["at"]))
                            - datetime.fromisoformat(str(page_with_cursor["items"][-1]["at"]))
                        ).total_seconds()
                    ),
                ),
                int(page_with_cursor["window_time_span_seconds"]),
            )
            self.assertEqual(
                all(
                    datetime.fromisoformat(str(page_with_cursor["items"][i]["at"]))
                    >= datetime.fromisoformat(str(page_with_cursor["items"][i + 1]["at"]))
                    for i in range(len(page_with_cursor["items"]) - 1)
                ),
                bool(page_with_cursor["window_time_desc_order"]),
            )
            self.assertEqual(
                max(
                    abs(
                        int(
                            (
                                datetime.fromisoformat(str(page_with_cursor["items"][i]["at"]))
                                - datetime.fromisoformat(str(page_with_cursor["items"][i + 1]["at"]))
                            ).total_seconds()
                        )
                    )
                    for i in range(len(page_with_cursor["items"]) - 1)
                )
                if len(page_with_cursor["items"]) > 1
                else 0,
                int(page_with_cursor["window_time_gap_max_seconds"]),
            )
            self.assertEqual(0, int(page_with_cursor["window_time_gap_min_seconds"]))
            self.assertEqual(0, int(page_with_cursor["window_time_gap_count"]))
            self.assertAlmostEqual(0.0, float(page_with_cursor["window_time_gap_total_seconds"]), places=6)
            self.assertAlmostEqual(
                (
                    sum(
                        abs(
                            (
                                datetime.fromisoformat(str(page_with_cursor["items"][i]["at"]))
                                - datetime.fromisoformat(str(page_with_cursor["items"][i + 1]["at"]))
                            ).total_seconds()
                        )
                        for i in range(len(page_with_cursor["items"]) - 1)
                    )
                    / float(len(page_with_cursor["items"]) - 1)
                )
                if len(page_with_cursor["items"]) > 1
                else 0.0,
                float(page_with_cursor["window_time_gap_avg_seconds"]),
                places=6,
            )
        else:
            self.assertIsNone(page_with_cursor["window_max_id"])
            self.assertIsNone(page_with_cursor["window_min_id"])
            self.assertIsNone(page_with_cursor["window_span"])
            self.assertIsNone(page_with_cursor["dense_window"])
            self.assertIsNone(page_with_cursor["id_gap_count"])
            self.assertIsNone(page_with_cursor["window_density"])
            self.assertIsNone(page_with_cursor["window_newest_at"])
            self.assertIsNone(page_with_cursor["window_oldest_at"])
            self.assertIsNone(page_with_cursor["window_time_parseable"])
            self.assertIsNone(page_with_cursor["window_time_unparseable_count"])
            self.assertIsNone(page_with_cursor["window_time_unparseable_ratio"])
            self.assertIsNone(page_with_cursor["window_time_span_seconds"])
            self.assertIsNone(page_with_cursor["window_time_desc_order"])
            self.assertIsNone(page_with_cursor["window_time_gap_max_seconds"])
            self.assertIsNone(page_with_cursor["window_time_gap_min_seconds"])
            self.assertIsNone(page_with_cursor["window_time_gap_count"])
            self.assertIsNone(page_with_cursor["window_time_gap_total_seconds"])
            self.assertIsNone(page_with_cursor["window_time_gap_avg_seconds"])
        if page_with_cursor["has_more"]:
            self.assertIsNotNone(page_with_cursor["next_query_string"])
        else:
            self.assertIsNone(page_with_cursor["next_query_string"])

        page_with_total = self.runtime.list_audit_records_page(limit=1, include_total=True)
        self.assertEqual("limit=1&include_total=true", page_with_total["query_string"])
        self.assertGreaterEqual(int(page_with_total["total_candidates"]), 3)
        self.assertEqual(
            int(page_with_total["total_candidates"]) - int(page_with_total["returned_items"]),
            int(page_with_total["remaining_candidates"]),
        )
        self.assertEqual(int(page_with_total["items"][0]["id"]), int(page_with_total["window_max_id"]))
        self.assertEqual(int(page_with_total["items"][-1]["id"]), int(page_with_total["window_min_id"]))
        self.assertEqual(
            int(page_with_total["window_max_id"]) - int(page_with_total["window_min_id"]) + 1,
            int(page_with_total["window_span"]),
        )
        self.assertEqual(
            bool(int(page_with_total["window_span"]) == int(page_with_total["returned_items"])),
            bool(page_with_total["dense_window"]),
        )
        self.assertEqual(
            max(0, int(page_with_total["window_span"]) - int(page_with_total["returned_items"])),
            int(page_with_total["id_gap_count"]),
        )
        self.assertEqual(bool(int(page_with_total["id_gap_count"]) == 0), bool(page_with_total["dense_window"]))
        self.assertAlmostEqual(
            float(page_with_total["returned_items"]) / float(page_with_total["window_span"]),
            float(page_with_total["window_density"]),
            places=6,
        )
        self.assertEqual(str(page_with_total["items"][0]["at"]), page_with_total["window_newest_at"])
        self.assertEqual(str(page_with_total["items"][-1]["at"]), page_with_total["window_oldest_at"])
        self.assertTrue(bool(page_with_total["window_time_parseable"]))
        self.assertEqual(0, int(page_with_total["window_time_unparseable_count"]))
        self.assertAlmostEqual(0.0, float(page_with_total["window_time_unparseable_ratio"]), places=6)
        self.assertEqual(
            max(
                0,
                int(
                    (
                        datetime.fromisoformat(str(page_with_total["items"][0]["at"]))
                        - datetime.fromisoformat(str(page_with_total["items"][-1]["at"]))
                    ).total_seconds()
                ),
            ),
            int(page_with_total["window_time_span_seconds"]),
        )
        self.assertEqual(
            all(
                datetime.fromisoformat(str(page_with_total["items"][i]["at"]))
                >= datetime.fromisoformat(str(page_with_total["items"][i + 1]["at"]))
                for i in range(len(page_with_total["items"]) - 1)
            ),
            bool(page_with_total["window_time_desc_order"]),
        )
        self.assertEqual(
            max(
                abs(
                    int(
                        (
                            datetime.fromisoformat(str(page_with_total["items"][i]["at"]))
                            - datetime.fromisoformat(str(page_with_total["items"][i + 1]["at"]))
                        ).total_seconds()
                    )
                )
                for i in range(len(page_with_total["items"]) - 1)
            )
            if len(page_with_total["items"]) > 1
            else 0,
            int(page_with_total["window_time_gap_max_seconds"]),
        )
        self.assertEqual(0, int(page_with_total["window_time_gap_min_seconds"]))
        self.assertEqual(0, int(page_with_total["window_time_gap_count"]))
        self.assertAlmostEqual(0.0, float(page_with_total["window_time_gap_total_seconds"]), places=6)
        self.assertAlmostEqual(
            (
                sum(
                    abs(
                        (
                            datetime.fromisoformat(str(page_with_total["items"][i]["at"]))
                            - datetime.fromisoformat(str(page_with_total["items"][i + 1]["at"]))
                        ).total_seconds()
                    )
                    for i in range(len(page_with_total["items"]) - 1)
                )
                / float(len(page_with_total["items"]) - 1)
            )
            if len(page_with_total["items"]) > 1
            else 0.0,
            float(page_with_total["window_time_gap_avg_seconds"]),
            places=6,
        )
        self.assertIsNotNone(page_with_total["next_query"])
        self.assertIsNotNone(page_with_total["next_query_string"])
        self.assertIn("include_total=true", page_with_total["next_query_string"])
        self.assertTrue(page_with_total["next_query"]["include_total"])
        with self.assertRaisesRegex(ValueError, "include_total must be a boolean"):
            self.runtime.list_audit_records_page(limit=1, include_total="bad")

    def test_list_gray_rollout_batch_plan_cache_operations(self) -> None:
        self.runtime.update_gray_rollout_policy(
            {
                "enabled": True,
                "default_percent": 100,
                "overrides": [],
                "dependencies": ["gray_ready"],
                "dependency_graph": {},
            }
        )
        self.runtime.batch_plan_gray_rollout_dependencies_report(
            {
                "idempotency_key": "ops-cache-001",
                "continue_on_error": True,
                "items": [
                    {
                        "tenant_id": "t1",
                        "site_id": "s1",
                        "box_id": "b1",
                        "seed": "ops-cache-seed-001",
                        "dependency_status": {"gray_ready": True},
                    },
                ],
            }
        )
        self.runtime.batch_plan_gray_rollout_dependencies_report(
            {
                "idempotency_key": "ops-cache-002",
                "continue_on_error": True,
                "items": [
                    {
                        "tenant_id": "t2",
                        "site_id": "s2",
                        "box_id": "b2",
                        "seed": "ops-cache-seed-002",
                        "dependency_status": {"gray_ready": True},
                    },
                ],
            }
        )
        self.runtime.clear_gray_rollout_batch_plan_cache({"dry_run": True, "max_clear_entries": 1})
        with self.assertRaisesRegex(ValueError, "exceeds max_clear_entries"):
            self.runtime.clear_gray_rollout_batch_plan_cache({"max_clear_entries": 1})
        self.runtime.clear_gray_rollout_batch_plan_cache({"max_clear_entries": 2, "reset_counters": True})

        items = self.runtime.list_gray_rollout_batch_plan_cache_operations(limit=10)
        actions = [item.get("action") for item in items]
        self.assertIn("gray_rollout.plan_batch.cache.clear.preview", actions)
        self.assertIn("gray_rollout.plan_batch.cache.clear.blocked", actions)
        self.assertIn("gray_rollout.plan_batch.cache.clear", actions)
        self.assertNotIn("device.register", actions)
        self.assertGreaterEqual(len(items), 3)

        anchor_id = int(items[1]["id"])
        older_items = self.runtime.list_gray_rollout_batch_plan_cache_operations(limit=10, before_id=anchor_id)
        self.assertGreaterEqual(len(older_items), 1)
        self.assertTrue(all(int(item["id"]) < anchor_id for item in older_items))

        with self.assertRaisesRegex(ValueError, "limit must be within \\[1, 200\\]"):
            self.runtime.list_gray_rollout_batch_plan_cache_operations(limit=0)
        with self.assertRaisesRegex(ValueError, "limit must be an integer"):
            self.runtime.list_gray_rollout_batch_plan_cache_operations(limit="bad")
        with self.assertRaisesRegex(ValueError, "before_id must be a positive integer"):
            self.runtime.list_gray_rollout_batch_plan_cache_operations(limit=10, before_id=0)
        with self.assertRaisesRegex(ValueError, "before_id must be a positive integer"):
            self.runtime.list_gray_rollout_batch_plan_cache_operations(limit=10, before_id="bad")

        page = self.runtime.list_gray_rollout_batch_plan_cache_operations_page(limit=1)
        self.assertEqual(1, page["limit"])
        self.assertIsNone(page["before_id"])
        self.assertEqual("limit=1&include_total=false", page["query_string"])
        self.assertIn("snapshot_at", page)
        datetime.fromisoformat(str(page["snapshot_at"]))
        self.assertEqual(1, page["returned_items"])
        self.assertEqual(int(page["items"][0]["id"]), int(page["window_max_id"]))
        self.assertEqual(int(page["items"][-1]["id"]), int(page["window_min_id"]))
        self.assertEqual(
            int(page["window_max_id"]) - int(page["window_min_id"]) + 1,
            int(page["window_span"]),
        )
        self.assertEqual(bool(int(page["window_span"]) == int(page["returned_items"])), bool(page["dense_window"]))
        self.assertEqual(max(0, int(page["window_span"]) - int(page["returned_items"])), int(page["id_gap_count"]))
        self.assertEqual(bool(int(page["id_gap_count"]) == 0), bool(page["dense_window"]))
        self.assertAlmostEqual(
            float(page["returned_items"]) / float(page["window_span"]),
            float(page["window_density"]),
            places=6,
        )
        self.assertEqual(str(page["items"][0]["at"]), page["window_newest_at"])
        self.assertEqual(str(page["items"][-1]["at"]), page["window_oldest_at"])
        self.assertEqual(
            max(
                0,
                int(
                    (
                        datetime.fromisoformat(str(page["items"][0]["at"]))
                        - datetime.fromisoformat(str(page["items"][-1]["at"]))
                    ).total_seconds()
                ),
            ),
            int(page["window_time_span_seconds"]),
        )
        self.assertEqual(
            all(
                datetime.fromisoformat(str(page["items"][i]["at"]))
                >= datetime.fromisoformat(str(page["items"][i + 1]["at"]))
                for i in range(len(page["items"]) - 1)
            ),
            bool(page["window_time_desc_order"]),
        )
        self.assertEqual(
            max(
                abs(
                    int(
                        (
                            datetime.fromisoformat(str(page["items"][i]["at"]))
                            - datetime.fromisoformat(str(page["items"][i + 1]["at"]))
                        ).total_seconds()
                    )
                )
                for i in range(len(page["items"]) - 1)
            )
            if len(page["items"]) > 1
            else 0,
            int(page["window_time_gap_max_seconds"]),
        )
        self.assertEqual(0, int(page["window_time_gap_min_seconds"]))
        self.assertEqual(0, int(page["window_time_gap_count"]))
        self.assertAlmostEqual(
            (
                sum(
                    abs(
                        (
                            datetime.fromisoformat(str(page["items"][i]["at"]))
                            - datetime.fromisoformat(str(page["items"][i + 1]["at"]))
                        ).total_seconds()
                    )
                    for i in range(len(page["items"]) - 1)
                )
                / float(len(page["items"]) - 1)
            )
            if len(page["items"]) > 1
            else 0.0,
            float(page["window_time_gap_avg_seconds"]),
            places=6,
        )
        self.assertEqual("id_desc", page["order"])
        self.assertIsNone(page["total_candidates"])
        self.assertIsNone(page["remaining_candidates"])
        self.assertTrue(page["has_more"])
        self.assertIsNotNone(page["next_before_id"])
        self.assertIsNotNone(page["next_query"])
        self.assertIsNotNone(page["next_query_string"])
        self.assertIn(f"before_id={page['next_before_id']}", page["next_query_string"])
        self.assertEqual(page["next_before_id"], page["next_query"]["before_id"])
        self.assertFalse(page["next_query"]["include_total"])
        self.assertEqual(1, len(page["items"]))

        page_with_cursor = self.runtime.list_gray_rollout_batch_plan_cache_operations_page(limit=1, before_id=anchor_id)
        self.assertEqual(anchor_id, page_with_cursor["before_id"])
        self.assertEqual(f"limit=1&before_id={anchor_id}&include_total=false", page_with_cursor["query_string"])
        self.assertEqual("id_desc", page_with_cursor["order"])
        self.assertIsNone(page_with_cursor["total_candidates"])
        self.assertIsNone(page_with_cursor["remaining_candidates"])
        if page_with_cursor["items"]:
            self.assertEqual(int(page_with_cursor["items"][0]["id"]), int(page_with_cursor["window_max_id"]))
            self.assertEqual(int(page_with_cursor["items"][-1]["id"]), int(page_with_cursor["window_min_id"]))
            self.assertEqual(
                int(page_with_cursor["window_max_id"]) - int(page_with_cursor["window_min_id"]) + 1,
                int(page_with_cursor["window_span"]),
            )
            self.assertEqual(
                bool(int(page_with_cursor["window_span"]) == int(page_with_cursor["returned_items"])),
                bool(page_with_cursor["dense_window"]),
            )
            self.assertEqual(
                max(0, int(page_with_cursor["window_span"]) - int(page_with_cursor["returned_items"])),
                int(page_with_cursor["id_gap_count"]),
            )
            self.assertEqual(bool(int(page_with_cursor["id_gap_count"]) == 0), bool(page_with_cursor["dense_window"]))
            self.assertAlmostEqual(
                float(page_with_cursor["returned_items"]) / float(page_with_cursor["window_span"]),
                float(page_with_cursor["window_density"]),
                places=6,
            )
            self.assertEqual(str(page_with_cursor["items"][0]["at"]), page_with_cursor["window_newest_at"])
            self.assertEqual(str(page_with_cursor["items"][-1]["at"]), page_with_cursor["window_oldest_at"])
            self.assertEqual(
                max(
                    0,
                    int(
                        (
                            datetime.fromisoformat(str(page_with_cursor["items"][0]["at"]))
                            - datetime.fromisoformat(str(page_with_cursor["items"][-1]["at"]))
                        ).total_seconds()
                    ),
                ),
                int(page_with_cursor["window_time_span_seconds"]),
            )
            self.assertEqual(
                all(
                    datetime.fromisoformat(str(page_with_cursor["items"][i]["at"]))
                    >= datetime.fromisoformat(str(page_with_cursor["items"][i + 1]["at"]))
                    for i in range(len(page_with_cursor["items"]) - 1)
                ),
                bool(page_with_cursor["window_time_desc_order"]),
            )
            self.assertEqual(
                max(
                    abs(
                        int(
                            (
                                datetime.fromisoformat(str(page_with_cursor["items"][i]["at"]))
                                - datetime.fromisoformat(str(page_with_cursor["items"][i + 1]["at"]))
                            ).total_seconds()
                        )
                    )
                    for i in range(len(page_with_cursor["items"]) - 1)
                )
                if len(page_with_cursor["items"]) > 1
                else 0,
                int(page_with_cursor["window_time_gap_max_seconds"]),
            )
            self.assertEqual(0, int(page_with_cursor["window_time_gap_min_seconds"]))
            self.assertEqual(0, int(page_with_cursor["window_time_gap_count"]))
            self.assertAlmostEqual(
                (
                    sum(
                        abs(
                            (
                                datetime.fromisoformat(str(page_with_cursor["items"][i]["at"]))
                                - datetime.fromisoformat(str(page_with_cursor["items"][i + 1]["at"]))
                            ).total_seconds()
                        )
                        for i in range(len(page_with_cursor["items"]) - 1)
                    )
                    / float(len(page_with_cursor["items"]) - 1)
                )
                if len(page_with_cursor["items"]) > 1
                else 0.0,
                float(page_with_cursor["window_time_gap_avg_seconds"]),
                places=6,
            )
        else:
            self.assertIsNone(page_with_cursor["window_max_id"])
            self.assertIsNone(page_with_cursor["window_min_id"])
            self.assertIsNone(page_with_cursor["window_span"])
            self.assertIsNone(page_with_cursor["dense_window"])
            self.assertIsNone(page_with_cursor["id_gap_count"])
            self.assertIsNone(page_with_cursor["window_density"])
            self.assertIsNone(page_with_cursor["window_newest_at"])
            self.assertIsNone(page_with_cursor["window_oldest_at"])
            self.assertIsNone(page_with_cursor["window_time_span_seconds"])
            self.assertIsNone(page_with_cursor["window_time_desc_order"])
            self.assertIsNone(page_with_cursor["window_time_gap_max_seconds"])
            self.assertIsNone(page_with_cursor["window_time_gap_min_seconds"])
            self.assertIsNone(page_with_cursor["window_time_gap_count"])
            self.assertIsNone(page_with_cursor["window_time_gap_avg_seconds"])
        if page_with_cursor["has_more"]:
            self.assertIsNotNone(page_with_cursor["next_query_string"])
        else:
            self.assertIsNone(page_with_cursor["next_query_string"])

        page_with_total = self.runtime.list_gray_rollout_batch_plan_cache_operations_page(limit=1, include_total=True)
        self.assertEqual("limit=1&include_total=true", page_with_total["query_string"])
        self.assertGreaterEqual(int(page_with_total["total_candidates"]), 3)
        self.assertEqual(
            int(page_with_total["total_candidates"]) - int(page_with_total["returned_items"]),
            int(page_with_total["remaining_candidates"]),
        )
        self.assertEqual(int(page_with_total["items"][0]["id"]), int(page_with_total["window_max_id"]))
        self.assertEqual(int(page_with_total["items"][-1]["id"]), int(page_with_total["window_min_id"]))
        self.assertEqual(
            int(page_with_total["window_max_id"]) - int(page_with_total["window_min_id"]) + 1,
            int(page_with_total["window_span"]),
        )
        self.assertEqual(
            bool(int(page_with_total["window_span"]) == int(page_with_total["returned_items"])),
            bool(page_with_total["dense_window"]),
        )
        self.assertEqual(
            max(0, int(page_with_total["window_span"]) - int(page_with_total["returned_items"])),
            int(page_with_total["id_gap_count"]),
        )
        self.assertEqual(bool(int(page_with_total["id_gap_count"]) == 0), bool(page_with_total["dense_window"]))
        self.assertAlmostEqual(
            float(page_with_total["returned_items"]) / float(page_with_total["window_span"]),
            float(page_with_total["window_density"]),
            places=6,
        )
        self.assertEqual(str(page_with_total["items"][0]["at"]), page_with_total["window_newest_at"])
        self.assertEqual(str(page_with_total["items"][-1]["at"]), page_with_total["window_oldest_at"])
        self.assertEqual(
            max(
                0,
                int(
                    (
                        datetime.fromisoformat(str(page_with_total["items"][0]["at"]))
                        - datetime.fromisoformat(str(page_with_total["items"][-1]["at"]))
                    ).total_seconds()
                ),
            ),
            int(page_with_total["window_time_span_seconds"]),
        )
        self.assertEqual(
            all(
                datetime.fromisoformat(str(page_with_total["items"][i]["at"]))
                >= datetime.fromisoformat(str(page_with_total["items"][i + 1]["at"]))
                for i in range(len(page_with_total["items"]) - 1)
            ),
            bool(page_with_total["window_time_desc_order"]),
        )
        self.assertEqual(
            max(
                abs(
                    int(
                        (
                            datetime.fromisoformat(str(page_with_total["items"][i]["at"]))
                            - datetime.fromisoformat(str(page_with_total["items"][i + 1]["at"]))
                        ).total_seconds()
                    )
                )
                for i in range(len(page_with_total["items"]) - 1)
            )
            if len(page_with_total["items"]) > 1
            else 0,
            int(page_with_total["window_time_gap_max_seconds"]),
        )
        self.assertEqual(0, int(page_with_total["window_time_gap_min_seconds"]))
        self.assertEqual(0, int(page_with_total["window_time_gap_count"]))
        self.assertAlmostEqual(
            (
                sum(
                    abs(
                        (
                            datetime.fromisoformat(str(page_with_total["items"][i]["at"]))
                            - datetime.fromisoformat(str(page_with_total["items"][i + 1]["at"]))
                        ).total_seconds()
                    )
                    for i in range(len(page_with_total["items"]) - 1)
                )
                / float(len(page_with_total["items"]) - 1)
            )
            if len(page_with_total["items"]) > 1
            else 0.0,
            float(page_with_total["window_time_gap_avg_seconds"]),
            places=6,
        )
        self.assertIsNotNone(page_with_total["next_query"])
        self.assertIsNotNone(page_with_total["next_query_string"])
        self.assertIn("include_total=true", page_with_total["next_query_string"])
        self.assertTrue(page_with_total["next_query"]["include_total"])
        with self.assertRaisesRegex(ValueError, "include_total must be a boolean"):
            self.runtime.list_gray_rollout_batch_plan_cache_operations_page(limit=1, include_total="bad")

    def test_gray_rollout_batch_cache_policy_default_max_clear_entries(self) -> None:
        updated = self.runtime.update_gray_rollout_batch_plan_cache_policy({"default_max_clear_entries": 1})
        self.assertEqual(1, updated["default_max_clear_entries"])
        self.assertEqual(1, self.runtime.get_gray_rollout_batch_plan_cache_policy()["default_max_clear_entries"])

        self.runtime.update_gray_rollout_policy(
            {
                "enabled": True,
                "default_percent": 100,
                "overrides": [],
                "dependencies": ["gray_ready"],
                "dependency_graph": {},
            }
        )
        self.runtime.batch_plan_gray_rollout_dependencies_report(
            {
                "idempotency_key": "policy-cache-001",
                "continue_on_error": True,
                "items": [
                    {
                        "tenant_id": "t1",
                        "site_id": "s1",
                        "box_id": "b1",
                        "seed": "policy-cache-seed-001",
                        "dependency_status": {"gray_ready": True},
                    },
                ],
            }
        )
        self.runtime.batch_plan_gray_rollout_dependencies_report(
            {
                "idempotency_key": "policy-cache-002",
                "continue_on_error": True,
                "items": [
                    {
                        "tenant_id": "t2",
                        "site_id": "s2",
                        "box_id": "b2",
                        "seed": "policy-cache-seed-002",
                        "dependency_status": {"gray_ready": True},
                    },
                ],
            }
        )
        with self.assertRaisesRegex(ValueError, "exceeds max_clear_entries=1"):
            self.runtime.clear_gray_rollout_batch_plan_cache({})

        dry_run = self.runtime.clear_gray_rollout_batch_plan_cache({"dry_run": True})
        self.assertEqual(1, dry_run["max_clear_entries"])
        self.assertEqual("policy", dry_run["max_clear_entries_source"])

        cleared = self.runtime.clear_gray_rollout_batch_plan_cache({"max_clear_entries": 2})
        self.assertEqual(2, cleared["max_clear_entries"])
        self.assertEqual("request", cleared["max_clear_entries_source"])
        self.assertEqual(0, cleared["gray_batch_plan_cache_entries"])

        disabled = self.runtime.update_gray_rollout_batch_plan_cache_policy({"default_max_clear_entries": None})
        self.assertIsNone(disabled["default_max_clear_entries"])
        self.assertIsNone(self.runtime.get_gray_rollout_batch_plan_cache_policy()["default_max_clear_entries"])

        with self.assertRaisesRegex(ValueError, "default_max_clear_entries must be a positive integer or null"):
            self.runtime.update_gray_rollout_batch_plan_cache_policy({"default_max_clear_entries": 0})
        with self.assertRaisesRegex(ValueError, "default_max_clear_entries must be a positive integer or null"):
            self.runtime.update_gray_rollout_batch_plan_cache_policy({"default_max_clear_entries": "bad"})

    def test_list_gray_rollout_batch_plan_cache_policy_history(self) -> None:
        self.runtime.update_gray_rollout_batch_plan_cache_policy({"default_max_clear_entries": 3})
        self.runtime.update_gray_rollout_batch_plan_cache_policy({"default_max_clear_entries": 5})
        self.runtime.update_gray_rollout_batch_plan_cache_policy({"default_max_clear_entries": None})

        items = self.runtime.list_gray_rollout_batch_plan_cache_policy_history(limit=2)
        self.assertEqual(2, len(items))
        for item in items:
            self.assertEqual("gray_rollout.plan_batch.cache.policy.update", item["action"])
            self.assertIn("policy", item["details"])
            self.assertIn("default_max_clear_entries", item["details"]["policy"])
        self.assertIsNone(items[0]["details"]["policy"]["default_max_clear_entries"])
        self.assertEqual(5, items[1]["details"]["policy"]["default_max_clear_entries"])

        all_items = self.runtime.list_gray_rollout_batch_plan_cache_policy_history(limit=10)
        self.assertGreaterEqual(len(all_items), 3)
        anchor_id = int(all_items[1]["id"])
        older_items = self.runtime.list_gray_rollout_batch_plan_cache_policy_history(limit=10, before_id=anchor_id)
        self.assertEqual(1, len(older_items))
        self.assertTrue(all(int(item["id"]) < anchor_id for item in older_items))

        with self.assertRaisesRegex(ValueError, "limit must be within \\[1, 200\\]"):
            self.runtime.list_gray_rollout_batch_plan_cache_policy_history(limit=0)
        with self.assertRaisesRegex(ValueError, "limit must be an integer"):
            self.runtime.list_gray_rollout_batch_plan_cache_policy_history(limit="bad")
        with self.assertRaisesRegex(ValueError, "before_id must be a positive integer"):
            self.runtime.list_gray_rollout_batch_plan_cache_policy_history(limit=10, before_id=0)
        with self.assertRaisesRegex(ValueError, "before_id must be a positive integer"):
            self.runtime.list_gray_rollout_batch_plan_cache_policy_history(limit=10, before_id="bad")

        page = self.runtime.list_gray_rollout_batch_plan_cache_policy_history_page(limit=1)
        self.assertEqual(1, page["limit"])
        self.assertIsNone(page["before_id"])
        self.assertEqual("limit=1&include_total=false", page["query_string"])
        self.assertIn("snapshot_at", page)
        datetime.fromisoformat(str(page["snapshot_at"]))
        self.assertEqual(1, page["returned_items"])
        self.assertEqual(int(page["items"][0]["id"]), int(page["window_max_id"]))
        self.assertEqual(int(page["items"][-1]["id"]), int(page["window_min_id"]))
        self.assertEqual(
            int(page["window_max_id"]) - int(page["window_min_id"]) + 1,
            int(page["window_span"]),
        )
        self.assertEqual(bool(int(page["window_span"]) == int(page["returned_items"])), bool(page["dense_window"]))
        self.assertEqual(max(0, int(page["window_span"]) - int(page["returned_items"])), int(page["id_gap_count"]))
        self.assertEqual(bool(int(page["id_gap_count"]) == 0), bool(page["dense_window"]))
        self.assertAlmostEqual(
            float(page["returned_items"]) / float(page["window_span"]),
            float(page["window_density"]),
            places=6,
        )
        self.assertEqual(str(page["items"][0]["at"]), page["window_newest_at"])
        self.assertEqual(str(page["items"][-1]["at"]), page["window_oldest_at"])
        self.assertEqual(
            max(
                0,
                int(
                    (
                        datetime.fromisoformat(str(page["items"][0]["at"]))
                        - datetime.fromisoformat(str(page["items"][-1]["at"]))
                    ).total_seconds()
                ),
            ),
            int(page["window_time_span_seconds"]),
        )
        self.assertEqual(
            all(
                datetime.fromisoformat(str(page["items"][i]["at"]))
                >= datetime.fromisoformat(str(page["items"][i + 1]["at"]))
                for i in range(len(page["items"]) - 1)
            ),
            bool(page["window_time_desc_order"]),
        )
        self.assertEqual(
            max(
                abs(
                    int(
                        (
                            datetime.fromisoformat(str(page["items"][i]["at"]))
                            - datetime.fromisoformat(str(page["items"][i + 1]["at"]))
                        ).total_seconds()
                    )
                )
                for i in range(len(page["items"]) - 1)
            )
            if len(page["items"]) > 1
            else 0,
            int(page["window_time_gap_max_seconds"]),
        )
        self.assertEqual(0, int(page["window_time_gap_min_seconds"]))
        self.assertEqual(0, int(page["window_time_gap_count"]))
        self.assertAlmostEqual(
            (
                sum(
                    abs(
                        (
                            datetime.fromisoformat(str(page["items"][i]["at"]))
                            - datetime.fromisoformat(str(page["items"][i + 1]["at"]))
                        ).total_seconds()
                    )
                    for i in range(len(page["items"]) - 1)
                )
                / float(len(page["items"]) - 1)
            )
            if len(page["items"]) > 1
            else 0.0,
            float(page["window_time_gap_avg_seconds"]),
            places=6,
        )
        self.assertEqual("id_desc", page["order"])
        self.assertIsNone(page["total_candidates"])
        self.assertIsNone(page["remaining_candidates"])
        self.assertTrue(page["has_more"])
        self.assertIsNotNone(page["next_before_id"])
        self.assertIsNotNone(page["next_query"])
        self.assertIsNotNone(page["next_query_string"])
        self.assertIn(f"before_id={page['next_before_id']}", page["next_query_string"])
        self.assertEqual(page["next_before_id"], page["next_query"]["before_id"])
        self.assertFalse(page["next_query"]["include_total"])
        self.assertEqual(1, len(page["items"]))

        page_with_cursor = self.runtime.list_gray_rollout_batch_plan_cache_policy_history_page(
            limit=1,
            before_id=anchor_id,
        )
        self.assertEqual(anchor_id, page_with_cursor["before_id"])
        self.assertEqual(f"limit=1&before_id={anchor_id}&include_total=false", page_with_cursor["query_string"])
        self.assertEqual("id_desc", page_with_cursor["order"])
        self.assertIsNone(page_with_cursor["total_candidates"])
        self.assertIsNone(page_with_cursor["remaining_candidates"])
        if page_with_cursor["items"]:
            self.assertEqual(int(page_with_cursor["items"][0]["id"]), int(page_with_cursor["window_max_id"]))
            self.assertEqual(int(page_with_cursor["items"][-1]["id"]), int(page_with_cursor["window_min_id"]))
            self.assertEqual(
                int(page_with_cursor["window_max_id"]) - int(page_with_cursor["window_min_id"]) + 1,
                int(page_with_cursor["window_span"]),
            )
            self.assertEqual(
                bool(int(page_with_cursor["window_span"]) == int(page_with_cursor["returned_items"])),
                bool(page_with_cursor["dense_window"]),
            )
            self.assertEqual(
                max(0, int(page_with_cursor["window_span"]) - int(page_with_cursor["returned_items"])),
                int(page_with_cursor["id_gap_count"]),
            )
            self.assertEqual(bool(int(page_with_cursor["id_gap_count"]) == 0), bool(page_with_cursor["dense_window"]))
            self.assertAlmostEqual(
                float(page_with_cursor["returned_items"]) / float(page_with_cursor["window_span"]),
                float(page_with_cursor["window_density"]),
                places=6,
            )
            self.assertEqual(str(page_with_cursor["items"][0]["at"]), page_with_cursor["window_newest_at"])
            self.assertEqual(str(page_with_cursor["items"][-1]["at"]), page_with_cursor["window_oldest_at"])
            self.assertEqual(
                max(
                    0,
                    int(
                        (
                            datetime.fromisoformat(str(page_with_cursor["items"][0]["at"]))
                            - datetime.fromisoformat(str(page_with_cursor["items"][-1]["at"]))
                        ).total_seconds()
                    ),
                ),
                int(page_with_cursor["window_time_span_seconds"]),
            )
            self.assertEqual(
                all(
                    datetime.fromisoformat(str(page_with_cursor["items"][i]["at"]))
                    >= datetime.fromisoformat(str(page_with_cursor["items"][i + 1]["at"]))
                    for i in range(len(page_with_cursor["items"]) - 1)
                ),
                bool(page_with_cursor["window_time_desc_order"]),
            )
            self.assertEqual(
                max(
                    abs(
                        int(
                            (
                                datetime.fromisoformat(str(page_with_cursor["items"][i]["at"]))
                                - datetime.fromisoformat(str(page_with_cursor["items"][i + 1]["at"]))
                            ).total_seconds()
                        )
                    )
                    for i in range(len(page_with_cursor["items"]) - 1)
                )
                if len(page_with_cursor["items"]) > 1
                else 0,
                int(page_with_cursor["window_time_gap_max_seconds"]),
            )
            self.assertEqual(0, int(page_with_cursor["window_time_gap_min_seconds"]))
            self.assertEqual(0, int(page_with_cursor["window_time_gap_count"]))
            self.assertAlmostEqual(
                (
                    sum(
                        abs(
                            (
                                datetime.fromisoformat(str(page_with_cursor["items"][i]["at"]))
                                - datetime.fromisoformat(str(page_with_cursor["items"][i + 1]["at"]))
                            ).total_seconds()
                        )
                        for i in range(len(page_with_cursor["items"]) - 1)
                    )
                    / float(len(page_with_cursor["items"]) - 1)
                )
                if len(page_with_cursor["items"]) > 1
                else 0.0,
                float(page_with_cursor["window_time_gap_avg_seconds"]),
                places=6,
            )
        else:
            self.assertIsNone(page_with_cursor["window_max_id"])
            self.assertIsNone(page_with_cursor["window_min_id"])
            self.assertIsNone(page_with_cursor["window_span"])
            self.assertIsNone(page_with_cursor["dense_window"])
            self.assertIsNone(page_with_cursor["id_gap_count"])
            self.assertIsNone(page_with_cursor["window_density"])
            self.assertIsNone(page_with_cursor["window_newest_at"])
            self.assertIsNone(page_with_cursor["window_oldest_at"])
            self.assertIsNone(page_with_cursor["window_time_span_seconds"])
            self.assertIsNone(page_with_cursor["window_time_desc_order"])
            self.assertIsNone(page_with_cursor["window_time_gap_max_seconds"])
            self.assertIsNone(page_with_cursor["window_time_gap_min_seconds"])
            self.assertIsNone(page_with_cursor["window_time_gap_count"])
            self.assertIsNone(page_with_cursor["window_time_gap_avg_seconds"])
        if page_with_cursor["has_more"]:
            self.assertIsNotNone(page_with_cursor["next_query_string"])
        else:
            self.assertIsNone(page_with_cursor["next_query_string"])

        page_with_total = self.runtime.list_gray_rollout_batch_plan_cache_policy_history_page(limit=1, include_total=True)
        self.assertEqual("limit=1&include_total=true", page_with_total["query_string"])
        self.assertGreaterEqual(int(page_with_total["total_candidates"]), 3)
        self.assertEqual(
            int(page_with_total["total_candidates"]) - int(page_with_total["returned_items"]),
            int(page_with_total["remaining_candidates"]),
        )
        self.assertEqual(int(page_with_total["items"][0]["id"]), int(page_with_total["window_max_id"]))
        self.assertEqual(int(page_with_total["items"][-1]["id"]), int(page_with_total["window_min_id"]))
        self.assertEqual(
            int(page_with_total["window_max_id"]) - int(page_with_total["window_min_id"]) + 1,
            int(page_with_total["window_span"]),
        )
        self.assertEqual(
            bool(int(page_with_total["window_span"]) == int(page_with_total["returned_items"])),
            bool(page_with_total["dense_window"]),
        )
        self.assertEqual(
            max(0, int(page_with_total["window_span"]) - int(page_with_total["returned_items"])),
            int(page_with_total["id_gap_count"]),
        )
        self.assertEqual(bool(int(page_with_total["id_gap_count"]) == 0), bool(page_with_total["dense_window"]))
        self.assertAlmostEqual(
            float(page_with_total["returned_items"]) / float(page_with_total["window_span"]),
            float(page_with_total["window_density"]),
            places=6,
        )
        self.assertEqual(str(page_with_total["items"][0]["at"]), page_with_total["window_newest_at"])
        self.assertEqual(str(page_with_total["items"][-1]["at"]), page_with_total["window_oldest_at"])
        self.assertEqual(
            max(
                0,
                int(
                    (
                        datetime.fromisoformat(str(page_with_total["items"][0]["at"]))
                        - datetime.fromisoformat(str(page_with_total["items"][-1]["at"]))
                    ).total_seconds()
                ),
            ),
            int(page_with_total["window_time_span_seconds"]),
        )
        self.assertEqual(
            all(
                datetime.fromisoformat(str(page_with_total["items"][i]["at"]))
                >= datetime.fromisoformat(str(page_with_total["items"][i + 1]["at"]))
                for i in range(len(page_with_total["items"]) - 1)
            ),
            bool(page_with_total["window_time_desc_order"]),
        )
        self.assertEqual(
            max(
                abs(
                    int(
                        (
                            datetime.fromisoformat(str(page_with_total["items"][i]["at"]))
                            - datetime.fromisoformat(str(page_with_total["items"][i + 1]["at"]))
                        ).total_seconds()
                    )
                )
                for i in range(len(page_with_total["items"]) - 1)
            )
            if len(page_with_total["items"]) > 1
            else 0,
            int(page_with_total["window_time_gap_max_seconds"]),
        )
        self.assertEqual(0, int(page_with_total["window_time_gap_min_seconds"]))
        self.assertEqual(0, int(page_with_total["window_time_gap_count"]))
        self.assertAlmostEqual(
            (
                sum(
                    abs(
                        (
                            datetime.fromisoformat(str(page_with_total["items"][i]["at"]))
                            - datetime.fromisoformat(str(page_with_total["items"][i + 1]["at"]))
                        ).total_seconds()
                    )
                    for i in range(len(page_with_total["items"]) - 1)
                )
                / float(len(page_with_total["items"]) - 1)
            )
            if len(page_with_total["items"]) > 1
            else 0.0,
            float(page_with_total["window_time_gap_avg_seconds"]),
            places=6,
        )
        self.assertIsNotNone(page_with_total["next_query"])
        self.assertIsNotNone(page_with_total["next_query_string"])
        self.assertIn("include_total=true", page_with_total["next_query_string"])
        self.assertTrue(page_with_total["next_query"]["include_total"])
        with self.assertRaisesRegex(ValueError, "include_total must be a boolean"):
            self.runtime.list_gray_rollout_batch_plan_cache_policy_history_page(limit=1, include_total="bad")

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
