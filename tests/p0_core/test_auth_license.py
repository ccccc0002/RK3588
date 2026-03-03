import unittest
from datetime import datetime, timedelta, timezone

from src.p0_core.auth_license import (
    LicenseSnapshot,
    can_enable_device,
    is_action_allowed,
)


class AuthLicenseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 3, 3, 8, 0, 0, tzinfo=timezone.utc)

    def test_license_expiry_is_enforced_to_second(self) -> None:
        license_ = LicenseSnapshot(
            license_id="lic-1",
            ipc_limit=4,
            enabled_devices=1,
            expires_at=self.now,
        )

        allowed_now, _ = can_enable_device(license_, at=self.now - timedelta(seconds=1))
        denied_after, reason = can_enable_device(license_, at=self.now + timedelta(seconds=1))

        self.assertTrue(allowed_now)
        self.assertFalse(denied_after)
        self.assertEqual("license_expired", reason)

    def test_ipc_limit_is_enforced(self) -> None:
        license_ = LicenseSnapshot(
            license_id="lic-2",
            ipc_limit=2,
            enabled_devices=2,
            expires_at=self.now + timedelta(days=1),
        )

        allowed, reason = can_enable_device(license_, at=self.now)

        self.assertFalse(allowed)
        self.assertEqual("ipc_limit_reached", reason)

    def test_rbac_mapping_allows_expected_action(self) -> None:
        self.assertTrue(is_action_allowed("admin", "license:update"))
        self.assertFalse(is_action_allowed("viewer", "license:update"))


if __name__ == "__main__":
    unittest.main()
