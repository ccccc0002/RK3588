from __future__ import annotations

from dataclasses import dataclass


class UnsupportedProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class IngestAdapter:
    protocol: str

    def build_ingest_spec(self, payload: dict) -> dict:
        return {
            "protocol": self.protocol,
            "stream_url": str(payload["stream_url"]),
            "enabled": bool(payload.get("enabled", True)),
        }


@dataclass(frozen=True)
class RtspAdapter(IngestAdapter):
    protocol: str = "rtsp"

    def build_ingest_spec(self, payload: dict) -> dict:
        base = super().build_ingest_spec(payload)
        base["transport"] = str(payload.get("transport", "tcp"))
        return base


@dataclass(frozen=True)
class RtmpAdapter(IngestAdapter):
    protocol: str = "rtmp"

    def build_ingest_spec(self, payload: dict) -> dict:
        base = super().build_ingest_spec(payload)
        base["app"] = str(payload.get("app", "live"))
        return base


@dataclass(frozen=True)
class OnvifAdapter(IngestAdapter):
    protocol: str = "onvif"

    def build_ingest_spec(self, payload: dict) -> dict:
        base = super().build_ingest_spec(payload)
        base["discovery"] = bool(payload.get("discovery", False))
        return base


def adapter_for(protocol: str) -> IngestAdapter:
    normalized = protocol.strip().lower()
    if normalized == "rtsp":
        return RtspAdapter()
    if normalized == "rtmp":
        return RtmpAdapter()
    if normalized == "onvif":
        return OnvifAdapter()

    raise UnsupportedProtocolError(f"unsupported protocol: {protocol}")
