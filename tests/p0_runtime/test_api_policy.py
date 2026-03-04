import unittest

from src.p0_runtime.api_policy import is_supported_role, required_get_action, required_post_action


class ApiPolicyTests(unittest.TestCase):
    def test_supported_roles(self) -> None:
        self.assertTrue(is_supported_role("admin"))
        self.assertTrue(is_supported_role("operator"))
        self.assertTrue(is_supported_role("viewer"))
        self.assertFalse(is_supported_role("guest"))

    def test_required_get_action_mapping(self) -> None:
        self.assertEqual("alert:read", required_get_action("/api/v1/runtime/snapshot"))
        self.assertEqual("alert:read", required_get_action("/api/v1/metrics"))
        self.assertEqual("device:read", required_get_action("/api/v1/devices"))
        self.assertEqual("device:read", required_get_action("/api/v1/push/worker/status"))
        self.assertIsNone(required_get_action("/api/v1/unknown"))

    def test_required_post_action_mapping(self) -> None:
        self.assertEqual("device:write", required_post_action("/api/v1/devices/register"))
        self.assertEqual("device:write", required_post_action("/api/v1/devices/capabilities"))
        self.assertEqual("device:read", required_post_action("/api/v1/runtime/schedule"))
        self.assertEqual("device:read", required_post_action("/api/v1/viewer-sessions/cam-1/join"))
        self.assertEqual("device:read", required_post_action("/api/v1/viewer-sessions/cam-1/leave"))
        self.assertEqual("device:write", required_post_action("/api/v1/events"))
        self.assertEqual("device:write", required_post_action("/api/v1/push/dispatch"))
        self.assertEqual("device:write", required_post_action("/api/v1/push/worker/start"))
        self.assertEqual("device:write", required_post_action("/api/v1/push/worker/stop"))
        self.assertIsNone(required_post_action("/api/v1/unknown"))


if __name__ == "__main__":
    unittest.main()
