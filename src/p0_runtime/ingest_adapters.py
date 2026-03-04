from __future__ import annotations

from dataclasses import dataclass

from src.p1_media.gb28181_adapter import normalize_gb28181_source


class UnsupportedProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class IngestAdapter:
    protocol: str
    requires_stream_url: bool = True

    def build_ingest_spec(self, payload: dict) -> dict:
        return {
            "protocol": self.protocol,
            "stream_url": str(payload["stream_url"]),
            "enabled": bool(payload.get("enabled", True)),
        }


@dataclass(frozen=True)
class RtspAdapter(IngestAdapter):
    protocol: str = "rtsp"
    requires_stream_url: bool = True

    def build_ingest_spec(self, payload: dict) -> dict:
        base = super().build_ingest_spec(payload)
        base["transport"] = str(payload.get("transport", "tcp"))
        return base


@dataclass(frozen=True)
class RtmpAdapter(IngestAdapter):
    protocol: str = "rtmp"
    requires_stream_url: bool = True

    def build_ingest_spec(self, payload: dict) -> dict:
        base = super().build_ingest_spec(payload)
        base["app"] = str(payload.get("app", "live"))
        return base


@dataclass(frozen=True)
class OnvifAdapter(IngestAdapter):
    protocol: str = "onvif"
    requires_stream_url: bool = True

    def build_ingest_spec(self, payload: dict) -> dict:
        base = super().build_ingest_spec(payload)
        base["discovery"] = bool(payload.get("discovery", False))
        return base


@dataclass(frozen=True)
class Gb28181Adapter(IngestAdapter):
    protocol: str = "gb28181"
    requires_stream_url: bool = False

    def build_ingest_spec(self, payload: dict) -> dict:
        normalized = normalize_gb28181_source(payload)
        return dict(normalized["ingest_spec"])


def adapter_for(protocol: str) -> IngestAdapter:
    normalized = protocol.strip().lower()
    if normalized == "rtsp":
        return RtspAdapter()
    if normalized == "rtmp":
        return RtmpAdapter()
    if normalized == "onvif":
        return OnvifAdapter()
    if normalized == "gb28181":
        return Gb28181Adapter()

    raise UnsupportedProtocolError(f"unsupported protocol: {protocol}")
