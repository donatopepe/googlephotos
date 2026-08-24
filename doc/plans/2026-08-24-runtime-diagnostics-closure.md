# Runtime diagnostics closure plan

## 1. RED tests

Add failing tests for:

- `main.run` invokes one bounded Cleaner pass and does not re-enter loop after `PASS_DONE`, `STOP_SAFE`, pending unresolved, or destructive ambiguous.
- exactly one terminal `cleaner_stopped`/`run_finished` sequence.
- runtime event context includes pid/uid/user/profile/lock owner, pending/checkpoint paths, limits, outcome.
- exception events include sanitized message and recovery result.
- selection event includes actual chosen selector and candidate/visible counts.
- media and day Trash events include positive feedback and result.
- handoff consistency checks via generated runtime snapshot if practical.

Run focused tests and confirm RED.

## 2. Implement

- Add safe process context helper in diagnostics.
- Extend Cleaner event context and terminal event ownership.
- Replace `main` unbounded loop with one pass; use `last_outcome` and emit terminal summary once.
- Pass configured timeout through all pending reconciliation paths.
- Add browser event fields without raw DOM/page content.
- Keep raw error artifacts out of journal and clearly document privacy boundary.

## 3. Handoff

Rewrite `/home/public/googlephotos/HANDOFF-2026-08-24-googlephotos-scan.md` from verified repository/runtime facts:

- current main commit and feature worktree commit;
- exact test count/result and commands;
- PID 1869 unrelated, lock absent, pending absent, checkpoint current;
- no destructive live test;
- remaining merge/live dry-run steps.

Do not commit data/profile artifacts. Handoff may remain untracked per repository state.

## 4. Verify

```text
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall -q .
git diff --check
```

Inspect git status, worktree, process list, lock, pending, checkpoint, and journal. No destructive launch.
