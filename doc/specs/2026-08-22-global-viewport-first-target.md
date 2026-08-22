# Global viewport-first target selection

## Problem
`select_current_day()` first searches day controls and only then searches single-media controls. A lower day control can therefore be selected before a photo/video tile that is higher or further left in same current viewport.

## Requirement
Select exactly one first unselected Google Photos target from current viewport, whether it is a day-group checkbox or single photo/video checkbox. Order all eligible targets globally by visible position: top-to-bottom (`y`), then left-to-right (`x`).

## Safety constraints
- No scrolling, `scrollTop` changes, `Locator.hover()`, or action that brings an off-screen target into view.
- Candidate needs an already-visible non-zero ancestor. Pointer move may only stay within that ancestor to reveal Google Photos zero-size checkbox.
- Exclude target whose revealed checkbox is not in viewport or is already selected.
- Never change Trash/pending-action reconciliation behavior.
- Do not recreate, remove, close, or mutate browser profile/cookies.

## Design
1. Extend viewport-control scan to accept tagged selector groups (`day`, `media`) and return candidate metadata: kind, locator, accessible label, and ordering position.
2. Scan every day and media selector before making a selection; deduplicate DOM controls matched by overlapping selector sets.
3. Sort candidate union by ancestor/target visible top-left position (`y`, then `x`); choose only first.
4. `select_current_day()` dispatches only selected candidate kind: day handling preserves verified day selection plus its local media fallback; media handling verifies selected media. It must not preempt a first media merely because any day checkbox exists.
5. Write non-sensitive structured selector diagnostic event including candidate kind, labels, coordinates, selected first candidate, and count; no DOM content, URLs, cookies, or screenshots required.
6. Tests cover global cross-kind ordering, tie order, already-selected exclusion, current day behavior, and no-scroll/pointer-only reveal invariant.

## Acceptance
A media at `(100, 100)` is selected before a day control at `(200, 100)`; a day at `(100, 100)` is selected before a media at `(200, 100)`. Existing ordering and recovery tests pass. Live session remains untouched until tested code requires controlled restart, which is out of scope until explicit implementation execution.