# Quantity-first Trash popup parsing

## Goal

Recognize Google Photos’ rendered Trash toast when Italian wording places the moved quantity first, such as `62 spostate nel cestino`, while preserving existing localized variants and the fail-closed positive-feedback contract.

## Scope

Change only the popup parser and focused browser tests. Parse rendered visible text in memory; do not use or log CSS classes, element IDs, HTML, page content, screenshots, URLs, credentials, or media identifiers. Keep live-region observation, fallback locators, pending handling, retry policy, and scrolling behavior unchanged.

## Design

Extend `PlaywrightBrowser.TRASH_FEEDBACK_POPUP_PATTERN` to accept both forms:

- verb-first: `Spostate 19 foto nel Cestino`, `Moved 8 photos to Trash`;
- quantity-first: `62 spostate nel cestino`.

The expression may make the photo noun optional for quantity-first localized text. It must capture exactly one numeric quantity through named alternatives or an equivalent parser helper. All call sites must normalize the match to integer `moved_count` without relying on a fixed positional group that breaks between forms.

The parser continues to require a visible candidate and a destination phrase (`trash`, `bin`, or localized `cestin...`). A matching hidden candidate, text without quantity, or non-matching text remains non-proof. Positive completion continues to emit only:

```text
moved_count=N
positive_feedback=true
feedback_source=browser_positive_feedback
popup_kind=bottom_left_toast
```

The DOM class/id shown in operator diagnostics (`zyTWof-gIZMF`, `c50`) is not part of the selector or logging contract because it is unstable and unnecessary.

## Tests and acceptance criteria

Add a failing unit test for visible fallback text `62 spostate nel cestino`, asserting `moved_count=62`, exact positive source, and no raw text. Keep existing tests for Italian verb-first and English variants. Add or retain a rejection test for quantity-less text. Run full suite, compileall, and diff check after implementation.

Required verification:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall -q .
git diff --check
```

No live destructive run is required to validate parser behavior. A later live run may use operator-authorized pending discard, but this change itself must not click Trash.

## Documentation impact

- Feature/user-facing documentation introduced: none; parser behavior is internal.
- Materially amended documentation: `/home/public/googlephotos/HANDOFF-2026-08-24-googlephotos-scan.md` only if a later live run observes this exact wording; no raw DOM markup will be recorded.
- Derived/memory invalidated: `/home/public/HermesVault/Inbox/2026-08-25T10-00-00Z-googlephotos-priority.md` remains valid; append observed operator-reported quantity only as non-browser proof.

## Open questions

None. User confirmed support for the quantity-first popup wording.
