# Single run-start lifecycle event

## Goal

Eliminate duplicate `run_started` events in real `main.py` invocations while retaining complete Cleaner diagnostics for direct use.

## Requirements

- Every real invocation that reaches Cleaner emits exactly one `run_started` event.
- `run_started` contains full runtime context: process identity, mode, pending/checkpoint paths, profile/lock context, retry/scroll/idle limits and pending policy/timeout.
- `main.py` must not emit a second `run_started` before Cleaner emits its event.
- Direct `Cleaner` use retains one `run_started` event by default.
- Existing terminal lifecycle remains one `cleaner_stopped` and one `run_finished`.
- No profile mutation, credential handling, process action, browser launch, or destructive Trash action during implementation.
