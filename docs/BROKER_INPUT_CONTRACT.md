# Broker Input Contract

This project should stay broker-neutral. Robinhood, Moomoo watchlists, and
future Fidelity accounts should normalize into the same small set of
private local files before the model or dashboard reads them.

See `MOOMOO_FIDELITY_INTEGRATION_RESEARCH.md` for the current source-specific
integration decision.

## Goals

- Aggregate all holdings across supported brokers without coupling the model to
  one brokerage UI or session format.
- Keep brokerage credentials, cookies, MFA codes, and raw account identifiers
  out of the repo and out of public artifacts.
- Make every imported snapshot reproducible enough to debug a bad forecast.
- Keep broker integrations read-only. No trading, watchlist writes, or account
  mutations belong in runtime code.

## Normalized Files

`portfolio/positions.csv` remains the primary portfolio input:

```csv
symbol,shares,average_cost,max_portfolio_weight,quality,valuation,revisions,thesis_broken,cik,sector,theme
HOOD,1180,19.77,0.25,,,,false,,Financials,Brokerage
```

Broker adapters may add zero-share rows for watchlist-only candidates, but the
core monitor should treat them as research candidates, not positions.

`portfolio/account-summary.json` should contain account-level fields when a
broker exposes them:

```json
{
  "account_value": 654377.15,
  "holdings_value": 654377.15,
  "buying_power": 1000.0,
  "margin_used": 0.0,
  "cash": 0.0,
  "source": "normalized-broker-import",
  "as_of": "2026-06-23T21:00:00-07:00"
}
```

Optional per-broker snapshots should live under ignored private paths such as
`data/private/brokers/robinhood.json`, `data/private/brokers/moomoo.json`, and
`data/private/brokers/fidelity.json`. These are raw-ish debug artifacts and
must not be committed.

`data/private/brokers/merged-universe.json` is the broker-neutral audit layer.
It merges read-only SnapTrade holdings by symbol and keeps per-source
attribution for each broker/account. It also separates Moomoo watchlist-only
symbols from symbols already held. This file is private runtime state; it is
not the model input yet. `portfolio/positions.csv` remains the explicit
decision-support portfolio until the import flow has enough validation.

`data/private/candidate-boundary.json` records the current separation between
held symbols, zero-share CSV candidates, broker watchlist-only symbols, and the
direction-forecast universe. A nonzero `direction_forecast_violations` count is
a regression: watchlist-only symbols must not enter held-position direction
forecasts unless they are explicitly promoted into real positions.

## Adapter Boundary

Each broker adapter should do only three things:

1. Read or import that broker's available portfolio/watchlist/account data.
2. Normalize symbols, quantities, costs, buying power, margin, and timestamps.
3. Write sanitized private files that the existing refresh pipeline can consume.

The model, dashboard, K-line renderer, forecast ledger, and evaluation code
should not know whether a row came from Robinhood, Moomoo, Fidelity, or a CSV
export.

## Future Broker Notes

- Moomoo: start with OpenD/API watchlist import and optional K-line fallback.
  Do not assume user-drawn chart levels are exportable until an official or
  user-controlled format is confirmed.
- Fidelity: start with portfolio CSV or official authorized data-sharing
  surfaces. Normalize cost basis, cash, and account value where available.
  Treat 401k funds that lack ticker-compatible daily prices separately from
  ordinary equities.
- Multiple brokers: merge rows by symbol using summed shares and weighted
  average cost. Preserve per-broker debug snapshots privately for audit.
- Merged universe: generate it after account/watchlist imports so UI and future
  import tools can use one small file without coupling to SnapTrade, Moomoo, or
  a future Fidelity CSV fallback.

## Public Safety

Before making the repo public or pushing shared work, run:

```bash
scripts/check_public_safety.sh
```

The public repo should contain code, docs, schemas, and demo data only. Real
positions, account values, broker exports, and dashboards belong under ignored
private paths.
