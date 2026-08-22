# Plan: global viewport-first target selection

1. Add failing `tests/test_browser.py` unit tests with mocked day/media controls showing cross-kind top-left ordering and exclusion of selected/offscreen controls.
2. Refactor `googlephotos_cleaner/browser.py` scanner to collect tagged candidates from day and single-media selector groups in one pass, retaining visible-parent-only pointer reveal and global `(y, x)` sort.
3. Dispatch `select_current_day()` by winning candidate type; preserve post-click verification and current safe media fallback only after the selected day fails verification.
4. Add minimal redacted candidate-selection journal event through existing diagnostics/logging mechanism, or document why browser adapter cannot access runtime journal and inject callback cleanly.
5. Run `python3 -m unittest discover -s tests -p 'test_*.py'` and `python3 -m compileall -q .`; inspect diff.
6. Only after green verification, coordinate controlled restart preserving existing profile/browser if live deployment is needed. Never restart while pending action exists.
