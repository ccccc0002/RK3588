# P1 Pre-Closure Review

Last updated: 2026-03-04T13:35:00+08:00  
Branch: `stage/P1-capability-enhancement`

## Delivered in P1 So Far

1. GB28181 adapter and runtime registration integration.
2. Device capability management (`ocr`, `face`) with API support.
3. Capability-aware runtime schedule planning API.
4. Audit trail model with RBAC-protected query endpoint.
5. Network policy baseline (read/update API + dispatch allowlist enforcement).
6. SQLite persistence for network policy and audit records.

## Verification Summary

1. Local gate: `python -m unittest discover -s tests -p 'test_*.py'`  
   Result: 73 tests pass on Python 3.11.
2. Remote gate on `192.168.1.104`: `python3.8 -m unittest discover -s tests -p 'test_*.py'`  
   Result: 73 tests pass on Python 3.8.10.
3. GitHub sync: `stage/P1-capability-enhancement` and checkpoint tags pushed.

## Latest Hardening Progress

1. Policy-denied outbound dispatch now short-circuits to dead-letter on first failure.
2. Policy-denied attempts are audit-recorded as `push.dispatch.policy_denied`.
3. Dispatch path remains retry-based for runtime/network send failures that are not policy denials.

## Current Gaps Before P1 Closure

1. Scheduler currently uses fixed input FPS assumption (`8.0`) and does not yet bind to live telemetry.
2. Audit persistence is implemented, but retention/rotation policy is currently fixed (cap by record count).

## Recommended Final P1 Closure Tasks

1. Bind schedule planner inputs to real stream telemetry.
2. Define configurable retention policy for persisted audit records.
