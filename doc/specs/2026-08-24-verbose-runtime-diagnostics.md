# Verbose runtime diagnostics

## Goal

Make `data/run.jsonl`, `data/run.log`, and console output contain enough structured evidence to diagnose scan, scroll, DOM materialization, selection, Trash, pending, checkpoint, process, profile lock, and browser lifecycle without guessing.

## Safety

- Never log credentials, cookies, tokens, authorization headers, page content, media URLs, or raw HTML.
- URLs remain redacted.
- Do not alter persistent profile behavior.
- Do not add destructive retries.
- Tests use fakes/temp paths; no live browser during implementation.

## Required evidence

### Run/process context

At `browser_started` and `run_started`, log:

- `pid`, `ppid`, `uid`, username;
- normalized `profile_dir` (path only, no contents);
- `profile_lock_path`, `profile_lock_owner_pid`, `profile_lock_owned`;
- command mode, pending policy, pending timeout, max batches/retries, scroll step/delay, idle/failure limits;
- browser URL redacted, page count if available.

At `cleaner_stopped`, `run_finished`, `run_failed`, and browser close, log:

- outcome, stop_requested, processed batches/days, photos;
- checkpoint path/state if available;
- pending path, exists, kind/label redacted-safe, pending action status;
- browser/page/context close state.

### Scan and scroll

For each day scan attempt log:

- attempt/max attempts;
- selector names checked;
- visible day-control count before/after pointer reveal;
- visible media count;
- chosen control kind, label, aria-checked before/after;
- bounding box/viewport ordering without media data;
- exception type/message sanitized and recovery result.

For each scroll log:

- direction, x/y wheel delta, configured step/delay;
- pointer coordinates and viewport dimensions;
- scan attempt/idle/failure counters;
- DOM counts before and after wait;
- whether day/media labels changed and count delta;
- `materialized=true|false`.

### Selection

Log selection start/result:

- kind day/media;
- selector used;
- candidate count, selected count before/after;
- label safe/redacted, media count only;
- click attempted, click completed, aria-checked verification;
- failure reason.

### Trash

Log every phase without claiming success early:

- target kind/label/count;
- action button names checked and visible counts;
- selected count before click;
- primary click timestamp/result;
- dialog count/confirmation button candidates;
- confirmation click timestamp/result;
- selected count after each wait;
- positive feedback strings checked and matched string category (not full page text);
- result enum `confirmed`, `pending`, `ambiguous`, `unavailable`;
- retry count (must stay zero after ambiguous action);
- reset timeline decision and reason.

`trash_completed` is legal only with `result=confirmed` and positive feedback evidence.

### Pending/checkpoint

Log every load/save/clear/reconcile:

- path, exists before/after;
- kind, safe label, count;
- policy (`block`, `inspect`, `discard`);
- reason and positive feedback status;
- checkpoint state/batch/photos before/after;
- no DOM absence alone as completion.

## CLI

Add `--verbose-diagnostics` (default enabled for JSONL; console remains concise) and `--diagnostics-detail {normal,verbose}` if useful. Default JSONL must remain verbose enough for incident analysis.

## Acceptance

- RED tests assert representative events include required evidence fields.
- Browser fake tests assert scroll logs include wheel and DOM before/after counts.
- Automation fake tests assert selection/Trash/pending/checkpoint lifecycle events.
- Sensitive data tests assert no password/cookie/token/raw page content.
- Full suite, compileall, diff check pass.
- Live dry-run after merge shows detailed scroll, scan, selection, outcome evidence and no duplicate process.
