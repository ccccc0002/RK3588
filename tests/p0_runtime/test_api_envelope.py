import unittest

from src.p0_runtime.api_envelope import error_payload, ok_payload


class ApiEnvelopeTests(unittest.TestCase):
    def test_ok_payload_shape(self) -> None:
        payload = ok_payload({"value": 1})
        self.assertTrue(payload["success"])
        self.assertEqual({"value": 1}, payload["data"])
        self.assertIsNone(payload["error"])
        self.assertEqual({}, payload["meta"])

    def test_error_payload_shape(self) -> None:
        payload = error_payload("bad_request", "invalid input", {"field": "role"})
        self.assertFalse(payload["success"])
        self.assertIsNone(payload["data"])
        self.assertEqual("bad_request", payload["error"]["code"])
        self.assertEqual("invalid input", payload["error"]["message"])
        self.assertEqual({"field": "role"}, payload["error"]["details"])
        self.assertEqual({}, payload["meta"])


if __name__ == "__main__":
    unittest.main()
