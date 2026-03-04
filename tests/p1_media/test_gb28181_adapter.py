import unittest

from src.p1_media.gb28181_adapter import normalize_gb28181_source


class Gb28181AdapterTests(unittest.TestCase):
    def test_normalize_valid_payload(self) -> None:
        raw = {
            "tenant_id": "t1",
            "site_id": "s1",
            "box_id": "b1",
            "device_id": "cam-gb",
            "sip_server": "10.0.0.8",
            "sip_port": 5060,
            "channel_id": "34020000001320000001",
            "transport": "udp",
            "enabled": True,
        }

        normalized = normalize_gb28181_source(raw)

        self.assertEqual("gb28181", normalized["protocol"])
        self.assertEqual("cam-gb", normalized["device_id"])
        self.assertTrue(normalized["enabled"])
        self.assertEqual("udp", normalized["transport"])
        self.assertEqual("10.0.0.8", normalized["ingest_spec"]["sip_server"])
        self.assertEqual(5060, normalized["ingest_spec"]["sip_port"])
        self.assertEqual("34020000001320000001", normalized["ingest_spec"]["channel_id"])
        self.assertEqual(3600, normalized["ingest_spec"]["expires_seconds"])

    def test_normalize_does_not_mutate_input(self) -> None:
        raw = {
            "tenant_id": "t1",
            "site_id": "s1",
            "box_id": "b1",
            "device_id": "cam-gb",
            "sip_server": "10.0.0.8",
            "sip_port": 5060,
            "channel_id": "34020000001320000001",
            "transport": "tcp",
        }
        snapshot = dict(raw)

        _ = normalize_gb28181_source(raw)

        self.assertEqual(snapshot, raw)

    def test_missing_required_field_raises(self) -> None:
        raw = {
            "tenant_id": "t1",
            "site_id": "s1",
            "box_id": "b1",
            "device_id": "cam-gb",
            "sip_server": "10.0.0.8",
            "sip_port": 5060,
            "transport": "udp",
        }

        with self.assertRaises(ValueError) as ctx:
            normalize_gb28181_source(raw)

        self.assertIn("missing required field: channel_id", str(ctx.exception))

    def test_invalid_transport_raises(self) -> None:
        raw = {
            "tenant_id": "t1",
            "site_id": "s1",
            "box_id": "b1",
            "device_id": "cam-gb",
            "sip_server": "10.0.0.8",
            "sip_port": 5060,
            "channel_id": "34020000001320000001",
            "transport": "sctp",
        }

        with self.assertRaises(ValueError) as ctx:
            normalize_gb28181_source(raw)

        self.assertIn("unsupported transport", str(ctx.exception))

    def test_invalid_sip_port_raises(self) -> None:
        raw = {
            "tenant_id": "t1",
            "site_id": "s1",
            "box_id": "b1",
            "device_id": "cam-gb",
            "sip_server": "10.0.0.8",
            "sip_port": 70000,
            "channel_id": "34020000001320000001",
            "transport": "udp",
        }

        with self.assertRaises(ValueError) as ctx:
            normalize_gb28181_source(raw)

        self.assertIn("sip_port out of range", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
