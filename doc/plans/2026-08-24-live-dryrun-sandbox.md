# Live dry-run sandbox plan

1. Record current PID/lock/pending/checkpoint and profile owner.
2. Use existing `.venv` with `runuser -u rdpuser`, DISPLAY/XAUTHORITY, bounded dry-run, isolated artifacts.
3. Inspect JSONL phase sequence and exit status.
4. Update handoff with attempted result.
5. No destructive action, no profile ownership changes, no `--no-sandbox`.
