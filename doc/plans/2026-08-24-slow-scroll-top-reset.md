# Slow scroll and return-to-top after deletion

## Requirements

- Timeline scroll uses small step `240` px and delay `1500` ms.
- Values configurable with `--scroll-step` and `--scroll-delay-ms`.
- If day checkbox exists: click and verify fresh `aria-checked=true`; do not fallback on failed verification.
- If no day checkbox exists: fallback to one visible photo/video checkbox, for single-photo days.
- After confirmed or safely reconciled day/photo Trash action, return timeline to top before next scan.
- Returning to top must use visible mouse wheel input, not page reload/navigation.
- Preserve pending journals and never retry ambiguous Trash blindly.

## Tests

- CLI defaults and custom scroll values.
- Browser wheel uses configured amount and delay.
- Browser top reset sends bounded negative wheel and waits.
- Day-missing path keeps single-media fallback.
- Day-present failed verification does not fallback.
- Automation invokes top reset after completed/reconciled deletion.
