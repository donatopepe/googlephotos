# Google Photos reliability state machine

## Context

Worktree: `/home/public/googlephotos/.worktrees/googlephotos-reliability`  
Base: `aee8e71`  
Spec: `doc/specs/2026-08-24-googlephotos-reliability-state-machine.md`

## Task 1 — RED: outcome and pending policy tests

Files: `tests/test_automation.py`, `tests/test_cli.py`, `tests/test_main.py` (new if needed).

- Test `Cleaner.last_outcome` becomes `PENDING_UNRESOLVED` when pending blocks.
- Test block policy performs no 30-second wait and preserves pending.
- Test inspect policy emits explicit inspect event and preserves pending.
- Test discard policy clears only with explicit policy and emits warning.
- Test bounded day/media run outcome is `PASS_DONE` and stop requested.
- Test main loop invokes one pass for terminal outcome.

Run focused tests. Confirm RED before production edits.

## Task 2 — Implement outcome/policy core

Files: `googlephotos_cleaner/automation.py`, `googlephotos_cleaner/cli.py`, `main.py`.

- Add `PassOutcome` enum/string constants.
- Add `Cleaner.last_outcome`, `pending_policy`, `pending_timeout_ms` validation.
- Replace implicit pending wait on default `block` with immediate safe stop.
- Implement `inspect` and explicit `discard` behavior.
- Set outcome on every safe/ambiguous/finished path while preserving integer return compatibility.
- Main loop exits for terminal outcomes; no second `Cleaner.run()`.
- Keep no Trash retry and no DOM-only success.

## Task 3 — Tests GREEN and docs

- Add/update README pending semantics: target absence is not completion, pending policy commands, bounded timeout.
- Add focused tests for all new branches.
- Ensure existing 87 tests remain green.

## Task 4 — Verification

From worktree:

```text
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall -q .
git diff --check
```

## Task 5 — Commit/merge/live dry-run

- Commit worktree changes.
- Merge to main only after verification.
- Before live test inspect PID/profile lock/pending/checkpoint/journal.
- Run dry-run with separate checkpoint/log/diagnostic paths and `--pending-action block` first.
- Verify one `run_started`, terminal event, no duplicate pass, no profile mutation.
- Do not run destructive mode while production pending remains unresolved.
