# Day checkbox timeout fix

## Scope

Fix live day-first scanning failures caused by a virtualized Google Photos day checkbox becoming stale or timing out after timeline movement. Preserve authenticated profile, visible-only targeting, positive Trash confirmation, and ambiguous-action safety.

## Plan

1. Add failing browser tests for stale day-control re-read and strict verification.
2. Change day selection to re-query the current visible day checkbox after pointer reveal, click only a current visible locator, then verify `aria-checked="true"` from a fresh locator.
3. Remove fallback from a found-but-unverified day control to arbitrary single-media selection; fail safe instead.
4. Bound day-scan timeout/recovery behavior so repeated failures do not spin forever without advancing or stopping.
5. Run full tests, compileall, diff check.
6. Stop current cleaner only after verification; verify profile owner/lock; start one instance and require fresh day lifecycle evidence.
