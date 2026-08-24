# Live dry-run sandbox and profile ownership

## Finding

A root-run dry-run with `.venv/bin/python` reaches Playwright but Chromium refuses sandbox startup. Persistent profile is owned by `rdpuser:rdpuser` mode 700. Existing Chromium processes use unrelated profile paths.

## Safe resolution

Run one bounded `--dry-run --max-batches 1` as `rdpuser`, with existing persistent profile and existing display, without changing profile ownership or sandbox flags. Use isolated `/tmp` journal/checkpoint/diagnostics paths. Verify no profile lock or project cleaner process before launch.

## Acceptance

- No root process touches profile contents.
- No duplicate project cleaner.
- Dry-run exits safely with journal evidence.
- If auth/session or DOM blocks progress, report exact phase and stop; do not switch to destructive mode.
- Do not use `--no-sandbox` or disable Chromium sandbox.
