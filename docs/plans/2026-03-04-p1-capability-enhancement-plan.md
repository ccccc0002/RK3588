# P1 Capability Enhancement Plan

Date: 2026-03-04  
Branch baseline: `stage/P0-closed-loop` (after `P0-stage-closure`)

## Goal

Deliver P1 capabilities on top of validated P0 closed-loop runtime:

1. GB28181 cascade integration baseline
2. OCR and face-analysis capability wiring
3. Audit and network governance hardening

## Scope Boundaries

In scope:

1. API/runtime contract expansion for P1 capabilities.
2. Adapter and scheduler integration points for GB28181 and OCR/face pipelines.
3. Security and audit trail controls for new endpoints and dispatch paths.
4. Tests and docs required for forward-compatible P2/P3 evolution.

Out of scope:

1. Full production-grade model training platform.
2. Tenant-scale gray rollout orchestration (belongs to P3).
3. Non-critical UI redesign unrelated to P1 capability exposure.

## Lane Breakdown

### Lane A: GB28181 Cascade

Deliverables:

1. `src/p1_media/gb28181_adapter.py` (protocol normalization + registration contract).
2. Runtime endpoint set for GB28181 source registration/status.
3. Unit/integration tests for adapter normalization and registration flow.

Key acceptance:

1. Valid GB28181 source can be registered and listed through runtime API.
2. Invalid SIP/media fields are rejected with structured envelope error.

### Lane B: OCR/Face Capability

Deliverables:

1. Capability configuration contract (`ocr`, `face`) attached to source/device.
2. Scheduler hooks for per-stream capability enable/disable and budget policy.
3. Tests covering capability toggles and pipeline task generation.

Key acceptance:

1. Capability toggle updates are reflected in runtime snapshot.
2. Scheduler behavior remains deterministic under concurrent updates.

### Lane C: Event + Audit

Deliverables:

1. Audit record model for capability changes and critical runtime actions.
2. API endpoint(s) for querying recent audit entries with RBAC enforcement.
3. Tests for immutable audit append and RBAC constraints.

Key acceptance:

1. Every critical write action emits an audit record.
2. Viewer role cannot access privileged audit endpoints.

### Lane D: Platform + Network Governance

Deliverables:

1. Network policy configuration endpoint baseline (allowlist and outbound webhook guardrails).
2. Validation and persistence for network policy records.
3. Documentation update for security posture and operational runbook.

Key acceptance:

1. Invalid network policy updates are rejected with clear reason.
2. Policy state survives runtime restart when storage is enabled.

## Test Strategy

Required per lane:

1. Unit tests for pure domain logic.
2. Integration tests for runtime endpoints and persistence behavior.
3. Compatibility checks for Python 3.11 (local) + Python 3.8 (remote gate).

Global gate:

1. `python -m unittest discover -s tests -p 'test_*.py'` must pass locally.
2. Remote `python3.8 -m unittest discover -s tests -p 'test_*.py'` must pass before P1 stage closure.

## Milestones

1. M1: Contracts and scaffolds (API + domain interfaces).
2. M2: Lane A/B functional completion with tests.
3. M3: Lane C/D security and governance completion with tests.
4. M4: End-to-end verification, checkpoint, and stage review.

## Risks and Mitigation

1. Protocol complexity in GB28181 mapping:
   Mitigation: keep adapter contract narrow in P1, validate strict required fields.
2. Capability scheduler contention:
   Mitigation: preserve immutable update patterns and lock-scoped state transitions.
3. Security regression from new write endpoints:
   Mitigation: reuse centralized api policy mapping and enforce deny-by-default.

## Execution Start

Immediate next step:

1. Create `stage/P1-capability-enhancement` from current branch head.
2. Implement lane A API/domain scaffold with tests first.
