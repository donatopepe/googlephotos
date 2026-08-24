# Runtime handoff finalization plan

1. RED test: handoff current commit marker must be updated after implementation.
2. RED test: worktree status must be clean after commit.
3. Verify terminal event tests and required fields.
4. Commit all worktree changes including spec/plan.
5. Update primary handoff with exact committed HEAD and fresh runtime snapshot.
6. Run full tests, compileall, diff check, process/lock/pending/checkpoint inspection.
