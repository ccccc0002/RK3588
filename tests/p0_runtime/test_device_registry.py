import unittest
from datetime import datetime, timezone

from src.p0_runtime.runtime import P0Runtime


class P0DeviceRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 3, 3, 8, 0, 0, tzinfo=timezone.utc)
        self.runtime = P0Runtime(webhook_url="https://example.com/hook", webhook_token="token")

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
            }
        )

        listed = self.runtime.list_devices()
        self.assertEqual(1, len(listed))
        self.assertEqual("onvif", listed[0]["protocol"])
        self.assertFalse(listed[0]["enabled"])


if __name__ == "__main__":
    unittest.main()
