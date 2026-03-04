# P0 Ingest Adapter Contract

This document defines adapter-level normalized ingest specs used by runtime registry.

## Common Device Fields

Required fields:
- `tenant_id`
- `site_id`
- `box_id`
- `device_id`
- `protocol`

Conditional required fields:
- For `rtsp|rtmp|onvif`: `stream_url`
- For `gb28181`: `sip_server`, `sip_port`, `channel_id`, `transport`

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

### GB28181
Input extras:
- `sip_server` (required)
- `sip_port` (required, range 1-65535)
- `channel_id` (required)
- `transport` (required, `udp|tcp`)
- `expires_seconds` (`3600` default, range `60-86400`)

Normalized ingest spec:
```json
{
  "sip_server": "10.0.0.8",
  "sip_port": 5060,
  "channel_id": "34020000001320000001",
  "transport": "udp",
  "expires_seconds": 3600
}
```

## Unsupported Protocol Behavior

Runtime returns validation failure when protocol is not in `rtsp|rtmp|onvif|gb28181`.
