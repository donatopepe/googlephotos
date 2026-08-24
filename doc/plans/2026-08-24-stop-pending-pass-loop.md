# Stop after unresolved pending Trash

## Context

Worktree: `/home/public/googlephotos/.worktrees/day-checkbox-timeout`  
Base: `c02eef8`  
Spec: `doc/specs/2026-08-24-stop-pending-pass-loop.md`

Current runtime has pending day action:
`Seleziona tutte le foto a partire da: dom 16 giu 2019`.
No profile recreation or credential handling. Do not start cleaner during implementation.

## Task 1 — RED tests

File: `tests/test_automation.py`

1. Add test where pending target is absent but `wait_for_target_absence()` returns false. Assert `stop_requested=True`, pending remains, no delete/reset.
2. Add test where current `delete_selected_day()` returns false and reconciliation returns false. Assert `stop_requested=True`, pending/checkpoint remain, no reset.
3. Add test where Trash adapter raises after click. Assert `stop_requested=True`, pending remains, no retry/reset.
4. Keep positive reconciliation tests asserting `stop_requested=False` and normal processing.

Run focused tests and confirm RED: current unresolved paths return with `stop_requested=False`.

## Task 2 — Minimal implementation

File: `googlephotos_cleaner/automation.py`

Set `self.stop_requested = True` immediately before each unresolved destructive return:

- pending target absent without feedback;
- pending target present without feedback;
- current-day Trash unresolved after one click;
- destructive action exception.

Preserve existing events, pending file, checkpoint state, and no-reset behavior. Do not set stop on normal positive reconciliation or explicitly authorized media-batch discard.

## Task 3 — Verification

From worktree:

```text
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall -q .
git diff --check
```

Expected full suite count >= 84, zero failures.

## Task 4 — Integrate and runtime recovery

After verification, commit and merge to `main`. Before restarting:

1. `pgrep/ps` active process check;
2. verify profile lock owner and PID;
3. current pending/checkpoint/journal report;
4. stop only owned stale PID if live;
5. restart one `rdpuser` instance with existing profile and exact operational flags.

Expected live behavior on unresolved Trash:
`day_trash_pending` → `day_trash_unresolved` → `cleaner_stopped`, then process exit; no second `run_started`.
