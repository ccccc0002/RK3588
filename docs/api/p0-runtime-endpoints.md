# P0 Runtime API (Zero Dependency)

This runtime server uses Python standard library only and reuses `p0_core` domain modules.

## Start Server

```powershell
python -m src.p0_runtime.http_server
```

Or use helper script:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-p0-runtime.ps1 -Host 127.0.0.1 -Port 18080
```

SQLite persistence (optional):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-p0-runtime.ps1 `
  -Host 127.0.0.1 `
  -Port 18080 `
  -DbPath .\data\p0-runtime.db
```

Admin bootstrap token (optional, required for issuing `admin` role token):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-p0-runtime.ps1 `
  -Host 127.0.0.1 `
  -Port 18080 `
  -BootstrapToken "change-me"
```

Default bind address:
- Host: `127.0.0.1`
- Port: `18080`

## Response Envelope

All runtime APIs use a unified envelope:

```json
{
  "success": true,
  "data": {},
  "error": null,
  "meta": {}
}
```

Error example:

```json
{
  "success": false,
  "data": null,
  "error": { "code": "forbidden", "message": "action not allowed for current role", "details": {} },
  "meta": {}
}
```

## Auth Guardrails

- `POST /api/v1/auth/token` is open (issues runtime token).
- Supported role values: `viewer`, `operator`, `admin`.
- `admin` token issuance requires `X-Bootstrap-Token` header matching server bootstrap token.
- Other endpoints require `Authorization: Bearer <token>`.
- RBAC actions:
  - Read endpoints: `device:read` or `alert:read`
  - Write endpoints: `device:write`
- Unauthorized/invalid token returns `401`.
- Forbidden action for role returns `403`.

## Worker Modes

- In-process thread worker: runtime-managed via API (`/push/worker/start|stop`)
- Standalone process worker: separate process calling dispatch endpoint

Standalone worker launch:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-p0-push-process-worker.ps1 `
  -BaseUrl http://127.0.0.1:18080 `
  -IntervalMs 500 `
  -Limit 20 `
  -Mode real
```

## Endpoints

### Auth

- `POST /api/v1/auth/token`
  - body: `{ "user_id": "u1", "role": "admin", "now": "2026-03-03T08:00:00+00:00" }`
  - 200: envelope with `{ "token": "...", "issued_at": "..." }`

### Device ingest registry

- `POST /api/v1/devices/register`
  - body:
    ```json
    {
      "tenant_id": "t1",
      "site_id": "s1",
      "box_id": "b1",
      "device_id": "cam-1",
      "protocol": "rtsp",
      "stream_url": "rtsp://10.0.0.2/live",
      "enabled": true,
      "transport": "tcp"
    }
    ```
  - protocol adapters supported: `rtsp`, `rtmp`, `onvif`
  - 200: envelope with registered record and `ingest_spec`

- `GET /api/v1/devices`
  - 200: envelope with `{ "items": [ ... ] }`

### Viewer sessions

- `POST /api/v1/viewer-sessions/{streamId}/join`
  - body: `{ "now": "2026-03-03T08:00:00+00:00" }`
  - 200: envelope with `{ "stream_id": "cam-1", "state": "RESUMING", "viewer_count": 1 }`

- `POST /api/v1/viewer-sessions/{streamId}/leave`
  - body: `{ "now": "2026-03-03T08:00:08+00:00" }`
  - 200: envelope with `{ "stream_id": "cam-1", "state": "IDLE_PENDING", "viewer_count": 0 }`

### Event and push

- `POST /api/v1/events`
  - body:
    ```json
    {
      "now": "2026-03-03T08:00:00+00:00",
      "event": {
        "tenant_id": "t1",
        "site_id": "s1",
        "box_id": "b1",
        "source_id": "cam-1",
        "event_type": "line_crossing",
        "object_id": "p1",
        "payload": { "confidence": 0.88 }
      }
    }
    ```
  - 202 accepted (envelope) or 409 duplicate (envelope)

- `POST /api/v1/push/dispatch`
  - body: `{ "now": "2026-03-03T08:00:00+00:00", "limit": 20, "mode": "real|always_success|always_fail" }`
  - 200: envelope with `{ "sent": 1, "failed": 0, "processed": 1 }`

### Async push worker

- `POST /api/v1/push/worker/start`
  - body: `{ "interval_ms": 500, "limit": 20, "mode": "real|always_success|always_fail" }`
  - 200: envelope with `{ "started": true, "interval_seconds": 0.5, "max_items": 20 }`

- `POST /api/v1/push/worker/stop`
  - 200: envelope with `{ "stopped": true }`

- `GET /api/v1/push/worker/status`
  - 200: envelope with `{ "running": true, "interval_seconds": 0.5 }`

### Runtime snapshot and metrics

- `GET /api/v1/runtime/snapshot`
  - 200 envelope with runtime snapshot

- `GET /api/v1/metrics`
  - 200 envelope with dispatch/worker metrics and storage stats (`storage_enabled`, `storage`)

## FastAPI Compatibility Layer

File: `src/p0_runtime/fastapi_adapter.py`

- `is_fastapi_available()` checks optional dependency presence
- `create_fastapi_app()` builds a compatibility app when dependencies exist
- If `fastapi/pydantic` are not installed, it raises runtime error by design

## Test Commands

```powershell
python -m unittest discover -s tests -p 'test_*.py'
```
