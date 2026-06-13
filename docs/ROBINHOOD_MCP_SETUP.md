# Robinhood MCP Setup

Robinhood connection is intentionally simple. The project uses it only as a
read-only source for positions, balances, quotes, and daily price history.

Official reference:
[Robinhood Agentic Trading overview](https://robinhood.com/us/en/support/articles/agentic-trading-overview/)

## Connect In Codex

1. Open **Settings -> MCP servers**.
2. Choose **Streamable HTTP**.
3. Add:

   ```text
   https://agent.robinhood.com/mcp/trading
   ```

4. Authenticate with Robinhood in a desktop browser.
5. Verify access with `get_accounts`.

For Codex CLI:

```bash
codex mcp add robinhood-trading --url https://agent.robinhood.com/mcp/trading
```

Then enter `/mcp`, select `robinhood-trading`, and authenticate.

Robinhood documents that the MCP can read all linked accounts, while trade
placement is restricted to a dedicated Agentic account. This project applies a
stricter permanent rule: **never call Robinhood write or trade tools**.

Never provide or persist a Robinhood password, MFA code, recovery code, cookie,
session token, or account number.

## Read-Only Refresh Flow

Use Robinhood reads to collect:

- `get_accounts`
- `get_equity_positions` for each explicitly selected account
- `get_portfolio`
- `get_equity_quotes`
- `get_equity_historicals`

Request daily history with `interval=day`, `bounds=regular`, and
`adjustment_type=split`. Do not assume the first account returned is the
intended account.

Before retaining a combined portfolio response, sanitize it:

```bash
PYTHONPATH=src python3 -m stock_investor.cli sanitize-robinhood \
  portfolio/combined-robinhood-read.json \
  portfolio/robinhood-snapshot.json

PYTHONPATH=src python3 -m stock_investor.cli import-robinhood \
  portfolio/robinhood-snapshot.json \
  portfolio/positions.csv \
  portfolio/robinhood-summary.json \
  --metadata portfolio/positions.csv \
  --baseline-history portfolio/robinhood-baselines.jsonl
```

The sanitizer keeps only cash, buying power, symbol, asset type, quantity, and
average cost. It drops account identifiers and all unrecognized fields.

Convert exported daily historical results:

```bash
PYTHONPATH=src python3 -m stock_investor.cli import-robinhood-prices \
  portfolio/robinhood-historicals.json \
  data/private/robinhood-prices.csv
```

Then run the full read-only analysis:

```bash
PYTHONPATH=src python3 -m stock_investor.cli refresh \
  portfolio/positions.csv data/private/robinhood-prices.csv data/private \
  --model-version decision-support-v3 \
  --account-summary portfolio/robinhood-summary.json \
  --baseline-snapshot data/private/model-v1-snapshot.json \
  --benchmark SPY
```

All real portfolio and dashboard artifacts belong under ignored `portfolio/`
or `data/private/` paths. Before every push, verify they remain ignored:

```bash
git status --short --ignored
git diff --cached --name-only
```
