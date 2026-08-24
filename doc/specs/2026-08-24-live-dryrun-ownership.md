# Live dry-run ownership result

## Result

- Root attempt failed safely before browser launch because Playwright was unavailable in system Python.
- Profile-owner attempt used `rdpuser`, existing profile, existing display, and venv Playwright.
- Chromium launched, auth succeeded, day scan found `gio 13 giu 2019`, but day checkbox click timed out because resolved control was not visible.
- Bounded retry/scroll began; process ended unexpectedly before terminal summary, leaving stale lock JSON with dead PID `1519761`.
- Stale lock was removed only after `kill -0` confirmed owner dead. No live owner remained. No Trash action occurred.

## Follow-up

Fix visibility/materialization path before another live dry-run. Do not infer Trash success from this run. Keep destructive mode disabled.
