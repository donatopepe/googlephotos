# Safe day scan and Trash reconciliation

## Problem

Live journal shows bounded `day_scan_failed` cycles and real `timeline_advanced` events, but current browser and orchestration code still permit unsafe conclusions:

- when no day checkbox exists, `select_current_day()` returns no target instead of using the allowed single visible photo/video fallback;
- day Trash completion can be inferred from selected-checkbox or dialog disappearance without positive Google Photos feedback;
- pending day actions can be cleared from DOM absence alone and can permit a later Trash click;
- media Trash completion also lacks positive feedback enforcement.

These behaviors risk skipping valid single-photo days or misreporting/repeating destructive actions.

## Scope

Change only browser Trash/selection semantics, pending-action reconciliation, and focused regression tests. Preserve:

- persistent profile `data/browser-profile`;
- one browser/profile owner at a time;
- manual authentication and credential isolation;
- visible-only targeting and real mouse wheel timeline movement;
- bounded day scan failures and `stop_requested` pass termination;
- existing CLI options and day-first default.

## Decisions

### Day selection

1. `select_current_day()` first searches for a currently visible day checkbox.
2. If day checkbox exists, click it once, re-read through a fresh locator, and require `aria-checked="true"`. Failure raises `CleanerError`; it must not fall back to arbitrary media.
3. If no day checkbox exists, select at most one currently visible photo/video checkbox using existing single-media selectors and verify a selected checkbox. Return its accessible label. If no such media exists, return `None`.
4. No navigation, programmatic scroll, or off-screen target reveal is added.

The returned label identifies either a day or a single media target. Existing day-first orchestration may use the same Trash path, but target kind must remain distinguishable for pending journaling/reconciliation.

### Trash confirmation

1. Every destructive Trash method clicks at most once per invocation for each required UI step.
2. A Trash action is successful only when positive Google Photos feedback is visible, using existing localized feedback markers (`Moved to trash`, `Moved to Trash`, `Spostato nel cestino`, `Spostata nel cestino`, `Moved to bin`).
3. Checkbox disappearance, dialog disappearance, or target absence alone is never success.
4. If click outcome is unknown or feedback is absent, return/raise an unresolved result that causes pending journaling and safe stop. No automatic retry occurs in same pass.
5. Existing confirmation-dialog handling remains, but final success still requires positive feedback.
6. Media-batch Trash must apply same positive-feedback rule as day/single-media Trash.

### Pending reconciliation

1. Pending destructive actions remain until positive feedback is observed.
2. `target_exists == False` alone must not clear pending or emit completed/reconciled success.
3. Reconciliation may clear pending only after `wait_for_target_absence()` observes positive feedback, or after an explicit positive retry result that itself observed feedback.
4. A missing target with no positive feedback is `pending_unresolved`; no second Trash click is attempted.
5. Existing explicitly authorized media-batch discard policy remains unchanged and must emit its existing warning event.

### Timeline and stop behavior

- `advance_timeline()` must continue using visible mouse wheel input and configured step/delay.
- Tests must verify scan-failure path calls timeline advance and that browser methods re-query DOM after movement.
- `reset_timeline_to_top()` runs only after confirmed or positively reconciled Trash completion, never after unresolved/ambiguous actions.
- `day_scan_stopped` sets `stop_requested`; `main.py` emits `cleaner_stopped` and exits without calling `Cleaner.run()` again.

## Acceptance

- New tests fail before production changes and pass after them.
- Tests cover missing-day-checkbox single photo and video fallback.
- Tests cover found-but-unverified day checkbox with no fallback.
- Tests cover positive feedback requirement for day and media Trash.
- Tests cover pending target absence without positive feedback: pending preserved, no second click, no reset.
- Tests cover confirmed/reconciled action reset and no reset for unresolved action.
- Tests cover scan failure → real timeline advance and bounded stop.
- Required commands pass in worktree:

```text
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall -q .
git diff --check
```

No live cleaner restart is part of implementation verification. Runtime restart requires separate ownership/lock check and explicit operational action.
