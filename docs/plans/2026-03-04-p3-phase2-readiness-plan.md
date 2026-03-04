# P3 Phase-2 Readiness Plan

Date: 2026-03-04  
Branch baseline: `stage/P2-business-expansion` (after `P2-stage-closure`)

## Goal

Deliver P3 readiness foundations on top of stable P2 contracts:

1. Offline executor health and heartbeat governance for safer job binding.
2. Semantic version compatibility checks for base-library mapping policy.
3. Preparatory contract hardening for edge-agent/sync/gray rollout phases.

## Scope Boundaries (Iteration 1)

In scope:

1. Executor heartbeat contract and runtime persistence fields.
2. Health-aware executor selection during offline job creation.
3. Compatibility policy extension with semantic version ranges.
4. Tests and API docs parity for all new/changed contracts.

Out of scope:

1. Full edge agent runtime and transport protocol.
2. Cross-box offline sync conflict resolution engine.
3. Tenant/site/box gray rollout controller.

## Lane Breakdown

### Lane A: Executor Health Governance

Deliverables:

1. `POST /api/v1/offline-executors/heartbeat` endpoint.
2. Executor record fields for heartbeat status (`last_heartbeat_at`, `health_state`).
3. Scheduler selection excludes unhealthy/stale executors by policy.

Acceptance:

1. Heartbeat updates are auditable and persisted.
2. Offline job auto-binding never picks stale executors when healthy options exist.

### Lane B: Semantic Compatibility Rules

Deliverables:

1. Compatibility policy extension with semantic range constraints by capability.
2. Runtime semver parser/comparator for deterministic validation.
3. Mapping validation gate enforcing regex + semver constraints.

Acceptance:

1. Invalid semantic versions are rejected when semantic policy is configured.
2. Mapping behavior remains deterministic and backward-compatible when semantic policy is absent.

### Lane C: Validation and Documentation

Deliverables:

1. Runtime/unit/http/fastapi/api-policy tests for new contracts.
2. OpenAPI + endpoint docs alignment.
3. P3 pre-closure tracking updates.

Acceptance:

1. Local `python -m unittest discover -s tests -p 'test_*.py'` passes.
2. Remote py3.8 gate rerun before next validated checkpoint.

## Risks and Mitigation

1. Semver rule ambiguity against calendar-style versions:
   - Mitigation: semantic rules are opt-in per capability; existing regex-only policies remain valid.
2. Heartbeat freshness time-source drift:
   - Mitigation: allow explicit `now` input and default to server UTC when absent.
3. Executor starvation under strict health rules:
   - Mitigation: keep fallback behavior explicit and documented in policy defaults.

## Immediate Next

1. Implement TDD red tests for heartbeat endpoint and semantic compatibility checks.
2. Implement runtime/API/storage updates to satisfy new tests.
