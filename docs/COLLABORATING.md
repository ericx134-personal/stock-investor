# Collaborating Safely

## Project Boundaries

- Read-only decision support only. Never add automatic trade placement.
- Do not commit real holdings, balances, account numbers, cost bases, tokens,
  cookies, MFA material, or private dashboards.
- Keep `data/`, `portfolio/`, `.env`, and real price exports ignored.
- Use aggregate or synthetic examples in tests and documentation.
- Treat BUY, SELL, and WAIT as research forecasts, not financial advice.

## Development Workflow

Never treat completing a milestone, commit, push, or progress report as a
stopping condition. Continue immediately with the next highest-value unblocked
milestone while the work window remains available. Stop only for an explicit
user request, an external execution limit, or a genuine blocker that cannot be
resolved locally.

1. Choose the highest-value unblocked milestone from
   `docs/CONTINUOUS_EXECUTION_PLAN.md`, using
   `docs/LONG_HORIZON_ROADMAP.md` for detailed backlog context.
2. Write down the hypothesis and validation rule before inspecting outcomes.
3. Implement the smallest complete change with focused tests.
4. Run the full suite:

   ```bash
   PYTHONPATH=src python3 -m unittest discover -s tests
   ```

5. Run the public-safety gate before pushing:

   ```bash
   scripts/check_public_safety.sh
   ```

6. Update `docs/RESEARCH_FINDINGS.md` only when evidence changes.
7. Keep model changes versioned; do not rewrite historical forecasts.

## Pull Request Checklist

- [ ] No private account or portfolio data is included.
- [x] No Robinhood write or trade action is introduced; CI enforces the read-only contract.
- [ ] The hypothesis and intended horizon are documented.
- [ ] Point-in-time and look-ahead behavior is tested.
- [ ] Missing-data behavior is explicit.
- [ ] New forecasts are append-only and evaluable.
- [ ] Focused and full tests pass.
- [ ] Research limitations are stated plainly.

## Repository Map

- `src/stock_investor/`: dependency-free application and research code.
- `tests/`: synthetic unit and integration tests.
- `models/`: immutable model configuration versions.
- `docs/STRATEGY.md`: detailed product and validation decisions.
- `docs/RESEARCH_FINDINGS.md`: concise team research handoff.
- `docs/LONG_HORIZON_ROADMAP.md`: prioritized long-running backlog.
- `docs/CONTINUOUS_EXECUTION_PLAN.md`: canonical adaptive milestones and completion gates.
- `examples/`: sanitized public input formats and demo data.
