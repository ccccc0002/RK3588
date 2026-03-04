import unittest

from src.p0_runtime.fastapi_adapter import create_fastapi_app, is_fastapi_available


class FastApiAdapterTests(unittest.TestCase):
    def test_create_fastapi_app_behavior(self) -> None:
        available = is_fastapi_available()
        if available:
            app = create_fastapi_app(bootstrap_token="bootstrap")
            paths = {route.path for route in app.routes}
            self.assertIn("/api/v1/runtime/snapshot", paths)
            self.assertIn("/api/v1/auth/token", paths)
            self.assertIn("/api/v1/devices/register", paths)
            self.assertIn("/api/v1/devices/capabilities", paths)
            self.assertIn("/api/v1/devices", paths)
            self.assertIn("/api/v1/algorithms", paths)
            self.assertIn("/api/v1/algorithms/upsert", paths)
            self.assertIn("/api/v1/base-libraries", paths)
            self.assertIn("/api/v1/base-libraries/upsert", paths)
            self.assertIn("/api/v1/base-libraries/mappings", paths)
            self.assertIn("/api/v1/base-libraries/mappings/upsert", paths)
            self.assertIn("/api/v1/base-libraries/mappings/batch-upsert", paths)
            self.assertIn("/api/v1/base-libraries/compatibility/policy", paths)
            self.assertIn("/api/v1/offline-executors", paths)
            self.assertIn("/api/v1/offline-executors/upsert", paths)
            self.assertIn("/api/v1/offline-jobs", paths)
            self.assertIn("/api/v1/offline-jobs/create", paths)
            self.assertIn("/api/v1/offline-jobs/status", paths)
            self.assertIn("/api/v1/offline-jobs/status/batch", paths)
            self.assertIn("/api/v1/runtime/schedule", paths)
            self.assertIn("/api/v1/runtime/telemetry", paths)
            self.assertIn("/api/v1/audit/recent", paths)
            self.assertIn("/api/v1/audit/policy", paths)
            self.assertIn("/api/v1/network/policy", paths)
            self.assertIn("/api/v1/events", paths)
            self.assertIn("/api/v1/push/dispatch", paths)
            self.assertIn("/api/v1/push/worker/start", paths)
            self.assertIn("/api/v1/push/worker/stop", paths)
        else:
            with self.assertRaises(RuntimeError):
                create_fastapi_app()


if __name__ == "__main__":
    unittest.main()
