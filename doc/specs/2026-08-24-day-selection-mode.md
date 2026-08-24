# Explicit day-first selection mode

## Problem

`main.py` currently derives `day_mode` from `args.selection_size == 1`. With the operational configuration `--selection-size 100`, Cleaner skips `select_current_day()` and directly selects individual media. This violates day-first behavior and prevents the visible day checkbox from being clicked.

## Decision

Make day-first selection explicit and independent of batch capacity. Default cleaner runs remain day-first. `--selection-size` controls only the maximum number of media selected in media-batch mode or future fallback behavior; it must not disable day selection.

## Behavior

- Startup with `--selection-size 100` enters day-first mode.
- Cleaner calls `select_current_day()` before `delete_selected_day()`.
- Browser clicks only a currently visible day checkbox.
- Browser verifies `aria-checked="true"` after click; failure is safe and non-destructive.
- Dynamic media checkbox scans refresh candidates after every click and skip controls whose current `aria-checked` is not `false`.
- Existing pending ambiguous actions remain protected. Restart may discard an ambiguous media batch only through existing explicit policy; no prior Trash action is retried.
- No profile recreation, credential handling, or duplicate browser ownership.

## Interface

Add an explicit CLI switch to select media-first mode, while defaulting to day-first:

```text
--media-first
```

`main.py` passes `day_mode=not args.media_first` to `Cleaner`.

## Acceptance

- A unit test proves `--selection-size 100` keeps `day_mode=True` by default.
- A unit test proves `--media-first` sets `day_mode=False`.
- Browser/automation tests prove day checkbox click and positive checked-state verification.
- Full existing suite passes.
- Live journal after restart contains day-first lifecycle event before destructive day action.
