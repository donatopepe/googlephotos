# Terminal journal contract

## Goal

Make one invocation produce unambiguous lifecycle evidence and keep handoff current without touching persistent profile or running destructive Google Photos actions.

## Required contract

Each normal invocation:

1. one `run_started`;
2. zero or more operational events;
3. one `cleaner_stopped` summary with `outcome`, `stop_requested`, `processed`, pending/checkpoint state;
4. one `run_finished` with same run id, outcome, processed, browser state, pending/checkpoint paths and existence.

Failure invocation:

1. one `run_started` if browser/cleaner initialization reaches it;
2. one `run_failed` with sanitized type/message/recovery;
3. one `run_finished` with `outcome=failed`.

`Cleaner` may emit internal `cleaner_terminal_state` events for safe-stop branches, but must not emit public `cleaner_stopped`; `main` owns public terminal summary.

## Safety

- No unbounded `main` loop or second Cleaner pass.
- Re-entry after terminal Cleaner outcome returns without `run_started`.
- No automatic Trash retry after ambiguity.
- Positive Google Photos feedback remains required.
- No credentials/cookies/tokens/raw page content in journal.
- Preserve `/home/public/googlephotos/data/browser-profile`.
- Do not touch unrelated PID 1869.

## Handoff

Update handoff with exact current commits, worktree status, verification result, PID/lock/pending/checkpoint snapshot, and explicit no-destructive-test status.
