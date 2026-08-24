# Verbose runtime diagnostics

## Context

Worktree: `/home/public/googlephotos/.worktrees/verbose-runtime-diagnostics`  
Base: `fcabfe5`  
Spec: `doc/specs/2026-08-24-verbose-runtime-diagnostics.md`

## Task 1 — RED diagnostic schema tests

Files: `tests/test_diagnostics.py`, `tests/test_browser.py`, `tests/test_automation.py`.

- Add tests for process/profile/run context fields.
- Add tests for scan/scroll events with wheel delta, viewport, DOM counts, materialization.
- Add tests for selection evidence.
- Add tests for Trash button/dialog/feedback/result fields.
- Add tests for pending/checkpoint lifecycle fields.
- Add sensitive-data regression assertions.

Run focused tests; confirm RED.

## Task 2 — Diagnostic context and helper APIs

Files: `googlephotos_cleaner/diagnostics.py`, `googlephotos_cleaner/browser.py`.

- Add safe `runtime_context()` and safe locator/DOM count helpers.
- Add structured browser event callback/diagnostic sink without circular imports.
- Log browser start/close, auth, scan attempts, controls, selection, scroll, Trash phases.
- Capture exceptions as type plus sanitized message.
- Ensure no credentials/cookies/page content.

## Task 3 — Automation lifecycle logging

File: `googlephotos_cleaner/automation.py`.

- Log run config/outcome, pending load/policy, checkpoint changes, scan/retry/recovery, selection, Trash result, reset decision, stop/finish.
- Include counters and safe target metadata on every event.
- Keep positive feedback gate and no ambiguous retry unchanged.

## Task 4 — CLI/main logging wiring

Files: `googlephotos_cleaner/cli.py`, `main.py`, README, tests.

- Wire DiagnosticLog into PlaywrightBrowser.
- Add optional diagnostic detail flag only if needed; verbose JSONL default.
- Console logs remain readable but include PID/run/outcome references.
- Final event always includes pending/checkpoint/lock/process summary.

## Task 5 — Verification

```text
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall -q .
git diff --check
```

Inspect generated JSONL for redaction and all lifecycle phases.

## Task 6 — Commit/merge/live dry-run

- Commit worktree and merge after tests.
- Check PID/profile lock before launch.
- Run dry-run bounded with separate artifacts.
- Verify journal explains every failed scan, scroll, DOM materialization, selected target, stop reason, pending/checkpoint, and process close.
- Do not run destructive mode while pending resolution is not explicitly authorized.
