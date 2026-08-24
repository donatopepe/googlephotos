# Stop repeated scan-failed pass loop

## Problem

`Cleaner._run_days()` now returns safely after bounded day-scan failures, but `main.py` unconditionally calls `cleaner.run()` inside `while True`. This immediately starts another pass and creates an endless retry loop.

## Fix

Return an explicit pass status from `Cleaner` or add a bounded stop signal without changing destructive semantics. Simplest compatible design: `Cleaner` sets `stop_requested=True` when it reaches `day_scan_stopped`; `main.py` exits its pass loop when that flag is set. Existing pending Trash reconciliation remains unchanged.

## Acceptance

- Failing test proves `Cleaner.run()` records stop state after scan failure bound.
- Main loop test or focused source-level test proves no immediate second `Cleaner.run()` after stop.
- Existing 71-test suite remains green.
- Runtime log has one `day_scan_stopped` followed by process exit, not repeated `run_started`.
