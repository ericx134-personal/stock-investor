# Moomoo And Fidelity Integration Research

Date: 2026-06-23

## Decision

Use this project as the portfolio brain. Each broker or tool should feed it
through a small, read-only import adapter:

1. SnapTrade is the product-facing read-only aggregation path for Robinhood,
   Fidelity, and future broker accounts.
2. Moomoo should be the primary local watchlist and K-line data source.
3. Yahoo Finance should remain a fallback market-data source, not the default
   source of truth.

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

Implemented SnapTrade/Fidelity state:

- Personal SnapTrade keys represent the user's own SnapTrade user, so
  `snaptrade-register-user` is not needed for the current setup and exits with
  a clear message when SnapTrade reports a Personal key.
- `snaptrade-login-url` generates a read-only Connection Portal URL with
  `connectionType=read`; Fidelity username, password, and MFA stay inside the
  Fidelity/SnapTrade authorization flow.
- `import-snaptrade-accounts` reads SnapTrade accounts, balances, and positions
  into ignored private JSON with masked account numbers.
- The private dashboard can now render a separate Fidelity tab from
  `data/private/brokers/snaptrade-accounts.json`, showing account totals,
  cash/buying power, per-account sync status, and imported positions.
- No SnapTrade trading endpoints are implemented.

CSV fallback only:

The user does not have a Fidelity CSV export available. Do not block on CSV.
Only add a CSV importer if SnapTrade/Fidelity Access cannot cover the needed
account or a one-off export becomes available later.

1. Add a broker merge step that sums shares by symbol and computes weighted
   average cost where cost basis is available.
2. Classify 401k mutual funds or target-date funds without ticker-compatible
   daily prices separately instead of forcing stock signals.
3. Add account-level fields only when available: account value, contribution
   source if exported, cash/buying power if meaningful, and as-of timestamp.

Longer-term Fidelity options:

- Continue with SnapTrade if the free tier remains sufficient for the user's
  personal Fidelity/401k connection.
- Re-evaluate Akoya/Plaid/Finicity only if SnapTrade coverage, freshness, or
  pricing becomes inadequate.

What not to do:

- Do not automate Fidelity login with username/password.
- Do not store Fidelity cookies, MFA state, account numbers, or raw statements.
- Do not assume 401k holdings map cleanly to public stock tickers.

## Unified Product Shape

Near-term dashboard behavior:

- Robinhood tab: current stock-decision surface and prediction details.
- Fidelity tab: imported Fidelity/SnapTrade accounts and positions for
  visibility only; 401k funds, cash sweeps, and non-stock instruments are not
  forced into stock prediction signals.
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

1. Combined holdings merger with per-broker source attribution.
2. Fidelity CSV importer only as a fallback if SnapTrade coverage fails.
3. Moomoo K-line fallback provider only after the watchlist importer is stable.
4. Optional Moomoo annotation import only if an official/user export format is
   confirmed.
