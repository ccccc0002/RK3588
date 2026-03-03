# P0 Ingest Adapter Contract

This document defines adapter-level normalized ingest specs used by runtime registry.

## Common Device Fields

Required fields:
- `tenant_id`
- `site_id`
- `box_id`
- `device_id`
- `protocol`
- `stream_url`

Optional fields:
- `enabled` (default `true`)

## Protocol Adapters

### RTSP
Input extras:
- `transport` (`tcp` default)

Normalized ingest spec:
```json
{
  "protocol": "rtsp",
  "stream_url": "rtsp://...",
  "enabled": true,
  "transport": "tcp"
}
```

### RTMP
Input extras:
- `app` (`live` default)

Normalized ingest spec:
```json
{
  "protocol": "rtmp",
  "stream_url": "rtmp://...",
  "enabled": true,
  "app": "live"
}
```

### ONVIF
Input extras:
- `discovery` (`false` default)

Normalized ingest spec:
```json
{
  "protocol": "onvif",
  "stream_url": "rtsp://...",
  "enabled": true,
  "discovery": false
}
```

## Unsupported Protocol Behavior

Runtime returns validation failure when protocol is not in `rtsp|rtmp|onvif`.
