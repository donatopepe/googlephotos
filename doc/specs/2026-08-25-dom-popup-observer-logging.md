# DOM popup observer logging

## Goal

Make the Google Photos Trash-feedback observer diagnosable when the visible bottom-left toast is present but the current text locator does not find it. The observer must expose safe DOM/accessibility metadata while preserving the existing fail-closed proof contract.

## Scope

The change is limited to `googlephotos_cleaner/browser.py` and its unit tests. It adds metadata-only observation of candidate live regions before the existing quantity-bearing text fallback. It does not change Trash click behavior, pending/checkpoint transitions, retry policy, profile handling, or live-run procedure.

Out of scope: capturing HTML, page content, accessibility snapshots, screenshots, raw popup text, URLs, media identifiers, cookies, headers, credentials, or an operator-attestation mechanism.

## Design

`PlaywrightBrowser` will inspect these selector groups, in order, using ordinary Playwright locators:

- `[role="status"]`
- `[role="alert"]`
- `[aria-live]`

Overlapping matches are allowed for diagnostics but must not cause duplicate completion. Each group produces a `trash_feedback_dom_observation` event containing only `selector_group`, `selector_kind`, `matched_count`, `visible_count`, and safe normalized role/live-region metadata. Candidate failures produce `trash_feedback_dom_observation_failed` with selector identity and exception type only; exception messages are excluded because they may contain page text.

Role and `aria-live` values are reduced to safe enums (`status`, `alert`, `log`, `generic`, `other`, `missing`; and `off`, `polite`, `assertive`, `other`, `missing`). No class names, arbitrary attributes, text, HTML, or DOM serialization is recorded.

For a visible candidate, text is read transiently in memory only. The existing localized quantity parser determines whether it is positive. Only a visible quantity-bearing match emits `trash_feedback_popup` with `popup_kind=bottom_left_toast`, numeric `moved_count`, `positive_feedback=true`, and exact `feedback_source=browser_positive_feedback`. A visible message without a quantity remains non-proof and only contributes metadata diagnostics. Hidden candidates and DOM disappearance remain non-proof.

The existing text-locator fallback remains available after live-region inspection so adapters and markup variants that do not expose ARIA roles continue to work. Any locator exception remains fail-closed.

## Tests and acceptance criteria

Tests will cover:

1. visible `role=status` markup with Italian quantity-bearing feedback;
2. visible `role=alert` markup with English quantity-bearing feedback;
3. visible `[aria-live=polite]` markup without a role;
4. hidden live-region candidates producing no positive feedback;
5. visible feedback without a quantity remaining non-proof;
6. overlapping live-region selectors producing at most one positive popup event;
7. locator failures producing safe failure diagnostics without DOM content;
8. the existing text fallback and dynamic quantities remaining supported;
9. all new and existing events excluding raw popup text and HTML.

Completion still requires `feedback_source=browser_positive_feedback`. No test or implementation path may retry an ambiguous destructive action.

Required verification:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall -q .
git diff --check
```

No live destructive run is part of implementation or testing.

## Documentation impact

- Feature/user-facing documentation introduced: none; the observer is internal diagnostics.
- Materially amended documentation: `HANDOFF-2026-08-24-googlephotos-scan.md`, updated after implementation with the actual selector groups and observed safe metadata; no raw DOM content will be added.
- Derived/memory invalidated: none. Existing Trash-proof and pending-policy specifications remain authoritative; this spec extends their diagnostic observation details.

## Open questions

None. The metadata-only logging boundary and exact positive-feedback source contract were confirmed before implementation.
