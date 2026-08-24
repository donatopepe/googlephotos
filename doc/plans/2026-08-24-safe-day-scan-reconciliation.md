# Safe day scan and Trash reconciliation

## Context

Worktree: `/home/public/googlephotos/.worktrees/day-checkbox-timeout`  
Base: `e3ce431`  
Spec: `doc/specs/2026-08-24-safe-day-scan-reconciliation.md`

Runtime profile is outside worktree and must not be opened, changed, recreated, or inspected for credentials during implementation. No live cleaner restart in this plan.

## Task 1 — Browser RED tests

Files: `tests/test_browser.py`

1. Add test proving `select_current_day()` calls existing single-photo/video fallback only when `_day_locator()` returns `None`, returns fallback label, and does not navigate.
2. Add test proving missing-day fallback also accepts video selector.
3. Add test proving day Trash returning selected-checkbox disappearance without positive feedback returns unresolved (`False`), without claiming completion.
4. Add test proving day Trash with positive feedback returns `True` even if DOM state is virtualized.
5. Add test proving media-batch Trash requires positive feedback; absence of feedback raises `CleanerError` or returns an explicit unresolved result consistent with current API.
6. Add test proving timeline advance uses wheel and fresh DOM scan tests remain covered.

Run:

```text
python3 -m unittest tests.test_browser
```

Expected RED: new tests fail against current behavior because missing-day fallback is absent and media/day Trash can rely on DOM state.

## Task 2 — Automation RED tests

Files: `tests/test_automation.py`

1. Add fake browser with pending day target absent but `wait_for_target_absence()` returning `False`; assert pending file remains, processed count stays zero, no second delete, and no reset call.
2. Add fake browser whose delete returns `True` without positive feedback only through adapter semantics if needed; assert Cleaner does not reset unless adapter reports confirmed completion. Prefer testing adapter result boundary rather than duplicating browser internals.
3. Add fake browser with confirmed day completion and `reset_timeline_to_top()` spy; assert reset occurs exactly once.
4. Add diagnostic test for scan failure path: `advance_timeline()` called after failed bounded scan, then `stop_requested` after configured failure count; no destructive action.
5. Keep existing `cleaner_stopped` loop behavior covered by source/main test or focused assertion if practical.

Run:

```text
python3 -m unittest tests.test_automation
```

Expected RED: unresolved pending absence currently clears pending; reset gating lacks a test boundary.

## Task 3 — Minimal implementation GREEN

Files: `googlephotos_cleaner/browser.py`, `googlephotos_cleaner/automation.py`, and only supporting tests if API correction requires it.

1. In `select_current_day()`, distinguish missing day control from found-but-unverified day control. Missing control uses `_select_single_media()` and returns its label; found control must fresh-read `aria-checked="true"` and raise on failure. Do not use off-screen or arbitrary selectors.
2. Introduce one internal positive-feedback helper or reuse `_trash_feedback_visible()` for all destructive completion paths.
3. In `delete_selected_day()`, retain existing one-click/confirmation flow, but return `True` only after positive feedback. Any DOM-only disappearance returns `False` and leaves reconciliation to Cleaner.
4. In `move_selected_to_trash()`, after required confirmation, require positive feedback. Missing feedback raises `CleanerError`/`DestructiveActionAmbiguous` path so pending remains and no blind retry occurs.
5. In pending reconciliation, never clear pending from `target_exists == False` alone. Require `wait_for_target_absence()` positive result. If absent without feedback, emit unresolved event and return safely. Ensure no reset is called on unresolved paths.
6. Preserve explicitly authorized `media_batch` discard behavior and warning event.
7. Preserve current `reset_timeline_to_top()` invocation only on confirmed or positively reconciled completion.
8. Do not alter profile lock, authentication, CLI mode defaults, or live data.

Before production code, run the new tests from Tasks 1–2 and confirm RED. Then implement smallest change and rerun focused tests until GREEN.

## Task 4 — Verification gate

From worktree root:

```text
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall -q .
git diff --check
```

Record exact test count and exit status. Inspect diff for credentials, profile operations, duplicate process behavior, and any Trash completion based only on DOM absence.

## Task 5 — Runtime-safe report

Do not start or stop any cleaner from worktree verification. From primary checkout, re-check:

```text
pgrep -af 'googlephotos|main.py'
ps -p 1468404 -o pid,ppid,user,stat,lstart,cmd
ls -l data/pending-action.json data/checkpoint.json data/run.jsonl
```

Report PID ownership, latest journal phases, pending state, and checkpoint. Never claim Trash completed from DOM disappearance or checkbox absence.
