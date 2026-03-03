import unittest

from src.p0_runtime.fastapi_adapter import create_fastapi_app, is_fastapi_available


class FastApiAdapterTests(unittest.TestCase):
    def test_create_fastapi_app_behavior(self) -> None:
        available = is_fastapi_available()
        if available:
            app = create_fastapi_app()
            paths = {route.path for route in app.routes}
            self.assertIn("/api/v1/runtime/snapshot", paths)
            self.assertIn("/api/v1/auth/token", paths)
        else:
            with self.assertRaises(RuntimeError):
                create_fastapi_app()


if __name__ == "__main__":
    unittest.main()
