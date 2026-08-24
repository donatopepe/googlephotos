# Runtime proof audit

## Goal

Close remaining observability gaps before any merge or live test.

## Findings

- `run_started` in `main.py` has only mode/process fields while Cleaner emits another `run_started` when used directly; public CLI lifecycle is one, but run context should be complete in main event.
- `run_finished` lacks explicit profile/lock owner and browser close result.
- Media `trash_completed` lacks positive feedback/result fields at Cleaner level.
- Day reconciliation currently treats `wait_for_target_absence()` true as confirmed even though adapter contract says positive feedback; event must carry explicit `positive_feedback` evidence.
- Handoff repeatedly accumulates historical “current” markers; replace with a single current-status block plus history.

## Safety

No profile changes, no credentials, no PID 1869 action, no destructive live run, no automatic Trash retry.
