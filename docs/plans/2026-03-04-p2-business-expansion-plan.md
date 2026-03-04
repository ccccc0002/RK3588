# P2 Business Expansion Plan

Date: 2026-03-04  
Branch baseline: `stage/P1-capability-enhancement` (after `P1-stage-closure`)

## Goal

Deliver P2 business expansion capabilities on top of stable P0/P1 runtime:

1. Algorithm repository management baseline (versioned model metadata and rollout intent).
2. Base capability library abstraction for reusable AI/business modules.
3. Offline analysis workflow for post-event reprocessing and reporting.

## Scope Boundaries

In scope:

1. Runtime/API contracts and persistence for algorithm/base-library/offline-analysis metadata.
2. Deterministic orchestration hooks for offline analysis job planning and status tracking.
3. Security and audit coverage for all new write endpoints.
4. Unit/integration test expansion and document parity updates.

Out of scope:

1. Full model training pipelines and GPU cluster scheduling.
2. Multi-tenant gray rollout topology controls (belongs to P3).
3. Production-grade billing and commercial packaging flows.

## Lane Breakdown

### Lane A: Algorithm Repository

Deliverables:

1. Algorithm catalog model (`algorithm_id`, `version`, `capabilities`, `status`).
2. Runtime endpoints for upsert/list/enable policy of algorithms.
3. Tests for schema validation, immutability, and persistence recovery.

Key acceptance:

1. Algorithm metadata survives runtime restart when sqlite storage is enabled.
2. Invalid version/state transitions are rejected with structured errors.

### Lane B: Base Capability Libraries

Deliverables:

1. Base library registry model for reusable components (OCR, face, detection templates).
2. Mapping contract from runtime devices/capabilities to selected base library entries.
3. Tests for deterministic selection and conflict validation.

Key acceptance:

1. Capability-library mapping is queryable and auditable.
2. Runtime behavior remains deterministic under concurrent updates.

### Lane C: Offline Analysis

Deliverables:

1. Offline analysis job model (`job_id`, `source_scope`, `algorithm_version`, `status`, `result_ref`).
2. Job lifecycle endpoints (create, list, status update) with idempotency constraints.
3. Tests for job transitions and audit trace completeness.

Key acceptance:

1. Offline jobs can be created and tracked without affecting online dispatch SLA.
2. Every job state change emits an immutable audit record.

### Lane D: Platform Governance

Deliverables:

1. RBAC and network policy parity for all new P2 endpoints.
2. API contract updates (`docs/api/p0-openapi.yaml` and runtime endpoint docs).
3. Pre-closure review checklist and checkpoint trace updates.

Key acceptance:

1. Viewer/operator/admin boundaries are enforced for P2 resources.
2. Documentation and tests match runtime behavior with no drift.

## Test Strategy

Required per lane:

1. Unit tests for pure domain modules.
2. Integration tests for runtime HTTP API and persistence behavior.
3. Compatibility validation on Python 3.11 (local) and Python 3.8 (remote gate).

Global gate:

1. `python -m unittest discover -s tests -p 'test_*.py'` passes locally.
2. `python3.8 -m unittest discover -s tests -p 'test_*.py'` passes on remote host before P2 closure.

## Milestones

1. M1: Data contracts and endpoint scaffolds for algorithm repository.
2. M2: Base library mapping and audit instrumentation.
3. M3: Offline analysis job workflow and persistence hardening.
4. M4: Security/contract review, full validation, and P2 closure checkpoint.

## Risks and Mitigation

1. Contract sprawl across new P2 resources:
   Mitigation: keep schemas minimal and centrally validated at runtime boundaries.
2. Offline job state complexity:
   Mitigation: enforce explicit status transition matrix with test-first development.
3. Security regression from additional write endpoints:
   Mitigation: reuse centralized api policy mapping and audit every critical mutation.

## Execution Start

Immediate next step:

1. Create `stage/P2-business-expansion` from current head.
2. Implement lane A algorithm repository scaffold with tests first.
