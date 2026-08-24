# Stop after unresolved pending Trash

## Problem

After one ambiguous day Trash click, `_run_days()` returns with `day_trash_unresolved` but leaves `Cleaner.stop_requested` false. `main.py` therefore starts another `Cleaner.run()` on the same browser. Pending reconciliation can wait again for feedback, producing repeated `run_started` events and a long/infinite pass loop.

## Decision

Any unresolved pending destructive action must request safe process stop. `main.py` already checks `cleaner.stop_requested` after each pass and emits `cleaner_stopped`; no second pass must start.

Set `stop_requested=True` before returning from:

- pending target absent without positive feedback;
- pending target present without positive feedback;
- current day Trash pending/unresolved after the one allowed click;
- destructive action exception where outcome may be ambiguous.

Preserve pending action and checkpoint state. Do not reset timeline. Do not click Trash again. Existing explicitly authorized media-batch discard remains unchanged; after discard normal scan may continue.

## Acceptance

- RED test proves unresolved pending sets `stop_requested` and preserves pending.
- RED test proves day Trash pending sets `stop_requested`, preserves pending, and does not call reset.
- Existing tests for positive reconciliation still pass and do not request stop.
- Full tests, compileall, and diff check pass.
- Live run shows one `day_trash_pending`/`day_trash_unresolved`, then `cleaner_stopped`, with no following `run_started` for same process.
- Never report Trash completed from DOM absence or missing checkbox.
