# Integration readiness

## Goal

Stop repeated patch-only cycles. Produce explicit integration readiness evidence for current branch, without merging or destructive browser action.

## Requirements

- Verify branch HEAD and clean status.
- Verify full tests, compileall, diff check.
- Verify handoff current commit matches HEAD and current test count.
- Compare branch against main and report files/commits.
- Preserve main, profile, PID 1869, pending/checkpoint.
- Do not merge without explicit integration request.
