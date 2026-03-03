# RK3588 AI Box Phased Development Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deliver RK3588 AI Box in P0-P3 with reliable multi-agent collaboration, durable progress checkpoints, and fast recovery after interruption.

**Architecture:** Work is split into stage branches and isolated worktrees per lane. Each stage uses quality gates, checkpoint commits/tags, and durable markdown+json records. Context pressure is controlled by periodic compact packets and reminders.

**Tech Stack:** Git, Git worktree, PowerShell scripts, Markdown runbooks, FastAPI/C++/Vue3 architecture from PRD.

---

## Stage and Lane Model

Stages:

1. `P0` closed loop: ingest -> infer -> event -> push -> dashboard.
2. `P1` capability enhancement: GB28181 cascade, OCR/face, audit/network.
3. `P2` business expansion: algorithm repo, base libraries, offline analysis.
4. `P3` phase-2 readiness: edge agent, offline sync, gray rollout, tenant-site-box full path.

Lanes per stage:

1. `lane-a-media`: media ingest and preview.
2. `lane-b-ai`: decode/preprocess/inference/orchestration.
3. `lane-c-event`: event model, dedup, push retry/idempotency.
4. `lane-d-platform`: auth/license/network/repo/base-library/ui-config.

## Agent and Skill Mapping

Primary agents:

1. `planner` + `architect`: stage goals, boundaries, dependencies.
2. `tdd-guide` + `build-error-resolver`: fast RED->GREEN loops.
3. `security-reviewer` + `code-reviewer`: risk and quality gate.
4. `e2e-runner` + `doc-updater`: critical flow checks and doc sync.

Primary skills:

1. `writing-plans`: this document and stage task plan files.
2. `tdd-workflow`: test-first implementation per lane.
3. `verification-loop`: build/type/lint/test/security/diff gates.
4. `strategic-compact`: context compaction at phase boundaries.
5. `api-design`: REST, WS, webhook, gRPC contract consistency.
6. `security-review`: auth, token, audit, secrets, transport safety.

## Cadence Rules

1. Every lane updates `docs/workflow/agent-sync-log.md` at least every 30 minutes.
2. Every stage completion must run `scripts/stage-checkpoint.ps1`.
3. Every 45 minutes generate compact packet and decide whether to run `/compact`.
4. Every task runs in a dedicated worktree if it can conflict with another lane.

## Definition of Done (per stage)

1. Stage branch merged from all active lanes.
2. Verification gates are all pass.
3. Checkpoint commit + metadata commit + tag created.
4. `docs/development-memory.md` includes stage summary and explicit next step.
5. Recovery is validated with `scripts/restore-checkpoint.ps1 -Checkpoint latest -CreateResumeBranch`.

## Task Plan

### Task 1: Set up synchronization files

**Files:**
- Create: `docs/workflow/agent-sync-log.md`
- Create: `docs/workflow/commit-timeline.md`
- Create: `docs/workflow/compact-packet-latest.md`
- Modify: `docs/workflow/multi-agent-checkpoint-runbook.md`

**Step 1: Write scaffold markdown files**

Create files with durable sections and append-only logs.

**Step 2: Verify files exist**

Run: `Get-ChildItem docs/workflow`
Expected: all files listed.

**Step 3: Commit**

```bash
git add docs/workflow
git commit -m "docs(workflow): add durable sync and compact records"
```

### Task 2: Add sync/compact/worktree scripts

**Files:**
- Create: `scripts/update-sync-log.ps1`
- Create: `scripts/post-commit-sync.ps1`
- Create: `scripts/generate-compact-packet.ps1`
- Create: `scripts/start-compact-reminder.ps1`
- Create: `scripts/new-workstream.ps1`
- Create: `scripts/list-workstreams.ps1`

**Step 1: Write scripts with strict mode and parameter validation**

Scripts must be safe for repeated execution.

**Step 2: Run smoke tests**

Run:
- `powershell -File .\scripts\update-sync-log.ps1 -Stage P0 -Lane lane-a-media -Agent planner -Status in_progress -Summary "kickoff" -Next "design api"`
- `powershell -File .\scripts\generate-compact-packet.ps1`
- `powershell -File .\scripts\list-workstreams.ps1`

Expected: scripts exit 0 and files update.

**Step 3: Commit**

```bash
git add scripts
git commit -m "feat(workflow): add sync compact and workstream scripts"
```

### Task 3: Install hook workflow

**Files:**
- Create: `.githooks/post-commit`
- Create: `scripts/install-dev-hooks.ps1`

**Step 1: Implement hook installer**

Set `core.hooksPath` to `.githooks` and ensure hook is executable.

**Step 2: Smoke test**

Run: `powershell -File .\scripts\install-dev-hooks.ps1`
Expected: `Hook path configured` and `post-commit installed`.

**Step 3: Commit**

```bash
git add .githooks scripts/install-dev-hooks.ps1
git commit -m "feat(workflow): install post-commit sync hook"
```

### Task 4: Validate checkpoint + recovery end-to-end

**Files:**
- Modify: `.checkpoints/*` (generated)
- Modify: `docs/development-memory.md` (generated)

**Step 1: Run checkpoint**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stage-checkpoint.ps1 `
  -Stage "workflow-ready" `
  -Summary "workflow automation validated" `
  -Next "start P0 lane workstreams"
```

**Step 2: Validate recovery**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\restore-checkpoint.ps1 `
  -Checkpoint latest `
  -CreateResumeBranch
```

Expected: resume branch is created and points to latest checkpoint commit.

**Step 3: Commit generated records if needed**

```bash
git add .checkpoints docs/development-memory.md
git commit -m "chore(workflow): persist workflow-ready checkpoint records"
```

## Execution Notes

1. Keep one stage one checkpoint, not one task one checkpoint.
2. Every lane branch must include clear ownership in commit subject.
3. Always write `Next` in checkpoint metadata to protect continuity after interruption.
4. Keep compact packets short, factual, and actionable.

