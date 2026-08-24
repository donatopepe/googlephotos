# Runtime diagnostics closure and handoff repair

## Request

Resolve remaining gaps, update handoff, correct implementation, continue safely.

## Findings to close

1. `main.py` may emit duplicate `cleaner_stopped`: `Cleaner` now emits one, then `main` emits another. One run must have one terminal stop event.
2. `main.py` loops on `while True` and does not use `last_outcome` as terminal state. It must end after each bounded/safe outcome and log one terminal result.
3. Runtime context lacks `uid`, username, lock owner PID, idle/failure limits, and safe checkpoint/pending paths in required events.
4. Browser diagnostics call `page.content()` for error artifacts. Journal itself must remain safe, but artifacts need explicit handling and must not be advertised as raw HTML-safe.
5. Some exception events log only type, not sanitized diagnostic message/recovery status.
6. `_first_viewport_control` now records chosen selector but selection events need candidate/visible counts and label/aria evidence consistently.
7. Media Trash and day Trash events need consistent positive-feedback result fields.
8. Existing handoff is stale and truncated: it references old branch/commit, old test count, old pending/checkpoint state, and does not describe verbose diagnostics worktree.

## Safety invariants

- Do not touch `/home/public/googlephotos/data/browser-profile` contents.
- Do not read credentials or log cookies/passwords/tokens/raw page content.
- Do not start or stop PID 1869; it is unrelated process.
- Do not run destructive Google Photos action.
- No automatic Trash retry after ambiguous outcome.
- Preserve pending/checkpoint behavior.

## Acceptance

- One `run_started`, one terminal `cleaner_stopped`/`run_finished` per invocation.
- `main` exits based on `last_outcome` / `stop_requested`; no unbounded loop after bounded pass.
- Events contain process/profile/lock/pending/checkpoint/config/outcome context.
- Selection, scroll, DOM, fallback, Trash feedback and timeout evidence remain structured and redacted.
- Handoff accurately reports current main, worktree, commits, tests, runtime PID/lock/pending/checkpoint, and explicitly says no destructive test completed.
- Full tests, compileall, diff check pass.
