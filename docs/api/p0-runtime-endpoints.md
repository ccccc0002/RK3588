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
      "capabilities": { "ocr": false, "face": false },
      "transport": "tcp"
    }
    ```
  - protocol adapters supported: `rtsp`, `rtmp`, `onvif`, `gb28181`
  - field rule:
    - `stream_url` is required for `rtsp|rtmp|onvif`
    - `gb28181` requires `sip_server`, `sip_port`, `channel_id`, `transport`
  - 200: envelope with registered record and `ingest_spec`

- `POST /api/v1/devices/capabilities`
  - body:
    ```json
    {
      "tenant_id": "t1",
      "site_id": "s1",
      "box_id": "b1",
      "device_id": "cam-1",
      "capabilities": { "ocr": true, "face": true }
    }
    ```
  - 200: envelope with updated device record (`capabilities` reflected in response)

GB28181 example:

```json
{
  "tenant_id": "t1",
  "site_id": "s1",
  "box_id": "b1",
  "device_id": "cam-gb-1",
  "protocol": "gb28181",
  "sip_server": "10.0.0.8",
  "sip_port": 5060,
  "channel_id": "34020000001320000001",
  "transport": "udp",
  "enabled": true
}
```

- `GET /api/v1/devices`
  - 200: envelope with `{ "items": [ ... ] }`

### Algorithm Repository

- `GET /api/v1/algorithms`
  - RBAC: requires `device:read`
  - 200 envelope with `{ "items": [ { "algorithm_id": "...", "version": "...", "status": "draft|active|disabled", "capabilities": [], "updated_at": "..." } ] }`

- `POST /api/v1/algorithms/upsert`
  - RBAC: requires `device:write`
  - body:
    ```json
    {
      "algorithm_id": "face-detector",
      "version": "1.0.0",
      "status": "active",
      "capabilities": ["face"]
    }
    ```
  - 200 envelope with upserted algorithm record

### Base Capability Libraries

- `GET /api/v1/base-libraries`
  - RBAC: requires `device:read`
  - 200 envelope with `{ "items": [ { "library_id": "...", "version": "...", "capability": "...", "status": "draft|active|disabled", "metadata": {}, "updated_at": "..." } ] }`

- `POST /api/v1/base-libraries/upsert`
  - RBAC: requires `device:write`
  - body:
    ```json
    {
      "library_id": "lib-face-core",
      "version": "2026.03",
      "capability": "face",
      "status": "active",
      "metadata": { "vendor": "rk" }
    }
    ```
  - 200 envelope with upserted base library record

- `GET /api/v1/base-libraries/mappings`
  - RBAC: requires `device:read`
  - 200 envelope with `{ "items": [ { "tenant_id": "...", "site_id": "...", "box_id": "...", "device_id": "...", "capability": "...", "library_id": "...", "library_version": "...", "updated_at": "..." } ] }`

- `POST /api/v1/base-libraries/mappings/upsert`
  - RBAC: requires `device:write`
  - body:
    ```json
    {
      "tenant_id": "t1",
      "site_id": "s1",
      "box_id": "b1",
      "device_id": "cam-1",
      "capability": "face",
      "library_id": "lib-face-core",
      "library_version": "2026.03"
    }
    ```
  - 200 envelope with upserted mapping record
  - validation: target device must exist, referenced base library must exist and be `active`

- `POST /api/v1/base-libraries/mappings/batch-upsert`
  - RBAC: requires `device:write`
  - body:
    ```json
    {
      "items": [
        {
          "tenant_id": "t1",
          "site_id": "s1",
          "box_id": "b1",
          "device_id": "cam-1",
          "capability": "face",
          "library_id": "lib-face-core",
          "library_version": "2026.03"
        }
      ]
    }
    ```
  - 200 envelope with `{ "items": [ ...BaseLibraryMappingRecord ] }`
  - validation: each item follows single upsert validation rules

- `GET /api/v1/base-libraries/compatibility/policy`
  - RBAC: requires `device:read`
  - 200 envelope with compatibility policy:
    - `enforce_capability_match`
    - `required_status`
    - `version_regex_by_capability`
    - `semver_range_by_capability` (optional semantic min/max per capability)

- `POST /api/v1/base-libraries/compatibility/policy`
  - RBAC: requires `device:write`
  - body:
    ```json
    {
      "enforce_capability_match": true,
      "required_status": "active",
      "version_regex_by_capability": { "face": "^2026\\." },
      "semver_range_by_capability": {
        "face": { "min": "1.0.0", "max": "2.0.0" }
      }
    }
    ```
  - 200 envelope with updated compatibility policy

### Offline Executors

- `GET /api/v1/offline-executors`
  - RBAC: requires `device:read`
  - 200 envelope with `{ "items": [ { "executor_id": "...", "endpoint": "http://...", "status": "active|drain|disabled", "capabilities": [], "last_heartbeat_at": "...|''", "health_state": "healthy|unknown|stale", "updated_at": "..." } ] }`

- `POST /api/v1/offline-executors/upsert`
  - RBAC: requires `device:write`
  - body:
    ```json
    {
      "executor_id": "exec-1",
      "endpoint": "http://executor.local:9001",
      "status": "active",
      "capabilities": ["face"],
      "last_heartbeat_at": "2026-03-03T08:00:00+00:00"
    }
    ```
  - 200 envelope with upserted executor record

- `POST /api/v1/offline-executors/heartbeat`
  - RBAC: requires `device:write`
  - body:
    ```json
    {
      "executor_id": "exec-1",
      "now": "2026-03-03T08:01:00+00:00"
    }
    ```
  - 200 envelope with updated executor heartbeat fields (`last_heartbeat_at`, `health_state=healthy`)

### Offline Analysis Jobs

- `GET /api/v1/offline-jobs`
  - RBAC: requires `device:read`
  - 200 envelope with `{ "items": [ { "job_id": "...", "source_scope": {}, "algorithm_id": "...", "algorithm_version": "...", "status": "queued|running|succeeded|failed|canceled", "result_ref": "", "error_reason": "", "created_at": "...", "updated_at": "..." } ] }`

- `POST /api/v1/offline-jobs/create`
  - RBAC: requires `device:write`
  - body:
    ```json
    {
      "job_id": "job-001",
      "source_scope": { "tenant_id": "t1", "site_id": "s1" },
      "algorithm_id": "face-detector",
      "algorithm_version": "1.0.0",
      "now": "2026-03-03T08:00:00+00:00"
    }
    ```
  - 200 envelope with created job
  - created job includes:
    - `executor_id` (auto-selected from active executor pool with health-aware preference: `healthy`/`unknown` before `stale`, or explicitly set by request)
    - lease fields initialized as empty string: `lease_agent_id`, `lease_token`, `lease_expires_at`, `lease_updated_at`
  - validation: referenced algorithm must exist and be `active`

- `POST /api/v1/offline-jobs/status`
  - RBAC: requires `device:write`
  - body:
    ```json
    {
      "job_id": "job-001",
      "status": "running",
      "now": "2026-03-03T08:00:05+00:00"
    }
    ```
  - 200 envelope with updated job
  - transition rules:
    - `queued -> queued|running|failed|canceled`
    - `running -> running|succeeded|failed|canceled`
    - terminal statuses (`succeeded|failed|canceled`) are immutable

- `POST /api/v1/offline-jobs/status/batch`
  - RBAC: requires `device:write`
  - body:
    ```json
    {
      "items": [
        { "job_id": "job-001", "status": "running" },
        { "job_id": "job-002", "status": "running" }
      ]
    }
    ```
  - 200 envelope with `{ "items": [ ...OfflineJobRecord ] }`
  - validation: each item follows single status-update transition rules

### Edge Agents

- `GET /api/v1/edge-agents`
  - RBAC: requires `device:read`
  - 200 envelope with `{ "items": [ { "agent_id": "...", "tenant_id": "...", "site_id": "...", "box_id": "...", "endpoint": "http://...", "status": "active|drain|disabled", "capabilities": [], "last_heartbeat_at": "...|''", "health_state": "healthy|unknown|stale", "updated_at": "..." } ] }`

- `POST /api/v1/edge-agents/register`
  - RBAC: requires `device:write`
  - body:
    ```json
    {
      "agent_id": "edge-agent-1",
      "tenant_id": "t1",
      "site_id": "s1",
      "box_id": "b1",
      "endpoint": "http://edge-agent.local:9501",
      "status": "active",
      "capabilities": ["sync", "rollout"]
    }
    ```
  - 200 envelope with registered edge-agent record

- `POST /api/v1/edge-agents/heartbeat`
  - RBAC: requires `device:write`
  - body:
    ```json
    {
      "agent_id": "edge-agent-1",
      "now": "2026-03-04T13:00:00+00:00"
    }
    ```
  - 200 envelope with heartbeat-updated edge-agent record (`health_state=healthy`)

- `POST /api/v1/edge-agents/offline-jobs/lease`
  - RBAC: requires `device:write`
  - body:
    ```json
    {
      "agent_id": "edge-agent-1",
      "lease_seconds": 120,
      "now": "2026-03-04T14:30:00+00:00"
    }
    ```
  - 200 envelope with lease result:
    - `leased=true`: returns `job` object and writes lease fields on that offline job:
      - `lease_agent_id`
      - `lease_token`
      - `lease_expires_at`
      - `lease_updated_at`
    - `leased=false`: returns `"job": null` when no queued scope-matched job is available
  - selection baseline:
    - edge agent must be `active` and not `stale`
    - only `queued` offline jobs are eligible
    - only jobs with matching `source_scope` tenant/site/box are eligible
    - active unexpired leases block other agents from taking the same job

- `POST /api/v1/edge-agents/offline-jobs/lease/renew`
  - RBAC: requires `device:write`
  - body:
    ```json
    {
      "agent_id": "edge-agent-1",
      "job_id": "job-001",
      "lease_token": "abcd1234",
      "lease_seconds": 180,
      "now": "2026-03-04T14:31:00+00:00"
    }
    ```
  - 200 envelope with renewed offline-job record
  - validation baseline:
    - edge agent must exist, be `active`, and not `stale`
    - job must have an unexpired lease owned by the same `agent_id`
    - `lease_token` must match current job lease token
  - effect:
    - extends `lease_expires_at`
    - refreshes `lease_updated_at`

- `POST /api/v1/edge-agents/offline-jobs/lease/start`
  - RBAC: requires `device:write`
  - body:
    ```json
    {
      "agent_id": "edge-agent-1",
      "job_id": "job-001",
      "lease_token": "abcd1234",
      "now": "2026-03-04T14:31:30+00:00"
    }
    ```
  - 200 envelope with updated offline-job record
  - validation baseline:
    - edge agent must exist, be `active`, and not `stale`
    - job must have an unexpired lease owned by the same `agent_id`
    - `lease_token` must match current job lease token
    - job status must be `queued` or `running`
  - effect:
    - updates job `status` to `running`
    - refreshes `lease_updated_at`

- `POST /api/v1/edge-agents/offline-jobs/lease/release`
  - RBAC: requires `device:write`
  - body:
    ```json
    {
      "agent_id": "edge-agent-1",
      "job_id": "job-001",
      "lease_token": "abcd1234",
      "now": "2026-03-04T14:32:00+00:00"
    }
    ```
  - 200 envelope with updated offline-job record
  - validation baseline:
    - edge agent must exist, be `active`, and not `stale`
    - job must have an unexpired lease owned by the same `agent_id`
    - `lease_token` must match current job lease token
  - effect:
    - clears `lease_agent_id`, `lease_token`, `lease_expires_at`
    - updates `lease_updated_at`

- `POST /api/v1/edge-agents/offline-jobs/lease/complete`
  - RBAC: requires `device:write`
  - body:
    ```json
    {
      "agent_id": "edge-agent-1",
      "job_id": "job-001",
      "lease_token": "abcd1234",
      "status": "succeeded",
      "result_ref": "s3://result/job-001.json",
      "error_reason": "",
      "now": "2026-03-04T14:33:00+00:00"
    }
    ```
  - 200 envelope with completed offline-job record
  - validation baseline:
    - edge agent must exist, be `active`, and not `stale`
    - job must have an unexpired lease owned by the same `agent_id`
    - `lease_token` must match current job lease token
    - completion status must be one of `succeeded|failed|canceled`
    - job status must be `queued` or `running`
  - effect:
    - applies terminal job status and optional `result_ref` / `error_reason`
    - clears `lease_agent_id`, `lease_token`, `lease_expires_at`

### Offline Sync Cursor

- `GET /api/v1/offline-sync/cursors`
  - RBAC: requires `device:read`
  - 200 envelope with `{ "items": [ { "tenant_id": "...", "site_id": "...", "box_id": "...", "cursor": "...", "version": 1, "updated_at": "..." } ] }`

- `POST /api/v1/offline-sync/cursors/upsert`
  - RBAC: requires `device:write`
  - body:
    ```json
    {
      "tenant_id": "t1",
      "site_id": "s1",
      "box_id": "b1",
      "cursor": "evt-300",
      "expected_version": 1
    }
    ```
  - 200 envelope with upserted cursor record (version auto-increments)
  - conflict behavior: if `expected_version` does not match current version, returns `400 bad_request`

### Offline Sync Stream Cursor

- `GET /api/v1/offline-sync/streams`
  - RBAC: requires `device:read`
  - 200 envelope with `{ "items": [ { "tenant_id": "...", "site_id": "...", "box_id": "...", "stream_id": "...", "cursor": "...", "version": 1, "updated_at": "..." } ] }`

- `POST /api/v1/offline-sync/streams/upsert`
  - RBAC: requires `device:write`
  - body:
    ```json
    {
      "tenant_id": "t1",
      "site_id": "s1",
      "box_id": "b1",
      "stream_id": "cam-1",
      "cursor": "evt-s300",
      "expected_version": 1
    }
    ```
  - 200 envelope with upserted stream cursor record (version auto-increments)
  - conflict behavior: if `expected_version` does not match current stream cursor version, returns `400 bad_request`

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
  - when network policy allowlist is enforced, disallowed webhook targets are short-circuited to dead-letter on first dispatch attempt (no retry backoff)

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
  - includes gray batch idempotency cache quick-view fields:
    - `gray_batch_plan_cache_entries`
    - `gray_batch_plan_cache_hits`
    - `gray_batch_plan_cache_misses`
    - `gray_batch_plan_cache_conflicts`
    - `gray_batch_plan_cache_evicted_expired`
    - `gray_batch_plan_cache_evicted_overflow`
    - `gray_batch_plan_cache_last_minute_requests`
    - `gray_batch_plan_cache_last_minute_hits`
    - `gray_batch_plan_cache_last_minute_misses`
    - `gray_batch_plan_cache_last_minute_conflicts`
    - `gray_batch_plan_cache_last_minute_hit_rate_percent`
    - cache clear policy observability:
      - `gray_batch_cache_policy_default_max_clear_entries` (`null` means disabled)
      - `gray_batch_cache_policy_enabled`

- `GET /api/v1/metrics`
  - 200 envelope with dispatch/worker metrics and storage stats (`storage_enabled`, `storage`)
  - includes counts for `algorithm_count`, `base_library_count`, `base_library_mapping_count`, `offline_executor_count`, `offline_job_count`
  - includes gray batch idempotency cache observability:
    - `gray_batch_plan_cache_entries`
    - `gray_batch_plan_cache_hits`
    - `gray_batch_plan_cache_misses`
    - `gray_batch_plan_cache_conflicts`
    - `gray_batch_plan_cache_evicted_expired`
    - `gray_batch_plan_cache_evicted_overflow`
    - `gray_batch_plan_cache_last_minute_requests`
    - `gray_batch_plan_cache_last_minute_hits`
    - `gray_batch_plan_cache_last_minute_misses`
    - `gray_batch_plan_cache_last_minute_conflicts`
    - `gray_batch_plan_cache_last_minute_hit_rate_percent` (`hits/(hits+misses)`, integer percent in `0..100`)
    - cache clear policy observability:
      - `gray_batch_cache_policy_default_max_clear_entries` (`null` means disabled)
      - `gray_batch_cache_policy_enabled`

- `POST /api/v1/runtime/schedule`
  - body: `{ "budget": 10.0 }`
  - 200 envelope with capability-aware schedule:
    - `degraded`
    - `total_cost`
    - `streams[]` with `device_id`, `sample_fps`, `estimated_cost`
  - scheduler input `fps_in` comes from latest runtime telemetry when available, otherwise falls back to default `8.0`

- `GET /api/v1/runtime/telemetry`
  - RBAC: requires `device:read`
  - 200 envelope with `{ "items": [ { "tenant_id": "...", "site_id": "...", "box_id": "...", "device_id": "...", "fps_in": 12.0, "updated_at": "..." } ] }`

- `POST /api/v1/runtime/telemetry`
  - RBAC: requires `device:write`
  - body:
    ```json
    {
      "tenant_id": "t1",
      "site_id": "s1",
      "box_id": "b1",
      "device_id": "cam-1",
      "fps_in": 12.0,
      "now": "2026-03-03T08:00:00+00:00"
    }
    ```
  - 200 envelope with updated telemetry record

### Audit

- `GET /api/v1/audit/recent?limit=20`
  - RBAC: requires `device:write` (`operator`/`admin` allowed, `viewer` forbidden)
  - query params (optional):
    - `limit` (default `20`, valid range `1..200`)
    - `before_id` (positive integer audit id, returns records with `id < before_id`)
    - `include_total` (`true|false`, default `false`; when `true`, includes `total_candidates`)
  - 200 envelope:
    - `items[]` audit records
    - `limit`, `before_id` (request cursor echo, nullable), `query_string` (normalized current-page query string)
    - `returned_items`, `window_max_id`, `window_min_id`, `window_span`, `dense_window`, `id_gap_count`, `window_density`, `window_newest_at`, `window_oldest_at`, `snapshot_at`, `order` (`id_desc`)
    - `window_span` = `window_max_id - window_min_id + 1` when page has items; otherwise `null`
    - `dense_window` = whether `window_span == returned_items` when page has items; otherwise `null`
    - `id_gap_count` = `window_span - returned_items` (non-negative) when page has items; otherwise `null`
    - `window_density` = `returned_items / window_span` (rounded to 6 decimals) when page has items; otherwise `null`
    - `window_newest_at`/`window_oldest_at` = current page first/last record `at` timestamps; `null` when page is empty
    - `has_more`, `next_before_id` (`null` when no next page)
    - `next_query` (`null` when no next page; otherwise `{limit,before_id,include_total}`)
    - `next_query_string` (`null` when no next page; otherwise `limit=...&before_id=...&include_total=...`)
    - `total_candidates` (`null` when `include_total=false`)
    - `remaining_candidates` (`total_candidates-returned_items`; `null` when `include_total=false`)
  - validation:
    - `limit` must be integer within `[1, 200]`
    - `before_id` must be a positive integer when provided
    - `include_total` must be boolean-like (`true/false/1/0/yes/no/on/off`)

- `GET /api/v1/audit/policy`
  - RBAC: requires `device:read`
  - 200 envelope with current retention policy:
    - `max_records`

- `POST /api/v1/audit/policy`
  - RBAC: requires `device:write`
  - body:
    ```json
    {
      "max_records": 2000
    }
    ```
  - 200 envelope with updated policy
  - effect: both in-memory and persisted audit records are pruned to `max_records`

### Network Policy

- `GET /api/v1/network/policy`
  - RBAC: requires `device:read`
  - 200 envelope with current policy:
    - `enforce_allowlist`
    - `webhook_allowlist`

- `POST /api/v1/network/policy`
  - RBAC: requires `device:write`
  - body:
    ```json
    {
      "enforce_allowlist": true,
      "webhook_allowlist": ["https://hooks.example.com", "http://10.0.0.5:8080"]
    }
    ```
  - 200 envelope with updated policy
  - effect: if `enforce_allowlist=true`, queued push tasks whose `target_url` does not match any prefix in `webhook_allowlist` are marked failed and moved directly to dead-letter

### Gray Rollout

- `GET /api/v1/gray-rollout/policy`
  - RBAC: requires `device:read`
  - 200 envelope with policy:
    - `enabled`
    - `default_percent` (0-100)
    - `dependencies[]` (required dependency keys that must be ready before rollout can enable)
    - `dependency_graph{}` (optional DAG where key depends on listed prerequisite keys)
    - `overrides[]` with `tenant_id/site_id/box_id/percent`

- `POST /api/v1/gray-rollout/policy`
  - RBAC: requires `device:write`
  - body:
    ```json
    {
      "enabled": true,
      "default_percent": 10,
      "dependencies": ["gray_ready"],
      "dependency_graph": {
        "gray_ready": ["edge_sync_ready"],
        "edge_sync_ready": ["base_library_ready"]
      },
      "overrides": [
        { "tenant_id": "t1", "site_id": "s1", "box_id": "b1", "percent": 100 }
      ]
    }
    ```
  - 200 envelope with updated policy

- `POST /api/v1/gray-rollout/evaluate`
  - RBAC: requires `device:read`
  - body:
    ```json
    {
      "tenant_id": "t1",
      "site_id": "s1",
      "box_id": "b1",
      "seed": "fixed-seed-001",
      "dependency_status": {
        "gray_ready": true,
        "edge_sync_ready": true,
        "base_library_ready": false
      }
    }
    ```
  - 200 envelope with deterministic decision:
    - `percent`, `bucket`, `enabled`
    - `blocked_by[]` (dependency keys that are not ready, including transitive prerequisites from `dependency_graph`)
  - evaluation rule: `enabled=true` only when policy is enabled and `bucket <= percent`
  - dependency rule: rollout is disabled when any root dependency or graph prerequisite is absent/false in `dependency_status`, and each missing key appears in `blocked_by`

- `POST /api/v1/gray-rollout/plan`
  - RBAC: requires `device:read`
  - body:
    ```json
    {
      "tenant_id": "t1",
      "site_id": "s1",
      "box_id": "b1",
      "seed": "fixed-seed-001",
      "dependency_status": {
        "gray_ready": true,
        "edge_sync_ready": true,
        "base_library_ready": false
      }
    }
    ```
  - 200 envelope with dependency execution planning:
    - `dependencies[]` root dependency keys from policy
    - `execution_order[]` topological order (prerequisites first)
    - `nodes[]` per-dependency readiness details (`dependency`, `prerequisites[]`, `ready`, `blocked_by[]`)
    - `blocked_by[]`, `missing_status[]`, `percent`, `bucket`, `enabled`
  - planning rule: `execution_order[]` is deterministic and derived from policy `dependencies + dependency_graph`
  - status rule: keys absent from request `dependency_status` are reported in `missing_status[]`
  - enablement rule: same as evaluate endpoint, `enabled=true` only when rollout percent hit and all planned dependencies are ready

- `POST /api/v1/gray-rollout/plan/batch`
  - RBAC: requires `device:read`
  - body:
    ```json
    {
      "idempotency_key": "plan-batch-001",
      "cache_ttl_seconds": 300,
      "continue_on_error": true,
      "start_index": 0,
      "max_errors": 2,
      "items": [
        {
          "tenant_id": "t1",
          "site_id": "s1",
          "box_id": "b1",
          "seed": "fixed-seed-001",
          "dependency_status": {
            "gray_ready": true,
            "edge_sync_ready": true
          }
        },
        {
          "tenant_id": "t2",
          "site_id": "s2",
          "box_id": "b2",
          "seed": "fixed-seed-002",
          "dependency_status": {
            "gray_ready": true,
            "edge_sync_ready": true,
            "base_library_ready": true
          }
        }
      ]
    }
    ```
  - 200 envelope:
    - `items[]` list of successful per-scope plan results
    - `errors[]` list of item-level errors with `index` and `error`
    - `continue_on_error`, `start_index`, `next_start_index`, `applied_range[]`, `retry_hint{}`, `max_errors`
    - `total`, `processed_count`, `success_count`, `error_count`, `failed_indices[]`, `stopped_early`, `duration_ms`
    - when `idempotency_key` is provided: `idempotency_key`, `cache_hit`, `cache_key`, `cache_expires_at`
  - batch rule:
    - default (`continue_on_error=false`): any invalid item fails entire request with `400` (`items[i]: ...`)
    - tolerant mode (`continue_on_error=true`): request returns `200` with partial successes in `items[]` and failures in `errors[]`
  - resume rule:
    - `errors[].index` and `failed_indices[]` are absolute indices offset by request `start_index`
    - when early stop occurs, `next_start_index` points to the next unprocessed item index for resume
    - `applied_range=[start_index, start_index+processed_count)` marks the absolute index window processed in current call
    - `retry_hint` includes `should_retry`, `resume_from`, `remaining_items`, and `failed_indices[]` for client resume logic
  - early-stop rule: when `max_errors` is provided in tolerant mode, processing stops once accumulated item errors reach `max_errors`
  - idempotency rule:
    - when `idempotency_key` is present, server caches successful batch report payload for a short TTL window
    - repeated calls with same key and same payload return cached report with `cache_hit=true`
    - repeated calls with same key but different payload return `400` with message `idempotency_key conflict with different payload`
    - `cache_ttl_seconds` is optional and only valid when `idempotency_key` is provided
    - `cache_ttl_seconds` must be within `[1, 3600]` when provided

- `POST /api/v1/gray-rollout/plan/batch/cache/clear`
  - RBAC: requires `device:write`
  - body (optional):
    ```json
    {
      "dry_run": false,
      "max_clear_entries": 100,
      "reset_counters": true
    }
    ```
  - 200 envelope:
    - `dry_run`
    - `cleared_entries`, `cleared_events` (actual cleared values)
    - `would_clear_entries`, `would_clear_events` (pre-clear snapshot)
    - `reset_counters`, `reset_counters_applied`, `max_clear_entries`, `max_clear_entries_source`, `cleared_at`
    - post-clear cache counters:
      - `gray_batch_plan_cache_entries`
      - `gray_batch_plan_cache_hits`
      - `gray_batch_plan_cache_misses`
      - `gray_batch_plan_cache_conflicts`
      - `gray_batch_plan_cache_evicted_expired`
      - `gray_batch_plan_cache_evicted_overflow`
      - `gray_batch_plan_cache_last_minute_requests`
      - `gray_batch_plan_cache_last_minute_hits`
      - `gray_batch_plan_cache_last_minute_misses`
      - `gray_batch_plan_cache_last_minute_conflicts`
      - `gray_batch_plan_cache_last_minute_hit_rate_percent`
  - clear rule:
    - always clears in-memory idempotency cache entries and minute-window cache events
    - when `reset_counters=true`, cumulative cache metrics counters are reset to `0`
  - dry-run rule:
    - when `dry_run=true`, no cache entries/events or counters are changed
    - response still returns `would_clear_entries` / `would_clear_events` for operational preview
  - guard rule:
    - when `max_clear_entries` is provided and `dry_run=false`, clear is rejected if `would_clear_entries` exceeds that threshold
    - when `max_clear_entries` is omitted, server uses cache policy `default_max_clear_entries` if configured

- `GET /api/v1/gray-rollout/plan/batch/cache/policy`
  - RBAC: requires `device:read`
  - 200 envelope:
    - `default_max_clear_entries` (`null` means disabled)

- `POST /api/v1/gray-rollout/plan/batch/cache/policy`
  - RBAC: requires `device:write`
  - body:
    ```json
    {
      "default_max_clear_entries": 100
    }
    ```
  - 200 envelope:
    - `default_max_clear_entries` (`null` disables default threshold policy)
  - validation:
    - `default_max_clear_entries` must be positive integer or `null`
  - persistence:
    - when runtime storage is enabled (sqlite), this policy is persisted and restored after restart

- `GET /api/v1/gray-rollout/plan/batch/cache/policy/history`
  - RBAC: requires `device:write`
  - query params (optional):
    - `limit` (default `20`, valid range `1..200`)
    - `before_id` (positive integer audit id, returns records with `id < before_id`)
    - `include_total` (`true|false`, default `false`; when `true`, includes `total_candidates`)
  - 200 envelope:
    - `items[]` from audit records filtered by action:
      - `gray_rollout.plan_batch.cache.policy.update`
    - `limit`, `before_id` (request cursor echo, nullable), `query_string` (normalized current-page query string)
    - `returned_items`, `window_max_id`, `window_min_id`, `window_span`, `dense_window`, `id_gap_count`, `window_density`, `window_newest_at`, `window_oldest_at`, `snapshot_at`, `order` (`id_desc`)
    - `window_span` = `window_max_id - window_min_id + 1` when page has items; otherwise `null`
    - `dense_window` = whether `window_span == returned_items` when page has items; otherwise `null`
    - `id_gap_count` = `window_span - returned_items` (non-negative) when page has items; otherwise `null`
    - `window_density` = `returned_items / window_span` (rounded to 6 decimals) when page has items; otherwise `null`
    - `window_newest_at`/`window_oldest_at` = current page first/last record `at` timestamps; `null` when page is empty
    - `has_more`, `next_before_id` (`null` when no next page)
    - `next_query` (`null` when no next page; otherwise `{limit,before_id,include_total}`)
    - `next_query_string` (`null` when no next page; otherwise `limit=...&before_id=...&include_total=...`)
    - `total_candidates` (`null` when `include_total=false`)
    - `remaining_candidates` (`total_candidates-returned_items`; `null` when `include_total=false`)
  - validation:
    - `limit` must be integer within `[1, 200]`
    - `before_id` must be a positive integer when provided
    - `include_total` must be boolean-like (`true/false/1/0/yes/no/on/off`)

- `GET /api/v1/gray-rollout/plan/batch/cache`
  - RBAC: requires `device:read`
  - query params (optional):
    - `limit` (default `20`, valid range `1..200`)
    - `include_events` (`true|false`, default `false`)
  - 200 envelope:
    - `limit`, `max_limit`, `total_entries`, `returned_entries`
    - cache policy: `max_entries`, `default_ttl_seconds`, `max_ttl_seconds`
    - `items[]` ordered by `created_at` desc:
      - `idempotency_key`, `fingerprint`, `created_at`, `expires_at`
      - `ttl_remaining_seconds`, `age_seconds`
    - optional `event_window` (when `include_events=true`):
      - `event_count`, `last_minute_requests`, `last_minute_hits`, `last_minute_misses`
      - `last_minute_conflicts`, `last_minute_hit_rate_percent`
  - validation:
    - `limit` must be integer within `[1, 200]`
    - `include_events` must be boolean-like (`true/false/1/0/yes/no/on/off`)

- `GET /api/v1/gray-rollout/plan/batch/cache/ops`
  - RBAC: requires `device:write`
  - query params (optional):
    - `limit` (default `20`, valid range `1..200`)
    - `before_id` (positive integer audit id, returns records with `id < before_id`)
    - `include_total` (`true|false`, default `false`; when `true`, includes `total_candidates`)
  - 200 envelope:
    - `items[]` from audit records, filtered by cache clear operation actions:
      - `gray_rollout.plan_batch.cache.clear.preview`
      - `gray_rollout.plan_batch.cache.clear.blocked`
      - `gray_rollout.plan_batch.cache.clear`
    - `limit`, `before_id` (request cursor echo, nullable), `query_string` (normalized current-page query string)
    - `returned_items`, `window_max_id`, `window_min_id`, `window_span`, `dense_window`, `id_gap_count`, `window_density`, `window_newest_at`, `window_oldest_at`, `snapshot_at`, `order` (`id_desc`)
    - `window_span` = `window_max_id - window_min_id + 1` when page has items; otherwise `null`
    - `dense_window` = whether `window_span == returned_items` when page has items; otherwise `null`
    - `id_gap_count` = `window_span - returned_items` (non-negative) when page has items; otherwise `null`
    - `window_density` = `returned_items / window_span` (rounded to 6 decimals) when page has items; otherwise `null`
    - `window_newest_at`/`window_oldest_at` = current page first/last record `at` timestamps; `null` when page is empty
    - `has_more`, `next_before_id` (`null` when no next page)
    - `next_query` (`null` when no next page; otherwise `{limit,before_id,include_total}`)
    - `next_query_string` (`null` when no next page; otherwise `limit=...&before_id=...&include_total=...`)
    - `total_candidates` (`null` when `include_total=false`)
    - `remaining_candidates` (`total_candidates-returned_items`; `null` when `include_total=false`)
  - validation:
    - `limit` must be integer within `[1, 200]`
    - `before_id` must be a positive integer when provided
    - `include_total` must be boolean-like (`true/false/1/0/yes/no/on/off`)

## FastAPI Compatibility Layer

File: `src/p0_runtime/fastapi_adapter.py`

- `is_fastapi_available()` checks optional dependency presence
- `create_fastapi_app(runtime=None, bootstrap_token="")` builds a compatibility app when dependencies exist
- Adapter now aligns with stdlib server behavior for:
  - response envelope (`success/data/error/meta`)
  - bearer + RBAC guardrails on protected endpoints
  - admin token issuance bootstrap guard
- If `fastapi/pydantic` are not installed, it raises runtime error by design

## Test Commands

```powershell
python -m unittest discover -s tests -p 'test_*.py'
```
