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

Important: logging in to `robinhood.com` in the app browser or Chrome does
**not** authenticate this project. The Robinhood Trading MCP uses the AI
platform's MCP/OAuth connection state, not ordinary Robinhood website cookies.
If `get_accounts` returns `OAuth authorization required`, reconnect or
reauthenticate the MCP server inside Codex, then rerun the read-only import and
dashboard refresh. The static dashboard cannot pull MCP data by itself.

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

## Standalone App Direction

Treat the Robinhood MCP as a prototype connector for AI-agent workflows, not as
the long-term auth backend for an iOS or public web app.

Current official surfaces are split:

- Robinhood Trading MCP is for MCP-compatible AI platforms. It can expose
  read-only positions, balances, transactions, and account details after the
  user authorizes the AI platform connection. Trade placement is restricted to
  the user's dedicated Agentic account, and this project still forbids all
  write/trade actions.
- Robinhood Crypto Trading API is an official programmatic API for crypto
  market data, crypto account data, holdings, orders, products, quotes, and
  crypto order placement after the user creates API credentials.
- There is no committed project assumption that a supported retail equities
  password-login API exists for a third-party iOS/web app. Do not build around
  the user's Robinhood username/password, browser cookies, or private mobile
  endpoints.

For a real standalone product, build a broker connector abstraction and prefer
one of these paths:

1. Official broker OAuth/partner connections for read-only brokerage data when
   Robinhood or another broker exposes a supported surface.
2. A regulated brokerage-aggregation provider for read-only holdings and
   transactions if it supports Robinhood and meets privacy/security needs.
3. User-imported CSV/statements as a fallback.
4. A separate supported brokerage API for accounts the user is willing to
   mirror or migrate.

The app should never ask for or store a Robinhood password.

The dashboard's connection gate should therefore look like a production app
login, but its broker section must route to a supported connector. A Stock
Investor account login can authenticate the user to our app; it must not be
presented as a Robinhood login unless Robinhood later provides an official
OAuth/partner flow for that exact purpose.

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
