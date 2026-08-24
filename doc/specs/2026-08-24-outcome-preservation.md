# Outcome preservation on handled failures

## Goal

Ensure the public terminal journal preserves the Cleaner safety outcome when a bounded/destructive operation raises after setting it, instead of flattening every exception to `failed`.

## Requirements

- If `Cleaner.last_outcome` is `DESTRUCTIVE_AMBIGUOUS`, `PENDING_UNRESOLVED`, or `STOP_SAFE` when `run()` raises, `run_failed` may record the exception but terminal `cleaner_stopped` and `run_finished` must retain that outcome.
- Generic initialization/runtime exceptions without a Cleaner outcome remain `failed`.
- `stop_requested` is true for preserved safe-stop/ambiguous outcomes.
- No automatic retry, profile change, or live destructive action.
- Handoff records the corrected commit and verification.
