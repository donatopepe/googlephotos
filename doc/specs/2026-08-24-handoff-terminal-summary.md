# Handoff and terminal summary repair

## Goal

Resolve remaining stale documentation and lifecycle reporting gaps. Keep code safe for Google Photos, with no live destructive action.

## Required behavior

- Handoff names newest worktree commit exactly.
- Handoff has one current merge status statement, one current runtime snapshot, and no stale claims presented as current.
- `main` writes one `cleaner_stopped` summary and one `run_finished` summary per invocation.
- `cleaner_stopped` includes process identity, profile/lock, pending/checkpoint paths and existence, outcome, stop state, processed count.
- `run_finished` includes same operational context plus browser-open state.
- `run_failed`, KeyboardInterrupt, and close failure produce final outcome.
- Tests cover summary fields and stale handoff marker prevention.

## Safety

Do not touch persistent browser profile. Do not touch PID 1869. Do not run destructive Google Photos operation. Do not merge to main automatically.
