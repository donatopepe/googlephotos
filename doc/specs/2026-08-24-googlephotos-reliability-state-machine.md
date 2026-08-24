# Google Photos reliability state machine

## Goal

Implement handoff P0 reliability fixes without touching live profile data during development:

- pending action cannot silently block or loop;
- bounded runs have explicit terminal outcome;
- day/media fallback uses correct destructive API and pending kind;
- Trash completion requires positive Google Photos feedback;
- main loop cannot restart after safe stop;
- runtime evidence remains observable.

## Scope for this wave

1. Add explicit `PassOutcome` values for `CONTINUE`, `PASS_DONE`, `STOP_SAFE`, `PENDING_UNRESOLVED`, and `DESTRUCTIVE_AMBIGUOUS`.
2. Make `Cleaner.run()` expose outcome while preserving integer processed return compatibility through a separate `last_outcome` attribute.
3. Make all terminal unresolved/ambiguous paths set outcome and stop state consistently.
4. Add CLI `--pending-action` policy with choices `block` (default), `inspect`, and `discard`.
   - `block`: preserve pending, emit unresolved, stop immediately without 30-second browser polling.
   - `inspect`: same safe block, explicit inspect event; no destructive action.
   - `discard`: explicit user authorization, clear pending, emit warning event, continue; never infer completion from DOM.
5. Add `--pending-timeout-ms` positive bounded option for any explicitly requested reconciliation wait.
6. Ensure `main.py` exits after any terminal outcome and does not call `Cleaner.run()` again.
7. Add integration-style tests around `main.run()` with fake browser/cleaner seams if feasible; otherwise test loop helper extracted from main.
8. Update README pending semantics and operational runbook.

## Deferred to next wave

- Full `SelectionTarget` typed object and separate `delete_selected_media()` browser API.
- DOM before/after evidence payload for timeline scroll.
- Formal checkpoint enum migration beyond current states.
- Real-account destructive run.

## Safety

- No profile deletion/recreation.
- No credential access.
- No live cleaner launch during implementation.
- No automatic Trash retry.
- No success from DOM/checkbox absence alone.
- Existing pending file remains untouched by tests; tests use temporary paths.

## Acceptance

- Tests demonstrate block/inspect/discard pending policies.
- Tests demonstrate terminal outcome and no second pass.
- Tests demonstrate bounded dry-run stops after one batch.
- Tests demonstrate positive Trash feedback requirements remain intact.
- Full required tests, compileall, and diff check pass.
- Live test, if run after merge, uses dry-run and separate checkpoint/log paths first.
