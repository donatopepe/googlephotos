# Day-selection mode fix

## Scope

Make day-first selection independent from `--selection-size`, so a run configured with `--selection-size 100` still clicks and verifies the visible Google Photos day checkbox before destructive work. Preserve safe handling of preselected media, ambiguous Trash results, and existing profile/session behavior.

## Tasks

1. **Add failing CLI/config test**
   - Update tests to express explicit day-first behavior rather than deriving `day_mode` from selection size.
   - Expected red test: `--selection-size 100` passes day-first mode to `Cleaner`.

2. **Add failing automation/browser tests**
   - Verify day-first adapter path calls `select_current_day()` and `delete_selected_day()`.
   - Verify day selection reads checkbox state after click and rejects unverified selection.
   - Verify already checked media are excluded when dynamically refreshing checkbox candidates.

3. **Implement minimal production fix**
   - Add explicit CLI flag/config with safe default day-first behavior.
   - Pass explicit `day_mode` from `main.py`; stop coupling it to `selection_size`.
   - Keep `--selection-size` as batch capacity only.
   - Improve day checkbox lookup/click verification using current visible controls and refreshed `aria-checked` state.

4. **Run focused tests, then full suite**
   - `python3 -m unittest tests.test_cli tests.test_automation tests.test_browser`
   - `python3 -m unittest discover -s tests -p 'test_*.py'`
   - `python3 -m compileall -q .`
   - `git diff --check`

5. **Operational restart**
   - Stop current cleaner only after code/test verification.
   - Verify no Chromium owns persistent profile and stale lock PID is dead.
   - Start one cleaner with `--selection-size 100 --max-idle-scrolls 30`.
   - Require lifecycle evidence `day_selection` (or `day_scan`/`day_trash_started`) before claiming day click works.
   - Do not retry current ambiguous `batch:3`; user-authorized discard-on-restart policy applies only after authenticated startup.
