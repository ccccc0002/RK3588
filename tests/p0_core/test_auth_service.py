import unittest
from datetime import datetime, timedelta, timezone

from src.p0_core.auth_service import issue_token, verify_token


class AuthServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.secret = "rk3588-secret"
        self.now = datetime(2026, 3, 3, 8, 0, 0, tzinfo=timezone.utc)

    def test_issue_and_verify_token(self) -> None:
        token = issue_token(user_id="u1", role="admin", issued_at=self.now, secret=self.secret, ttl_seconds=60)

        ok, payload = verify_token(token, at=self.now + timedelta(seconds=30), secret=self.secret)

        self.assertTrue(ok)
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual("u1", payload.user_id)
        self.assertEqual("admin", payload.role)

    def test_expired_token_is_rejected(self) -> None:
        token = issue_token(user_id="u2", role="viewer", issued_at=self.now, secret=self.secret, ttl_seconds=10)

        ok, payload = verify_token(token, at=self.now + timedelta(seconds=11), secret=self.secret)

        self.assertFalse(ok)
        self.assertIsNone(payload)

    def test_signature_tampering_is_rejected(self) -> None:
        token = issue_token(user_id="u3", role="operator", issued_at=self.now, secret=self.secret, ttl_seconds=60)
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")

        ok, _ = verify_token(tampered, at=self.now + timedelta(seconds=5), secret=self.secret)

        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
