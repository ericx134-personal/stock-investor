# Moomoo And Fidelity Integration Research

Date: 2026-06-23

## Decision

Use this project as the portfolio brain. Each broker or tool should feed it
through a small, read-only import adapter:

1. Robinhood remains the first real holdings source through the existing MCP
   path.
2. Moomoo should be added first as a watchlist and K-line data source.
3. Fidelity 401k should start as CSV/manual export or an authorized aggregator
   connection, not password automation.

The normalized files in `BROKER_INPUT_CONTRACT.md` stay the boundary. The model
and dashboard should not know which broker produced a position.

## Moomoo / Futu

Moomoo is useful even if the account holds few or no shares. The actual use
case is a watchlist hub for Robinhood and Fidelity holdings, and that matches
the public API surface better than treating Moomoo as the master brokerage
account.

Official docs show that Moomoo/Futu OpenAPI uses OpenD plus SDKs, including
Python, and covers market data and trading services. The official download page
shows `pip install moomoo-api` and macOS support.

Official references:

- https://openapi.moomoo.com/moomoo-api-doc/en/
- https://www.moomoo.com/download/OpenAPI
- https://openapi.moomoo.com/moomoo-api-doc/en/quote/overview.html
- https://openapi.moomoo.com/moomoo-api-doc/en/quote/get-user-security.html
- https://openapi.moomoo.com/moomoo-api-doc/en/quote/request-history-kline.html

Useful quote APIs:

- `get_user_security_group`: list watchlist groups.
- `get_user_security(group_name)`: read a specified watchlist group.
- `request_history_kline(...)`: fetch historical candlesticks with symbol,
  start, end, K-line type, adjustment type, and pagination parameters.
- `get_market_snapshot`: get current quote-style snapshots.

Implemented first step:

- `import-moomoo-watchlist` reads Moomoo/OpenD watchlist groups and writes
  normalized private JSON.
- Local SDK installation is not enough. Personal watchlists require Moomoo
  OpenD running on `127.0.0.1:11111` and logged in to the user's Moomoo
  account. If OpenD is not reachable, the importer now fails fast instead of
  waiting on SDK reconnect attempts.

Next implementation:

1. Verify the importer against the user's local OpenD session.
2. Merge watchlist symbols into dashboard research candidates without changing
   real portfolio shares.
3. Add per-source attribution so Moomoo watchlist symbols remain distinct from
   Robinhood/Fidelity held positions.
4. Optionally fetch Moomoo historical K-lines for symbols where Yahoo data is
   missing, stale, or visually poor.

What not to assume yet:

- No official endpoint for exporting user-drawn chart lines or annotations is
  confirmed. Treat Moomoo-drawn support/resistance lines as unavailable until
  an official export path or user-controlled export file is proven.
- Do not enable Moomoo trading calls.
- Do not store Moomoo passwords in this repo. If OpenD needs login, keep that
  state in the Moomoo/OpenD app or private local config outside git.

## Fidelity / NetBenefits / 401k

Fidelity is more sensitive because it may include retirement accounts and
employer-plan data. The safe path is authorized data sharing or CSV/manual
export, not scraping.

Fidelity's own security pages describe Fidelity Access as a way to share account
data with third-party websites and apps without giving those third parties the
Fidelity username and password. Fidelity also says older third-party access can
involve credential sharing, which this project should avoid.

Official references:

- https://www.fidelity.com/security/fidelity-access-data-security
- https://www.fidelity.com/security/third-party-app-protection
- https://nb.fidelity.com/public/nb/default/resourceslibrary_redesign/articles/datasecurity

Best first implementation:

1. Add a `portfolio/fidelity-positions.csv` import path.
2. Normalize Fidelity rows into the same position schema as Robinhood.
3. Add a broker merge step that sums shares by symbol and computes weighted
   average cost where cost basis is available.
4. Classify 401k mutual funds or target-date funds without ticker-compatible
   daily prices separately instead of forcing stock signals.
5. Add account-level fields only when available: account value, contribution
   source if exported, cash/buying power if meaningful, and as-of timestamp.

Longer-term Fidelity options:

- Use Fidelity Access only if this project becomes a registered app or routes
  through a supported aggregator that the user explicitly authorizes.
- Treat Plaid/Finicity/Akoya-style aggregation as a separate product decision:
  it adds vendor dependency, token handling, data retention policy, and likely
  paid API access.

What not to do:

- Do not automate Fidelity login with username/password.
- Do not store Fidelity cookies, MFA state, account numbers, or raw statements.
- Do not assume 401k holdings map cleanly to public stock tickers.

## Unified Product Shape

Near-term dashboard behavior:

- Holdings tab: real combined positions from Robinhood plus future Fidelity.
- Watchlist tab: Moomoo watchlist names, symbols, and research status.
- Opportunities tab: only active BUY/SELL/WAIT review candidates from the model.
- Data health tab: per-source freshness, missing symbols, and import warnings.

Near-term backend shape:

```text
Broker/tool source
  -> private raw snapshot/export
  -> broker adapter
  -> normalized private positions/watchlists/account summary
  -> existing refresh/model/dashboard pipeline
```

This keeps the project simple: one model, one dashboard, one normalized data
contract, many thin read-only importers.

## Recommended Next Milestones

1. Moomoo watchlist importer, read-only, no trading context.
2. Combined holdings merger with per-broker source attribution.
3. Fidelity CSV importer for 401k/exported holdings.
4. Moomoo K-line fallback provider only after the watchlist importer is stable.
5. Optional Moomoo annotation import only if an official/user export format is
   confirmed.
