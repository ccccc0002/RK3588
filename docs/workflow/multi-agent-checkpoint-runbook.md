# Multi-Agent Checkpoint Runbook

This runbook defines how to collaborate in parallel, checkpoint each phase, and recover quickly after interruption.

## 1. Collaboration Model

Use one stage branch per phase.

- Branch naming: `stage/<P0|P1|P2|P3>-<short-goal>`
- Commit style: `type(scope): message`
- Checkpoint commit style: `chore(checkpoint): <stage> - <summary>`

Parallel lanes per stage:

1. Lane A (media ingest): `architect` + `build-error-resolver`
2. Lane B (ai pipeline): `architect` + `tdd-guide`
3. Lane C (event and push): `api-design` + `security-reviewer`
4. Lane D (platform control): `database-reviewer` + `code-reviewer`

Merge lane branches into stage branch only after verification gates pass.

## 2. Stage Gates (must pass before checkpoint)

1. Build check
2. Type check
3. Lint check
4. Test check (unit/integration/e2e)
5. Security check
6. Diff review

Reference skill: `verification-loop`.

## 3. Required Output per Stage

At least:

1. One merged stage branch
2. One checkpoint commit
3. One checkpoint tag
4. One checkpoint metadata file in `.checkpoints/`
5. One memory entry in `docs/development-memory.md`

## 4. Commands

Create a checkpoint locally:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stage-checkpoint.ps1 `
  -Stage "P0" `
  -Summary "Closed loop: ingest->infer->event->push" `
  -Next "Start P1 GB28181 cascade and OCR"
```

Create checkpoint and push branch/tag to GitHub:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stage-checkpoint.ps1 `
  -Stage "P0" `
  -Summary "P0 completed and verified" `
  -Next "P1 implementation starts" `
  -VerifyCommand "npm test" `
  -Push
```

List checkpoints:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\list-checkpoints.ps1
```

Restore from latest checkpoint (create resume branch):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\restore-checkpoint.ps1 `
  -Checkpoint latest `
  -CreateResumeBranch
```

Restore from specific checkpoint id:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\restore-checkpoint.ps1 `
  -Checkpoint 20260303-180000-P0 `
  -CreateResumeBranch `
  -BranchName "resume/p0/hotfix"
```

## 5. Interruption Recovery Protocol

When a session is interrupted:

1. Run `scripts/list-checkpoints.ps1`
2. Restore latest checkpoint with `scripts/restore-checkpoint.ps1 -Checkpoint latest -CreateResumeBranch`
3. Read latest entries in `docs/development-memory.md`
4. Continue only from "Next" field in checkpoint

## 6. Anti-Drift Rules

1. Never skip stage checkpoint on milestone completion.
2. Never start the next stage before writing `Next`.
3. Keep checkpoint summaries short and explicit.
4. Keep one checkpoint per meaningful stage result, not per tiny commit.
5. If no Git remote is configured, checkpoint locally first, then add remote and re-run with `-Push`.

