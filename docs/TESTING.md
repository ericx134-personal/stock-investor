# Testing Strategy

The default test policy is cost-aware. Do not run the full suite by habit.

## Levels

- **L1 fast regression**: default local check for ordinary edits. Covers
  read-only safety, broker importers, latest-price/data handling, refresh smoke,
  and dashboard failures that have already bitten us.
- **L2 core regression**: use when touching model logic, diagnostics, risk,
  evaluation, wave evidence, or broad dashboard behavior. This is the default
  CI test level.
- **L3 full audit**: use before release/public sharing, after cross-cutting
  refactors, or when L1/L2 pass but behavior still looks suspicious. Runs all
  tests plus the public-safety check.

## Commands

```bash
make test       # L1
make test-l2    # core regression
make test-l3    # full audit + public safety
```

`tests/__init__.py` inserts `src` into `sys.path`, and `scripts/run_tests.sh`
also exports `PYTHONPATH`, so direct unittest invocations should not fail with
`ModuleNotFoundError: stock_investor`.
