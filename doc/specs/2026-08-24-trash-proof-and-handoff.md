# Trash proof and handoff cleanup

## Goal

Make destructive-action journal evidence truthful and stop handoff history from presenting old commits as current.

## Requirements

- `move_selected_to_trash()` emits browser evidence for positive feedback category and confirmed result before returning.
- Cleaner `trash_completed` is emitted only after adapter returns successfully and includes `positive_feedback=true`, `result=confirmed`, `feedback_source=browser_positive_feedback`.
- Ambiguous event includes sanitized error message and no completion event.
- Handoff has one current status block with exact HEAD, one merge status, test count, and runtime snapshot; old commits move under history.
- No live destructive action, no profile mutation, no retry.
