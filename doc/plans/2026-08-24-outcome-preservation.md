# Outcome preservation plan

1. Add RED test with Cleaner-like failure carrying `DESTRUCTIVE_AMBIGUOUS` and assert public final outcome.
2. Add RED test with generic browser failure and assert `failed` remains.
3. Implement outcome extraction in `main.run` exception path.
4. Update handoff current commit and test count.
5. Run full suite, compileall, diff check; inspect process/lock/pending/checkpoint.
