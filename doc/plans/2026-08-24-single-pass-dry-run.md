# Single-pass dry-run and runtime stop semantics

## Context

Worktree `/home/public/googlephotos/.worktrees/day-checkbox-timeout`, base `f53ff87`.

Live dry-run evidence: one day was found and checkpointed, then `run_started` repeated because `Cleaner.stop_requested` stayed false. The process was stopped after verifying PID `1489919` owned profile lock. No profile recreation.

## Task 1 — RED tests

File: `tests/test_automation.py`

1. Add dry-run day-mode test with `max_batches=1`: one day processed, no Trash, `stop_requested=True`.
2. Add media-first test with `max_batches=1`: one media batch processed, no unintended second scan, `stop_requested=True`.
3. Preserve unresolved pending stop tests.

Run focused tests and observe RED because current successful max-batch paths do not set stop.

## Task 2 — Minimal implementation

File: `googlephotos_cleaner/automation.py`

After successful day/media processing and checkpoint, if `max_batches` is not `None` and `processed >= max_batches`, set `stop_requested=True` before returning. Keep existing `batch_limit` behavior for media mode. Do not stop unbounded normal idle paths.

## Task 3 — Verification

```text
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall -q .
git diff --check
```

## Task 4 — Commit, merge, live dry-run

Commit and merge to `main`. Run one dry-run using existing profile and a separate checkpoint/log/diagnostics path, with `--max-batches 1`. Verify one `run_started`, one successful day selection/checkpoint, then `cleaner_stopped`, no second pass. Stop only after PID/lock ownership verification. Then report PID, journal, pending, checkpoint.
