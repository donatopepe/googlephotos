# Terminal journal contract plan

## RED

- Add `main.run` test with fake Browser/Cleaner and inspect JSONL phases.
- Assert exactly one `run_started`, one `cleaner_stopped`, one `run_finished`.
- Assert failure path has `run_failed` and `run_finished(outcome=failed)`.
- Assert Cleaner terminal internal event does not use public phase.
- Assert handoff references current closure commit and no merge/live destructive test.

## Implement

- Add terminal event helper in `main.py`.
- Set `run_outcome` for normal, KeyboardInterrupt, and handled errors.
- Ensure browser close errors do not prevent `run_finished`.
- Keep Cleaner internal event names distinct.
- Add safe context to all terminal events.

## Verify and handoff

```text
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall -q .
git diff --check
```

Update handoff after fresh PID/lock/pending/checkpoint inspection. Do not launch live destructive mode.
