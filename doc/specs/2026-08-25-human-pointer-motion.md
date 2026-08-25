# Human-like pointer motion for Google Photos scanning

## Goal

Improve reliable Google Photos selection after timeline scrolling by moving the real browser pointer through visible content before and during checkbox materialization, without bypassing Playwright’s normal interaction safety.

## Scope

Modify `googlephotos_cleaner/browser.py` and focused browser tests. Add bounded pointer trajectories around already-visible parent boxes and viewport content. Preserve persistent profile, pending/checkpoint behavior, positive Trash proof, and no-retry-after-ambiguous-action policy.

Out of scope: JavaScript clicks, `force=True`, programmatic DOM mutation, credential handling, stealth fingerprinting, CAPTCHA bypass, or arbitrary page-content capture.

## Design

Add an internal helper that moves the mouse through a short deterministic, human-like path: an intermediate point near the visible parent, the parent hover point, then a point near the visible checkbox target. Each point must be inside the current viewport and derived only from safe bounding boxes. Use bounded waits between movement and materialization checks. No `Locator.hover()` is required; direct visible `page.mouse.move()` keeps pointer behavior explicit and avoids implicit scrolling.

Use helper during `_first_viewport_control()` before reading the final candidate box and before selecting the top-left candidate. Keep retries bounded at three materialization attempts per candidate. Emit safe diagnostics with `pointer_moves`, `pointer_path_steps`, `materialization_attempts`, and existing viewport/count fields; do not log DOM text, HTML, classes, IDs, URLs, or media content.

Enhance `advance_timeline()` with a short movement from viewport center toward a nearby content point before wheel and a post-wheel movement back into content. Existing wheel and DOM materialization diagnostics remain.

Before Trash click, require a positive selected count and visible action button. Emit `trash_action_unavailable` and raise `CleanerError` before `trash_click_started` if no action button exists; never record a misleading click-start event for a non-click.

## Tests and acceptance

Add tests for pointer path execution, bounded materialization retry, overlay/non-materialization failure, scroll pointer movement, and no Trash click when selected count is zero/action button missing. Preserve existing tests for normal selection and positive popup parsing.

Required verification:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall -q .
git diff --check
```

No live destructive run during implementation. Later live run must use `rdpuser`, persistent profile, verified lock ownership, and explicit pending handling.

## Documentation impact

- Feature/user-facing documentation introduced: none; this is internal interaction reliability.
- Materially amended documentation: `/home/public/googlephotos/HANDOFF-2026-08-24-googlephotos-scan.md` after a later live run, recording pointer-motion diagnostics only.
- Derived/memory invalidated: none.

## Open questions

None. User approved bounded pointer motion with no browser safety bypass.
