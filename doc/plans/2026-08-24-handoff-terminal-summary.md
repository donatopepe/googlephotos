# Handoff and terminal summary repair plan

1. RED tests for `cleaner_stopped`/`run_finished` required fields.
2. RED test for handoff current commit and no contradictory current-status lines.
3. Implement shared terminal context in `main.py`; reuse for both events.
4. Update handoff current commit/runtime facts; keep historical events under history.
5. Full unittest, compileall, diff check; inspect process/lock/pending/checkpoint.
