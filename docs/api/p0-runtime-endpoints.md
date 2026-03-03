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

Default bind address:
- Host: `127.0.0.1`
- Port: `18080`

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
  - 200: `{ "token": "...", "issued_at": "..." }`

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
  - 200: registered record with `ingest_spec`

- `GET /api/v1/devices`
  - 200: `{ "items": [ ... ] }`

### Viewer sessions

- `POST /api/v1/viewer-sessions/{streamId}/join`
  - body: `{ "now": "2026-03-03T08:00:00+00:00" }`
  - 200: `{ "stream_id": "cam-1", "state": "RESUMING", "viewer_count": 1 }`

- `POST /api/v1/viewer-sessions/{streamId}/leave`
  - body: `{ "now": "2026-03-03T08:00:08+00:00" }`
  - 200: `{ "stream_id": "cam-1", "state": "IDLE_PENDING", "viewer_count": 0 }`

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
  - 202 accepted or 409 duplicate

- `POST /api/v1/push/dispatch`
  - body: `{ "now": "2026-03-03T08:00:00+00:00", "limit": 20, "mode": "real|always_success|always_fail" }`
  - 200: `{ "sent": 1, "failed": 0, "processed": 1 }`

### Async push worker

- `POST /api/v1/push/worker/start`
  - body: `{ "interval_ms": 500, "limit": 20, "mode": "real|always_success|always_fail" }`
  - 200: `{ "started": true, "interval_seconds": 0.5, "max_items": 20 }`

- `POST /api/v1/push/worker/stop`
  - 200: `{ "stopped": true }`

- `GET /api/v1/push/worker/status`
  - 200: `{ "running": true, "interval_seconds": 0.5 }`

### Runtime snapshot and metrics

- `GET /api/v1/runtime/snapshot`
  - 200 runtime in-memory snapshot

- `GET /api/v1/metrics`
  - 200 dispatch and worker metrics

## FastAPI Compatibility Layer

File: `src/p0_runtime/fastapi_adapter.py`

- `is_fastapi_available()` checks optional dependency presence
- `create_fastapi_app()` builds a compatibility app when dependencies exist
- If `fastapi/pydantic` are not installed, it raises runtime error by design

## Test Commands

```powershell
python -m unittest discover -s tests -p 'test_*.py'
```
