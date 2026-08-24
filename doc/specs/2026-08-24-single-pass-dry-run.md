# Single-pass dry-run and runtime stop semantics

## Problem

A dry-run with `--max-batches 1` successfully processes one visible day but `main.py` starts another `Cleaner.run()` because `stop_requested` remains false. This makes bounded tests unexpectedly continue scanning and keeps the browser/profile locked. The same loop must remain safe for production unresolved pending actions.

## Decision

`Cleaner` exposes explicit pass completion state for bounded modes. When `max_batches` is reached after a successful day/media pass, set `stop_requested=True` and emit existing limit/checkpoint event before returning. `main.py` then emits `cleaner_stopped` and exits the single browser pass.

Do not set stop for normal unbounded idle scanning unless existing safety stop already does so. Do not alter destructive confirmation rules, pending journals, profile lock behavior, or persistent profile.

## Acceptance

- RED test: dry-run with `max_batches=1` processes one day and sets `stop_requested=True`.
- RED test: media-first `max_batches=1` also stops after one batch.
- Existing unresolved pending tests remain safe and stop.
- Live dry-run creates one `run_started`, one successful selection/checkpoint, then `cleaner_stopped`; no second `run_started`.
- Full tests, compileall, diff check pass.
