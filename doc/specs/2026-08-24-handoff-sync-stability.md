# Handoff sync stability

## Goal

Make handoff updates reliable without requiring a new commit for every documentation edit, and remove stale current-state drift.

## Requirements

- Handoff current commit matches actual worktree HEAD after final commit.
- Test checks handoff shape, not hard-coded commit literals.
- Handoff lists current verification count and runtime facts in one block.
- No code behavior changes.
- No profile/PID/browser/Trash mutation.
