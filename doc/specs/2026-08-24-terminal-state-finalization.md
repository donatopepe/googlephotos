# Terminal state finalization

## Goal

Fix remaining lifecycle ambiguity and update handoff without live destructive actions.

## Requirements

- `Cleaner` emits internal stop evidence only; `main` emits one public `cleaner_stopped` summary.
- Public `cleaner_stopped` summary must exist for normal, pending, safe-stop, and ambiguous outcomes.
- `run_finished` always carries final outcome, including initialization failure, keyboard interrupt, and close failure.
- Normal `run_started` context remains complete and redacted.
- No second pass or browser reopen.
- Handoff must name newest commit and fresh runtime facts.

## Safety

No profile deletion/recreation. No credential handling. No touching unrelated PID 1869. No destructive live run or Trash retry.
