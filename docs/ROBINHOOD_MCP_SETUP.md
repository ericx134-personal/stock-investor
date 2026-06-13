# Robinhood Trading MCP Setup And Read-Only Workflow

This is the team runbook for connecting Robinhood to Codex and feeding the
stock-investor system. The connection itself is simple; the important part is
keeping the downstream workflow read-only, privacy-safe, and reproducible.

Official reference:
[Robinhood Agentic Trading overview](https://robinhood.com/us/en/support/articles/agentic-trading-overview/)

## Three-Minute Codex Setup

Robinhood's official Trading MCP endpoint is:

```text
https://agent.robinhood.com/mcp/trading
```

In the Codex desktop app:

1. Open **Settings**.
2. Open **MCP servers**.
3. Choose **Streamable HTTP**.
4. Add `https://agent.robinhood.com/mcp/trading`.
5. Start authentication and complete Robinhood's flow in a desktop browser.
6. Return to Codex and verify that Robinhood tools are available.

For Codex CLI:

```bash
codex mcp add robinhood-trading --url https://agent.robinhood.com/mcp/trading
```

Then enter `/mcp`, select `robinhood-trading`, and authenticate.

Authentication is handled by Robinhood. Never give the agent a Robinhood
password, MFA code, recovery code, browser cookie, or session token. Never put
those values in `.env`, a prompt, a file, or Git.

## What The Connection Can Access

As documented by Robinhood, an authenticated Trading MCP connection can read
all linked Robinhood accounts, including account numbers, positions, balances,
transactions, and order history. Trade placement is restricted to a dedicated
Robinhood Agentic account.

This repository adopts a stricter policy:

- Robinhood MCP is used only for reads.
- No order-placement, cancellation, watchlist-write, or other mutation tool is
  called.
- Main and Agentic account data may be read, but account identifiers are
  removed before project artifacts are persisted.
- All real portfolio artifacts remain under ignored `portfolio/` or
  `data/private/` paths.

The MCP's technical ability to trade in an Agentic account does not change the
project's permanent no-trade rule.

## First Connection Verification

After authentication, verify the connection with the smallest useful reads:

1. Call `get_accounts` to enumerate linked accounts.
2. For each explicitly selected account, call `get_equity_positions`.
3. Call `get_portfolio` for balances, buying power, and asset breakdown.
4. Call `get_equity_quotes` for current quote reconciliation.
5. Call `get_equity_historicals` for daily bars.

Do not assume the first account returned is the intended account. Some
Robinhood tools require an `account_number`; select it from the authenticated
result for that run, use it only in memory, and never persist it.

For this project, request daily historical bars with:

```text
interval=day
bounds=regular
adjustment_type=split
```

The monitor is designed for multi-week and multi-month waves, not intraday
trading. Regular-session daily bars provide the appropriate base frequency.

## Portfolio Snapshot Data Flow

The privacy boundary is:

```text
Robinhood MCP response
  -> temporary combined read payload
  -> sanitize-robinhood whitelist
  -> ignored sanitized snapshot
  -> import-robinhood
  -> ignored monitor positions and account summary
  -> read-only refresh and private dashboard
```

The temporary combined payload has this conceptual shape:

```json
{
  "accounts": [
    {
      "account_number": "removed-by-sanitizer",
      "cash": 1000,
      "buying_power": 2000,
      "positions": [
        {
          "symbol": "EXAMPLE",
          "asset_type": "equity",
          "quantity": 10,
          "average_cost": 25,
          "instrument_id": "removed-by-sanitizer"
        }
      ]
    }
  ]
}
```

Run the sanitizer before using or retaining the payload:

```bash
PYTHONPATH=src python3 -m stock_investor.cli sanitize-robinhood \
  portfolio/combined-robinhood-read.json \
  portfolio/robinhood-snapshot.json
```

The sanitizer uses an explicit whitelist. It keeps only:

- Per-account cash and buying power.
- Position symbol, asset type, quantity, and average cost.
- A capture timestamp and schema version.

It removes account numbers, nicknames, instrument IDs, and all unrecognized
fields. Tests verify that identifiers are dropped.

Convert the sanitized snapshot into monitor inputs:

```bash
PYTHONPATH=src python3 -m stock_investor.cli import-robinhood \
  portfolio/robinhood-snapshot.json \
  portfolio/positions.csv \
  portfolio/robinhood-summary.json \
  --metadata portfolio/positions.csv \
  --baseline-history portfolio/robinhood-baselines.jsonl
```

The importer:

- Aggregates the same equity ticker across linked accounts.
- Computes a weighted average cost.
- Preserves separately maintained sector, theme, thesis, and risk metadata.
- Skips non-equity positions.
- Allows negative cash so margin usage is measured honestly.
- Gives new holdings conservative blank metadata and a default 10% maximum
  weight until reviewed.
- Appends a baseline only when balances or holdings change.

## Historical Price Data Flow

Robinhood MCP daily historical output can be exported and converted:

```bash
PYTHONPATH=src python3 -m stock_investor.cli import-robinhood-prices \
  portfolio/robinhood-historicals.json \
  data/private/robinhood-prices.csv
```

The converter:

- Rejects intervals other than daily.
- Normalizes symbols and timestamps.
- Preserves OHLCV fields.
- Removes bars explicitly marked as interpolated.
- Rejects duplicate dates and non-positive closes.

A Codex session log containing structured Robinhood historical and quote tool
results can also be converted:

```bash
PYTHONPATH=src python3 -m stock_investor.cli extract-robinhood-prices \
  /path/to/codex-session.jsonl \
  data/private/robinhood-prices.csv
```

Session logs may contain sensitive MCP results. Treat the source log as
private, never commit it, and remove it when no longer needed.

The newest historical bar may not be the official settled close. Refresh after
market settlement or reconcile the latest date with `get_equity_quotes`.

## Run The Full Read-Only Refresh

After positions and daily prices are current:

```bash
PYTHONPATH=src python3 -m stock_investor.cli refresh \
  portfolio/positions.csv \
  data/private/robinhood-prices.csv \
  data/private \
  --model-version decision-support-v3 \
  --account-summary portfolio/robinhood-summary.json \
  --baseline-snapshot data/private/model-v1-snapshot.json \
  --benchmark SPY
```

This produces private snapshots, append-only decisions, risk diagnostics,
K-line and wave evidence, forward-outcome scorecards, and the local dashboard.
The manifest is written last so an interrupted run cannot appear complete.

## Safety Verification Before Every Push

```bash
git status --short --ignored
git check-ignore -v \
  portfolio/positions.csv \
  portfolio/robinhood-summary.json \
  data/private/robinhood-prices.csv \
  data/private/dashboard-v3.html
git diff --cached --name-only
```

Expected: every real portfolio, price, and dashboard artifact is ignored, and
none appears in the staged file list.

## Troubleshooting

### Robinhood tools do not appear

- Confirm the MCP server is enabled in Codex settings.
- Disconnect and reconnect the Robinhood Trading MCP.
- Complete authentication on a desktop device.
- Restart or open a new Codex thread if newly installed tools have not appeared.

### Main account cannot be traded

This is expected. Robinhood restricts agent trade placement to the dedicated
Agentic account. The main account can still be readable after authentication.
This project never attempts to trade either account.

### A tool requests an account number

Call `get_accounts`, explicitly select the intended account for the current
read, and pass that number only to the read tool. Do not copy the number into
source code, docs, prompts intended for sharing, or persisted artifacts.

### Historical bars look incomplete

- Confirm `interval=day` and `bounds=regular`.
- Request a sufficiently early `start_time`.
- Check for provider limits and fetch symbols in batches.
- Reconcile the newest date with the official quote close.
- Do not silently fill missing sessions.

### Access should be revoked

Disconnect the Robinhood Trading MCP from the AI platform and use Robinhood's
account controls to disable the connection. Rotate or revoke access rather
than deleting local files and assuming access is gone.

## Team Rule

Connecting is intentionally easy. Preserving an auditable read-only boundary
is the real engineering task. Any proposed Robinhood write capability must be
rejected from this repository.
