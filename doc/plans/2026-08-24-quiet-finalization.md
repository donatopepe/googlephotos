# Quiet finalization plan

1. RED test: missing diagnostic artifact method does not produce console error in test-like fake; journal has diagnostics_failed.
2. RED test: handoff current section has one current commit/count marker.
3. Implement logging level/guard for diagnostics capture failure while preserving event.
4. Rewrite handoff current/history layout.
5. Full verification, commit, update handoff, inspect runtime safety.
