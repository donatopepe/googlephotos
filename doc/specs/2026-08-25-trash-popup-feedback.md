# Trash popup feedback

## Goal

Use the visible Google Photos bottom-left toast that reports moved photo counts as positive completion evidence, without collecting page content or retrying ambiguous destructive actions.

## Requirements

- Inspect only visible status/alert/live-region or text locators during normal operation; no HTML/page-content capture.
- Debug-only exception: public client-side HTML/JavaScript may be read transiently in memory through approved browser tooling, never saved, logged, or copied into artifacts. Exclude passwords, cookies, tokens, headers, media URLs, session data, and anti-robot challenge material; do not copy or reproduce proprietary anti-robot controls.
- Accept localized quantity-bearing confirmations such as `Spostate 8 foto nel Cestino`, `Spostata 1 foto nel Cestino`, and `Moved 8 photos to Trash`.
- Extract only numeric `moved_count` and a safe popup kind; do not log the raw popup text.
- Emit `trash_feedback_popup` with `popup_kind=bottom_left_toast`, `moved_count`, `positive_feedback=true`, and `feedback_source=browser_positive_feedback` only after visibility succeeds.
- Preserve existing exact source contract and fail-closed behavior. DOM disappearance, checkbox counts, hidden text, or journal observation remain non-proof.
- Keep pending/checkpoint journal when no visible popup is found; never auto-retry Trash.
- Add unit tests for accepted localized variants, hidden popup, missing quantity, and event sanitization.
- No live destructive run while implementing or testing.
