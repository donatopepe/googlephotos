# Terminal state finalization plan

1. RED: add tests for Cleaner `STOP_SAFE`/pending/ambiguous outcomes and main public summary cardinality.
2. RED: add test that `run_finished.outcome` is present on KeyboardInterrupt/close failure.
3. Implement centralized `emit_terminal_summary` in `main.py` and guarantee final outcome assignment.
4. Normalize Cleaner stop events and include `error_message` in ambiguous Trash event.
5. Update handoff with current commit and runtime snapshot.
6. Run full unittest, compileall, diff check; inspect PID, lock, pending, checkpoint. No destructive launch.
