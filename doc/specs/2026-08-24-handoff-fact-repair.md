# Handoff fact repair

## Goal

Remove stale contradictory facts from handoff and make current branch status auditable.

## Requirements

- Current worktree commit in `## Stato corrente` matches actual HEAD `0ba2264` until next commit.
- Current verification count and current branch delta are factual.
- Historical commit list remains clearly historical.
- Main remains `fcabfe5`; no merge performed.
- Runtime snapshot records PID 1869 as unrelated, lock absent, pending absent, checkpoint state.
- No code/profile/browser/destructive changes.
