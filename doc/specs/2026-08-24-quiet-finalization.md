# Quiet finalization

## Goal

Remove the remaining noisy test/runtime behavior and keep the handoff precise.

## Requirements

- Diagnostic capture failures in tests and runtime are journaled but do not emit misleading console noise unless the real run is already failing.
- Handoff current block names exactly one current worktree commit and one test count; historical counts stay under history.
- `wait_for_target_absence` remains positive-feedback-only.
- Full verification remains clean; no profile/PID/Trash mutation.
