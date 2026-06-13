# Collaborating Safely

## Project Boundaries

- Read-only decision support only. Never add automatic trade placement.
- Do not commit real holdings, balances, account numbers, cost bases, tokens,
  cookies, MFA material, or private dashboards.
- Keep `data/`, `portfolio/`, `.env`, and real price exports ignored.
- Use aggregate or synthetic examples in tests and documentation.
- Treat BUY, SELL, and WAIT as research forecasts, not financial advice.

## Development Workflow

1. Choose a task from `docs/LONG_HORIZON_ROADMAP.md`.
2. Write down the hypothesis and validation rule before inspecting outcomes.
3. Implement the smallest complete change with focused tests.
4. Run the full suite:

   ```bash
   PYTHONPATH=src python3 -m unittest discover -s tests
   ```

5. Update `docs/RESEARCH_FINDINGS.md` only when evidence changes.
6. Keep model changes versioned; do not rewrite historical forecasts.

## Pull Request Checklist

- [ ] No private account or portfolio data is included.
- [ ] No Robinhood write or trade action is introduced.
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
- `examples/`: sanitized public input formats and demo data.
