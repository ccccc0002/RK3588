import unittest
from datetime import datetime, timezone

from src.p0_runtime.ingest_adapters import UnsupportedProtocolError, adapter_for
from src.p0_runtime.runtime import P0Runtime


class P0DeviceRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 3, 3, 8, 0, 0, tzinfo=timezone.utc)
        self.runtime = P0Runtime(webhook_url="https://example.com/hook", webhook_token="token")

    def test_adapter_selection(self) -> None:
        self.assertEqual("rtsp", adapter_for("rtsp").protocol)
        self.assertEqual("rtmp", adapter_for("RTMP").protocol)
        self.assertEqual("onvif", adapter_for("onvif").protocol)

    def test_unknown_protocol_raises(self) -> None:
        with self.assertRaises(UnsupportedProtocolError):
            adapter_for("gb28181")

    def test_register_and_list_devices(self) -> None:
        reg = self.runtime.register_device(
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

        self.assertEqual("cam-1", reg["device_id"])
        self.assertIn("ingest_spec", reg)
        self.assertEqual("tcp", reg["ingest_spec"]["transport"])

        listed = self.runtime.list_devices()
        self.assertEqual(1, len(listed))
        self.assertEqual("rtsp", listed[0]["protocol"])

    def test_register_same_device_updates_record(self) -> None:
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
        self.runtime.register_device(
            {
                "tenant_id": "t1",
                "site_id": "s1",
                "box_id": "b1",
                "device_id": "cam-1",
                "protocol": "onvif",
                "stream_url": "rtsp://10.0.0.3/live",
                "enabled": False,
                "discovery": True,
            }
        )

        listed = self.runtime.list_devices()
        self.assertEqual(1, len(listed))
        self.assertEqual("onvif", listed[0]["protocol"])
        self.assertFalse(listed[0]["enabled"])
        self.assertTrue(listed[0]["ingest_spec"]["discovery"])


if __name__ == "__main__":
    unittest.main()
