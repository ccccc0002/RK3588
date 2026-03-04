from __future__ import annotations

from datetime import datetime
import importlib.util
from typing import Any

from src.p0_runtime.api_envelope import error_payload, ok_payload
from src.p0_runtime.api_policy import is_supported_role, required_get_action, required_post_action
from src.p0_runtime.runtime import P0Runtime


def is_fastapi_available() -> bool:
    return bool(importlib.util.find_spec("fastapi") and importlib.util.find_spec("pydantic"))


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _sender_for_mode(mode: str | None):
    normalized = (mode or "real").strip().lower()
    if normalized == "real":
        return None
    if normalized == "always_success":
        return lambda _task: True
    if normalized == "always_fail":
        return lambda _task: False
    return None


def create_fastapi_app(runtime: P0Runtime | None = None, bootstrap_token: str = "") -> Any:
    if not is_fastapi_available():
        raise RuntimeError("fastapi/pydantic not installed")

    from fastapi import Body, FastAPI, Header
    from fastapi.responses import JSONResponse

    app = FastAPI(title="RK3588 P0 FastAPI Adapter", version="0.1.0")
    rt = runtime or P0Runtime(webhook_url="https://example.com/hook", webhook_token="token")
    bootstrap_secret = str(bootstrap_token or "").strip()

    def _authorize_request(authorization: str, required_action: str) -> JSONResponse | None:
        auth_value = str(authorization or "")
        if not auth_value.startswith("Bearer "):
            return JSONResponse(status_code=401, content=error_payload("unauthorized", "missing bearer token"))
        token = auth_value[len("Bearer ") :].strip()
        if not token:
            return JSONResponse(status_code=401, content=error_payload("unauthorized", "missing bearer token"))

        ok, context = rt.authorize(token=token, required_action=required_action)
        if ok:
            return None
        if context and context.get("reason") == "forbidden":
            return JSONResponse(
                status_code=403,
                content=error_payload(
                    "forbidden",
                    "action not allowed for current role",
                    details={"required_action": required_action, "role": context.get("role")},
                ),
            )
        return JSONResponse(status_code=401, content=error_payload("invalid_token", "token invalid or expired"))

    @app.get("/api/v1/runtime/snapshot")
    def runtime_snapshot(authorization: str = Header(default="", alias="Authorization")):
        denied = _authorize_request(authorization, required_get_action("/api/v1/runtime/snapshot") or "alert:read")
        if denied is not None:
            return denied
        return ok_payload(rt.snapshot())

    @app.get("/api/v1/metrics")
    def runtime_metrics(authorization: str = Header(default="", alias="Authorization")):
        denied = _authorize_request(authorization, required_get_action("/api/v1/metrics") or "alert:read")
        if denied is not None:
            return denied
        return ok_payload(rt.get_metrics())

    @app.get("/api/v1/devices")
    def list_devices(authorization: str = Header(default="", alias="Authorization")):
        denied = _authorize_request(authorization, required_get_action("/api/v1/devices") or "device:read")
        if denied is not None:
            return denied
        return ok_payload({"items": rt.list_devices()})

    @app.get("/api/v1/algorithms")
    def list_algorithms(authorization: str = Header(default="", alias="Authorization")):
        denied = _authorize_request(authorization, required_get_action("/api/v1/algorithms") or "device:read")
        if denied is not None:
            return denied
        return ok_payload({"items": rt.list_algorithms()})

    @app.get("/api/v1/base-libraries")
    def list_base_libraries(authorization: str = Header(default="", alias="Authorization")):
        denied = _authorize_request(authorization, required_get_action("/api/v1/base-libraries") or "device:read")
        if denied is not None:
            return denied
        return ok_payload({"items": rt.list_base_libraries()})

    @app.get("/api/v1/base-libraries/mappings")
    def list_base_library_mappings(authorization: str = Header(default="", alias="Authorization")):
        denied = _authorize_request(
            authorization,
            required_get_action("/api/v1/base-libraries/mappings") or "device:read",
        )
        if denied is not None:
            return denied
        return ok_payload({"items": rt.list_base_library_mappings()})

    @app.get("/api/v1/base-libraries/compatibility/policy")
    def get_base_library_compatibility_policy(authorization: str = Header(default="", alias="Authorization")):
        denied = _authorize_request(
            authorization,
            required_get_action("/api/v1/base-libraries/compatibility/policy") or "device:read",
        )
        if denied is not None:
            return denied
        return ok_payload(rt.get_base_library_compatibility_policy())

    @app.get("/api/v1/offline-executors")
    def list_offline_executors(authorization: str = Header(default="", alias="Authorization")):
        denied = _authorize_request(authorization, required_get_action("/api/v1/offline-executors") or "device:read")
        if denied is not None:
            return denied
        return ok_payload({"items": rt.list_offline_executors()})

    @app.get("/api/v1/offline-jobs")
    def list_offline_jobs(authorization: str = Header(default="", alias="Authorization")):
        denied = _authorize_request(authorization, required_get_action("/api/v1/offline-jobs") or "device:read")
        if denied is not None:
            return denied
        return ok_payload({"items": rt.list_offline_jobs()})

    @app.get("/api/v1/edge-agents")
    def list_edge_agents(authorization: str = Header(default="", alias="Authorization")):
        denied = _authorize_request(authorization, required_get_action("/api/v1/edge-agents") or "device:read")
        if denied is not None:
            return denied
        return ok_payload({"items": rt.list_edge_agents()})

    @app.get("/api/v1/offline-sync/cursors")
    def list_offline_sync_cursors(authorization: str = Header(default="", alias="Authorization")):
        denied = _authorize_request(authorization, required_get_action("/api/v1/offline-sync/cursors") or "device:read")
        if denied is not None:
            return denied
        return ok_payload({"items": rt.list_offline_sync_cursors()})

    @app.get("/api/v1/offline-sync/streams")
    def list_offline_sync_stream_cursors(authorization: str = Header(default="", alias="Authorization")):
        denied = _authorize_request(authorization, required_get_action("/api/v1/offline-sync/streams") or "device:read")
        if denied is not None:
            return denied
        return ok_payload({"items": rt.list_offline_sync_stream_cursors()})

    @app.get("/api/v1/push/worker/status")
    def push_worker_status(authorization: str = Header(default="", alias="Authorization")):
        denied = _authorize_request(authorization, required_get_action("/api/v1/push/worker/status") or "device:read")
        if denied is not None:
            return denied
        return ok_payload(rt.push_worker_status())

    @app.get("/api/v1/audit/recent")
    def audit_recent(limit: int = 20, authorization: str = Header(default="", alias="Authorization")):
        denied = _authorize_request(authorization, required_get_action("/api/v1/audit/recent") or "device:write")
        if denied is not None:
            return denied
        return ok_payload({"items": rt.list_audit_records(limit=limit)})

    @app.get("/api/v1/audit/policy")
    def get_audit_policy_ep(authorization: str = Header(default="", alias="Authorization")):
        denied = _authorize_request(authorization, required_get_action("/api/v1/audit/policy") or "device:read")
        if denied is not None:
            return denied
        return ok_payload(rt.get_audit_policy())

    @app.post("/api/v1/audit/policy")
    def update_audit_policy_ep(
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(authorization, required_post_action("/api/v1/audit/policy") or "device:write")
        if denied is not None:
            return denied
        try:
            return ok_payload(rt.update_audit_policy(dict(payload)))
        except ValueError as exc:
            return JSONResponse(status_code=400, content=error_payload("bad_request", str(exc)))

    @app.get("/api/v1/network/policy")
    def get_network_policy_ep(authorization: str = Header(default="", alias="Authorization")):
        denied = _authorize_request(authorization, required_get_action("/api/v1/network/policy") or "device:read")
        if denied is not None:
            return denied
        return ok_payload(rt.get_network_policy())

    @app.get("/api/v1/gray-rollout/policy")
    def get_gray_rollout_policy_ep(authorization: str = Header(default="", alias="Authorization")):
        denied = _authorize_request(authorization, required_get_action("/api/v1/gray-rollout/policy") or "device:read")
        if denied is not None:
            return denied
        return ok_payload(rt.get_gray_rollout_policy())

    @app.post("/api/v1/auth/token")
    def issue_token_ep(
        payload: dict = Body(default_factory=dict),
        x_bootstrap_token: str = Header(default="", alias="X-Bootstrap-Token"),
    ):
        role = str(payload.get("role", "viewer"))
        if not is_supported_role(role):
            return JSONResponse(status_code=400, content=error_payload("bad_request", f"unsupported role: {role}"))

        if role == "admin":
            provided = str(x_bootstrap_token or "").strip()
            if not bootstrap_secret or provided != bootstrap_secret:
                return JSONResponse(
                    status_code=403,
                    content=error_payload("forbidden", "admin token issuance requires valid bootstrap token"),
                )

        user_id = str(payload.get("user_id", ""))
        now = _parse_time(payload.get("now"))
        return ok_payload(rt.issue_token(user_id=user_id, role=role, now=now))

    @app.post("/api/v1/devices/register")
    def register_device_ep(
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(authorization, required_post_action("/api/v1/devices/register") or "device:write")
        if denied is not None:
            return denied
        try:
            return ok_payload(rt.register_device(dict(payload)))
        except ValueError as exc:
            return JSONResponse(status_code=400, content=error_payload("bad_request", str(exc)))

    @app.post("/api/v1/devices/capabilities")
    def update_device_capabilities_ep(
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(
            authorization,
            required_post_action("/api/v1/devices/capabilities") or "device:write",
        )
        if denied is not None:
            return denied
        try:
            return ok_payload(rt.update_device_capabilities(dict(payload)))
        except ValueError as exc:
            return JSONResponse(status_code=400, content=error_payload("bad_request", str(exc)))

    @app.post("/api/v1/algorithms/upsert")
    def upsert_algorithm_ep(
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(authorization, required_post_action("/api/v1/algorithms/upsert") or "device:write")
        if denied is not None:
            return denied
        try:
            return ok_payload(rt.upsert_algorithm(dict(payload)))
        except ValueError as exc:
            return JSONResponse(status_code=400, content=error_payload("bad_request", str(exc)))

    @app.post("/api/v1/base-libraries/upsert")
    def upsert_base_library_ep(
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(
            authorization,
            required_post_action("/api/v1/base-libraries/upsert") or "device:write",
        )
        if denied is not None:
            return denied
        try:
            return ok_payload(rt.upsert_base_library(dict(payload)))
        except ValueError as exc:
            return JSONResponse(status_code=400, content=error_payload("bad_request", str(exc)))

    @app.post("/api/v1/base-libraries/mappings/upsert")
    def upsert_base_library_mapping_ep(
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(
            authorization,
            required_post_action("/api/v1/base-libraries/mappings/upsert") or "device:write",
        )
        if denied is not None:
            return denied
        try:
            return ok_payload(rt.upsert_base_library_mapping(dict(payload)))
        except ValueError as exc:
            return JSONResponse(status_code=400, content=error_payload("bad_request", str(exc)))

    @app.post("/api/v1/base-libraries/mappings/batch-upsert")
    def batch_upsert_base_library_mapping_ep(
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(
            authorization,
            required_post_action("/api/v1/base-libraries/mappings/batch-upsert") or "device:write",
        )
        if denied is not None:
            return denied
        try:
            return ok_payload({"items": rt.batch_upsert_base_library_mappings(dict(payload))})
        except ValueError as exc:
            return JSONResponse(status_code=400, content=error_payload("bad_request", str(exc)))

    @app.post("/api/v1/base-libraries/compatibility/policy")
    def update_base_library_compatibility_policy_ep(
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(
            authorization,
            required_post_action("/api/v1/base-libraries/compatibility/policy") or "device:write",
        )
        if denied is not None:
            return denied
        try:
            return ok_payload(rt.update_base_library_compatibility_policy(dict(payload)))
        except ValueError as exc:
            return JSONResponse(status_code=400, content=error_payload("bad_request", str(exc)))

    @app.post("/api/v1/offline-executors/upsert")
    def upsert_offline_executor_ep(
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(authorization, required_post_action("/api/v1/offline-executors/upsert") or "device:write")
        if denied is not None:
            return denied
        try:
            return ok_payload(rt.upsert_offline_executor(dict(payload)))
        except ValueError as exc:
            return JSONResponse(status_code=400, content=error_payload("bad_request", str(exc)))

    @app.post("/api/v1/offline-executors/heartbeat")
    def heartbeat_offline_executor_ep(
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(
            authorization,
            required_post_action("/api/v1/offline-executors/heartbeat") or "device:write",
        )
        if denied is not None:
            return denied
        try:
            return ok_payload(rt.heartbeat_offline_executor(dict(payload), now=_parse_time(payload.get("now"))))
        except ValueError as exc:
            return JSONResponse(status_code=400, content=error_payload("bad_request", str(exc)))

    @app.post("/api/v1/edge-agents/register")
    def register_edge_agent_ep(
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(authorization, required_post_action("/api/v1/edge-agents/register") or "device:write")
        if denied is not None:
            return denied
        try:
            return ok_payload(rt.register_edge_agent(dict(payload)))
        except ValueError as exc:
            return JSONResponse(status_code=400, content=error_payload("bad_request", str(exc)))

    @app.post("/api/v1/edge-agents/heartbeat")
    def heartbeat_edge_agent_ep(
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(authorization, required_post_action("/api/v1/edge-agents/heartbeat") or "device:write")
        if denied is not None:
            return denied
        try:
            return ok_payload(rt.heartbeat_edge_agent(dict(payload), now=_parse_time(payload.get("now"))))
        except ValueError as exc:
            return JSONResponse(status_code=400, content=error_payload("bad_request", str(exc)))

    @app.post("/api/v1/edge-agents/offline-jobs/lease")
    def lease_offline_job_to_edge_agent_ep(
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(
            authorization,
            required_post_action("/api/v1/edge-agents/offline-jobs/lease") or "device:write",
        )
        if denied is not None:
            return denied
        try:
            return ok_payload(rt.lease_offline_job_to_edge_agent(dict(payload), now=_parse_time(payload.get("now"))))
        except ValueError as exc:
            return JSONResponse(status_code=400, content=error_payload("bad_request", str(exc)))

    @app.post("/api/v1/edge-agents/offline-jobs/lease/start")
    def start_offline_job_with_lease_ep(
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(
            authorization,
            required_post_action("/api/v1/edge-agents/offline-jobs/lease/start") or "device:write",
        )
        if denied is not None:
            return denied
        try:
            return ok_payload(rt.start_offline_job_with_lease(dict(payload), now=_parse_time(payload.get("now"))))
        except ValueError as exc:
            return JSONResponse(status_code=400, content=error_payload("bad_request", str(exc)))

    @app.post("/api/v1/edge-agents/offline-jobs/lease/renew")
    def renew_offline_job_lease_ep(
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(
            authorization,
            required_post_action("/api/v1/edge-agents/offline-jobs/lease/renew") or "device:write",
        )
        if denied is not None:
            return denied
        try:
            return ok_payload(rt.renew_offline_job_lease(dict(payload), now=_parse_time(payload.get("now"))))
        except ValueError as exc:
            return JSONResponse(status_code=400, content=error_payload("bad_request", str(exc)))

    @app.post("/api/v1/edge-agents/offline-jobs/lease/release")
    def release_offline_job_lease_ep(
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(
            authorization,
            required_post_action("/api/v1/edge-agents/offline-jobs/lease/release") or "device:write",
        )
        if denied is not None:
            return denied
        try:
            return ok_payload(rt.release_offline_job_lease(dict(payload), now=_parse_time(payload.get("now"))))
        except ValueError as exc:
            return JSONResponse(status_code=400, content=error_payload("bad_request", str(exc)))

    @app.post("/api/v1/edge-agents/offline-jobs/lease/complete")
    def complete_offline_job_with_lease_ep(
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(
            authorization,
            required_post_action("/api/v1/edge-agents/offline-jobs/lease/complete") or "device:write",
        )
        if denied is not None:
            return denied
        try:
            return ok_payload(rt.complete_offline_job_with_lease(dict(payload), now=_parse_time(payload.get("now"))))
        except ValueError as exc:
            return JSONResponse(status_code=400, content=error_payload("bad_request", str(exc)))

    @app.post("/api/v1/offline-sync/cursors/upsert")
    def upsert_offline_sync_cursor_ep(
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(
            authorization,
            required_post_action("/api/v1/offline-sync/cursors/upsert") or "device:write",
        )
        if denied is not None:
            return denied
        try:
            return ok_payload(rt.upsert_offline_sync_cursor(dict(payload), now=_parse_time(payload.get("now"))))
        except ValueError as exc:
            return JSONResponse(status_code=400, content=error_payload("bad_request", str(exc)))

    @app.post("/api/v1/offline-sync/streams/upsert")
    def upsert_offline_sync_stream_cursor_ep(
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(
            authorization,
            required_post_action("/api/v1/offline-sync/streams/upsert") or "device:write",
        )
        if denied is not None:
            return denied
        try:
            return ok_payload(rt.upsert_offline_sync_stream_cursor(dict(payload), now=_parse_time(payload.get("now"))))
        except ValueError as exc:
            return JSONResponse(status_code=400, content=error_payload("bad_request", str(exc)))

    @app.post("/api/v1/offline-jobs/create")
    def create_offline_job_ep(
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(authorization, required_post_action("/api/v1/offline-jobs/create") or "device:write")
        if denied is not None:
            return denied
        try:
            return ok_payload(rt.create_offline_job(dict(payload), now=_parse_time(payload.get("now"))))
        except ValueError as exc:
            return JSONResponse(status_code=400, content=error_payload("bad_request", str(exc)))

    @app.post("/api/v1/offline-jobs/status")
    def update_offline_job_status_ep(
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(authorization, required_post_action("/api/v1/offline-jobs/status") or "device:write")
        if denied is not None:
            return denied
        try:
            return ok_payload(rt.update_offline_job_status(dict(payload), now=_parse_time(payload.get("now"))))
        except ValueError as exc:
            return JSONResponse(status_code=400, content=error_payload("bad_request", str(exc)))

    @app.post("/api/v1/offline-jobs/status/batch")
    def batch_update_offline_job_status_ep(
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(
            authorization,
            required_post_action("/api/v1/offline-jobs/status/batch") or "device:write",
        )
        if denied is not None:
            return denied
        try:
            return ok_payload({"items": rt.batch_update_offline_job_status(dict(payload), now=_parse_time(payload.get("now")))})
        except ValueError as exc:
            return JSONResponse(status_code=400, content=error_payload("bad_request", str(exc)))

    @app.post("/api/v1/viewer-sessions/{stream_id}/join")
    def viewer_join_ep(
        stream_id: str,
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(
            authorization,
            required_post_action(f"/api/v1/viewer-sessions/{stream_id}/join") or "device:read",
        )
        if denied is not None:
            return denied
        return ok_payload(rt.viewer_join(stream_id=stream_id, now=_parse_time(payload.get("now"))))

    @app.post("/api/v1/viewer-sessions/{stream_id}/leave")
    def viewer_leave_ep(
        stream_id: str,
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(
            authorization,
            required_post_action(f"/api/v1/viewer-sessions/{stream_id}/leave") or "device:read",
        )
        if denied is not None:
            return denied
        return ok_payload(rt.viewer_leave(stream_id=stream_id, now=_parse_time(payload.get("now"))))

    @app.post("/api/v1/events")
    def ingest_event_ep(
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(authorization, required_post_action("/api/v1/events") or "device:write")
        if denied is not None:
            return denied
        try:
            event = dict(payload.get("event", {}))
            result = rt.ingest_event(event, now=_parse_time(payload.get("now")))
            status = int(result.get("status", 202))
            if status >= 400:
                return JSONResponse(
                    status_code=status,
                    content=error_payload("event_rejected", str(result.get("reason", "event_rejected")), details=result),
                )
            return JSONResponse(status_code=status, content=ok_payload(result))
        except ValueError as exc:
            return JSONResponse(status_code=400, content=error_payload("bad_request", str(exc)))

    @app.post("/api/v1/runtime/schedule")
    def runtime_schedule_ep(
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(authorization, required_post_action("/api/v1/runtime/schedule") or "device:read")
        if denied is not None:
            return denied
        budget = float(payload.get("budget", 10.0))
        return ok_payload(rt.plan_capability_schedule(budget=budget))

    @app.get("/api/v1/runtime/telemetry")
    def runtime_telemetry_ep(authorization: str = Header(default="", alias="Authorization")):
        denied = _authorize_request(authorization, required_get_action("/api/v1/runtime/telemetry") or "device:read")
        if denied is not None:
            return denied
        return ok_payload({"items": rt.list_stream_telemetry()})

    @app.post("/api/v1/runtime/telemetry")
    def update_runtime_telemetry_ep(
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(authorization, required_post_action("/api/v1/runtime/telemetry") or "device:write")
        if denied is not None:
            return denied
        try:
            return ok_payload(rt.update_stream_telemetry(dict(payload), now=_parse_time(payload.get("now"))))
        except ValueError as exc:
            return JSONResponse(status_code=400, content=error_payload("bad_request", str(exc)))

    @app.post("/api/v1/network/policy")
    def update_network_policy_ep(
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(authorization, required_post_action("/api/v1/network/policy") or "device:write")
        if denied is not None:
            return denied
        try:
            return ok_payload(rt.update_network_policy(dict(payload)))
        except ValueError as exc:
            return JSONResponse(status_code=400, content=error_payload("bad_request", str(exc)))

    @app.post("/api/v1/gray-rollout/policy")
    def update_gray_rollout_policy_ep(
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(authorization, required_post_action("/api/v1/gray-rollout/policy") or "device:write")
        if denied is not None:
            return denied
        try:
            return ok_payload(rt.update_gray_rollout_policy(dict(payload)))
        except ValueError as exc:
            return JSONResponse(status_code=400, content=error_payload("bad_request", str(exc)))

    @app.post("/api/v1/gray-rollout/evaluate")
    def evaluate_gray_rollout_ep(
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(authorization, required_post_action("/api/v1/gray-rollout/evaluate") or "device:read")
        if denied is not None:
            return denied
        try:
            return ok_payload(rt.evaluate_gray_rollout(dict(payload)))
        except ValueError as exc:
            return JSONResponse(status_code=400, content=error_payload("bad_request", str(exc)))

    @app.post("/api/v1/push/dispatch")
    def dispatch_push_ep(
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(authorization, required_post_action("/api/v1/push/dispatch") or "device:write")
        if denied is not None:
            return denied
        limit = int(payload.get("limit", 20))
        mode = str(payload.get("mode", "real"))
        sender = _sender_for_mode(mode)
        result = rt.dispatch_pushes(now=_parse_time(payload.get("now")), sender=sender, max_items=limit)
        return ok_payload(result)

    @app.post("/api/v1/push/worker/start")
    def start_push_worker_ep(
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(authorization, required_post_action("/api/v1/push/worker/start") or "device:write")
        if denied is not None:
            return denied
        interval_ms = int(payload.get("interval_ms", 500))
        limit = int(payload.get("limit", 20))
        mode = str(payload.get("mode", "real"))
        sender = _sender_for_mode(mode)
        result = rt.start_push_worker(
            interval_seconds=max(0.01, interval_ms / 1000.0),
            max_items=limit,
            sender=sender,
        )
        return ok_payload(result)

    @app.post("/api/v1/push/worker/stop")
    def stop_push_worker_ep(
        payload: dict = Body(default_factory=dict),
        authorization: str = Header(default="", alias="Authorization"),
    ):
        denied = _authorize_request(authorization, required_post_action("/api/v1/push/worker/stop") or "device:write")
        if denied is not None:
            return denied
        _ = payload
        return ok_payload(rt.stop_push_worker())

    return app
