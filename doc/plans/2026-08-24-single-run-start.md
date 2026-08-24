# Single run-start lifecycle plan

1. Add RED test asserting main+Cleaner integration produces one `run_started` event.
2. Remove duplicate main emission or add context handoff without second phase.
3. Full tests, compileall, diff check; update handoff and commit.
4. Inspect PID, lock, pending, checkpoint; no live destructive run.
