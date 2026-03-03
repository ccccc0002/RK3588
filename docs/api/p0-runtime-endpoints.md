# P0 Runtime API (Zero Dependency)

This runtime server uses Python standard library only and reuses `p0_core` domain modules.

## Start Server

```powershell
python -m src.p0_runtime.http_server
```

Default bind address:
- Host: `127.0.0.1`
- Port: `18080`

## Endpoints

- `POST /api/v1/auth/token`
  - body: `{ "user_id": "u1", "role": "admin", "now": "2026-03-03T08:00:00+00:00" }`
  - 200: `{ "token": "...", "issued_at": "..." }`

- `POST /api/v1/viewer-sessions/{streamId}/join`
  - body: `{ "now": "2026-03-03T08:00:00+00:00" }`
  - 200: `{ "stream_id": "cam-1", "state": "RESUMING", "viewer_count": 1 }`

- `POST /api/v1/viewer-sessions/{streamId}/leave`
  - body: `{ "now": "2026-03-03T08:00:08+00:00" }`
  - 200: `{ "stream_id": "cam-1", "state": "IDLE_PENDING", "viewer_count": 0 }`

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

- `GET /api/v1/runtime/snapshot`
  - 200 runtime in-memory snapshot

## Test Commands

```powershell
python -m unittest tests/p0_runtime/test_runtime.py tests/p0_runtime/test_http_api.py
python -m unittest discover -s tests -p 'test_*.py'
```
