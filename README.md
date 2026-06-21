# Stock Investor

A long-running, evidence-based portfolio monitoring project.

For teammates joining the project, start with
[Research Findings](docs/RESEARCH_FINDINGS.md),
[Collaborating Safely](docs/COLLABORATING.md), and the
[Continuous Execution Plan](docs/CONTINUOUS_EXECUTION_PLAN.md) and
[Long-Horizon Roadmap](docs/LONG_HORIZON_ROADMAP.md). To connect real portfolio
data safely, follow the [Robinhood MCP Setup](docs/ROBINHOOD_MCP_SETUP.md).

The system is designed to answer a narrower and more useful question than
"what will the market do next?":

> Does this holding or watchlist candidate deserve attention today, and why?

It combines independent signals, portfolio risk, and explicit rules to produce
review alerts. It does not promise perfect entry or exit prices, and it does
not place trades automatically.

## Principles

- Protect against avoidable portfolio risk before seeking extra return.
- Combine several durable signals instead of trusting one indicator.
- Explain every alert in plain language.
- Treat backtests skeptically and validate strategies out of sample.
- Require human approval for every trade until a strategy has earned trust.
- Never store Robinhood passwords, MFA codes, session cookies, or recovery
  credentials.

## Daily Monitor

The dependency-free Python monitor calculates trend, momentum, drawdown, and
portfolio concentration from daily adjusted closes. It combines those values
with explicit fundamental scores and generates one of:

- `BUY_CANDIDATE`: attractive enough for deeper research, not an instruction.
- `ADD_CANDIDATE`: an existing, undersized holding may deserve a limited add.
- `HOLD`: no strong action signal.
- `REVIEW`: something changed and deserves attention.
- `TRIM_REVIEW`: portfolio risk or deterioration may justify reducing exposure.
- `DATA_REVIEW`: missing, stale, or insufficient data prevents a sound result.

Generate and run the complete demo:

```bash
python3 examples/generate_demo_prices.py
PYTHONPATH=src python3 -m stock_investor.cli monitor \
  examples/positions.csv examples/prices.csv --history data/alerts.jsonl
```

To fetch account-aligned real daily bars without credentials, use the Yahoo Finance chart
fallback. It is the default provider for the always-on Mac refresh workflow:

```bash
PYTHONPATH=src python3 -m stock_investor.cli fetch-yahoo \
  portfolio/positions.csv data/prices.csv
PYTHONPATH=src python3 -m stock_investor.cli monitor \
  portfolio/positions.csv data/prices.csv \
  --account-summary portfolio/robinhood-summary.json \
  --history data/alerts.jsonl
```

For a scheduled job, use the one-command daily workflow:

```bash
export SEC_USER_AGENT="stock-investor your-email@example.com"
PYTHONPATH=src python3 -m stock_investor.cli daily \
  portfolio/positions.csv data/prices.csv \
  --account-summary portfolio/robinhood-summary.json \
  --fundamentals data/fundamentals.json --refresh-sec \
  --filing-state data/filing-state.json \
  --filing-alerts data/filing-alerts.jsonl \
  --risk-history data/portfolio-risk.jsonl \
  --risk-policy examples/risk-policy.json \
  --theses examples/theses.json \
  --outcomes data/alert-outcomes.json --benchmark SPY \
  --feedback data/alert-feedback.jsonl \
  --brief-output data/daily-brief.md
```

Alpaca support remains in the codebase only as an explicit opt-in provider for
users who already have a valid reason and their own read-only market-data
credentials. It is not required for normal operation.

## Robinhood Read-Only Import

Robinhood's official Trading MCP can read positions, balances, and transactions
across all linked Robinhood accounts, while trade placement is restricted to
the dedicated Agentic account. This project treats the connection as read-only.

Convert a sanitized MCP snapshot into monitor-ready holdings:

```bash
PYTHONPATH=src python3 -m stock_investor.cli sanitize-robinhood \
  portfolio/combined-robinhood-read.json portfolio/robinhood-snapshot.json
PYTHONPATH=src python3 -m stock_investor.cli import-robinhood \
  portfolio/robinhood-snapshot.json portfolio/positions.csv \
  portfolio/robinhood-summary.json --metadata portfolio/positions.csv \
  --baseline-history portfolio/robinhood-baselines.jsonl
```

The normalized snapshot format is shown in
[examples/robinhood-snapshot.json](examples/robinhood-snapshot.json). It
contains `accounts`, each with `cash`, `buying_power`, and equity `positions`
containing `symbol`, `quantity`, `average_cost`, and optional `asset_type`.
`sanitize-robinhood` whitelists only balances and monitor-required position
fields, dropping account numbers, nicknames, instrument IDs, and other fields.
The importer aggregates the same ticker across accounts using weighted average
cost, preserves existing risk metadata and watchlist rows, skips non-equity
positions, and writes a sanitized summary. Optional baseline history appends
only when holdings or balances change. New holdings intentionally receive blank
sector and fundamental metadata, which blocks buy/add alerts until reviewed.

Use either `--account-summary` or `--cash`, never both. Store all real snapshots,
positions, and summaries under the ignored `portfolio/` directory.

Robinhood MCP daily historical responses can also feed the monitor without
Alpaca credentials. Export the read-only `get_equity_historicals` response with
`interval=day`, `bounds=regular`, and split adjustment, then convert it:

```bash
PYTHONPATH=src python3 -m stock_investor.cli import-robinhood-prices \
  portfolio/robinhood-historicals.json data/private/robinhood-prices.csv
```

The importer rejects non-daily intervals, removes explicitly interpolated
gap-fill bars, and writes the same long-form price format used elsewhere.
Because Robinhood notes that the newest historical bar may not be the official
settled close, live monitoring should refresh after settlement or reconcile the
latest date with the official quote close.

`fetch-sec` uses the SEC's official ticker-to-CIK mapping and Company Facts API
to calculate annual quality and valuation scores. The SEC requires an
identifying user agent, and the client paces requests below its published
10-requests-per-second fair-access limit:

```bash
export SEC_USER_AGENT="stock-investor your-email@example.com"
PYTHONPATH=src python3 -m stock_investor.cli fetch-sec \
  portfolio/positions.csv data/prices.csv data/fundamentals.json
```

SEC-derived scores retain the CIK, fiscal year, filing date, annual form,
taxonomy, reporting currency, component metrics, and warnings. Facts from
different fiscal years or currencies are never mixed. US-GAAP `10-K` and IFRS
`20-F` quality ratios are supported. IFRS/ADR valuation is intentionally
disabled until point-in-time currency conversion and ADR ratios are available.
SEC scores older than 550 days block buy/add alerts. They are not
sector-adjusted, so financial companies require separate review.

Monitor new material filings separately or through the daily command:

```bash
PYTHONPATH=src python3 -m stock_investor.cli check-filings \
  portfolio/positions.csv data/filing-state.json \
  --alerts data/filing-alerts.jsonl
```

The first filing check establishes a baseline without flooding old reports.
Later checks emit each unseen `10-K`, `10-Q`, or `8-K` once, including a direct
SEC filing URL. The monitor uses the SEC submission's structured 8-K item
numbers to label events such as earnings releases, acquisitions, bankruptcy,
cybersecurity incidents, impairments, delisting risk, unreliable financial
statements, and changes in control. High-impact categories are highlighted for
review. This classifies issuer-reported metadata; it does not claim to interpret
the filing's full text or predict the stock-price reaction.

The alert history is append-only and idempotent for the same symbol, market
date, model version, action, score, and reasons. `HOLD` results are not
persisted. Each record includes an immutable alert ID, model version, signal
date, and entry close.

The complete refresh also writes a separate append-only daily decision ledger
for every monitored symbol. Unlike alert history, it includes `HOLD` and
ordinary `REVIEW` decisions. Forward evaluation treats `HOLD` as remaining
long, treats `TRIM_REVIEW` inversely, and records raw and benchmark-relative
outcomes for `REVIEW` without inventing a directional win rate. `DATA_REVIEW`
states remain in the audit ledger but are excluded from investment-performance
claims.

Measure recorded alerts as new price history arrives:

```bash
PYTHONPATH=src python3 -m stock_investor.cli evaluate-alerts \
  data/alerts.jsonl data/prices.csv data/alert-outcomes.json --benchmark SPY
```

Outcomes include 21, 63, and 126-session returns, directional returns,
benchmark-relative returns, and maximum adverse/favorable excursion. Buy/add
alerts succeed directionally when prices rise; trim alerts succeed when prices
fall. Pending alerts remain visible. Alerts of the same model, ticker, and
action within 21 trading sessions are treated as one episode so repeated daily
signals do not falsely inflate the sample size.

`--scorecard data/scorecard.json` persists the grouped model-version results.
When `--benchmark SPY` is used with `daily`, the benchmark is fetched
automatically. Scorecards are observational diagnostics, not proof that alerts
caused returns or will work in the future.

Generate a private static dashboard from the latest alerts, portfolio-risk
history, and scorecard:

```bash
PYTHONPATH=src python3 -m stock_investor.cli dashboard \
  data/private/model-v3-snapshot.json data/private/dashboard-v3.html \
  --risk-history data/private/model-v1-risk.jsonl \
  --scorecard data/private/model-v3-scorecard.json \
  --decision-scorecard data/private/model-v3-decision-scorecard.json \
  --comparison data/private/model-v1-v3-comparison.json \
  --fundamental-coverage data/private/fundamental-coverage.json \
  --kline-scorecard data/private/kline-scorecard.json \
  --wave-snapshot data/private/wave-snapshot.json \
  --wave-scorecard data/private/wave-scorecard.json \
  --wave-experiment-scorecard data/private/wave-experiment-scorecard.json \
  --wave-conditional-scorecard data/private/wave-conditional-scorecard.json \
  --direction-forecasts data/private/wave-direction-forecasts.jsonl \
  --direction-forecast-outcomes data/private/wave-direction-forecast-outcomes.json \
  --prices data/private/robinhood-prices.csv
```

The dashboard opens as a compact all-holdings portfolio board led by a large
green `BUY`, red `SELL`, or amber `WAIT` badge. BUY/SELL appears only when the
pooled 95% directional interval and cross-stock absolute-return breadth agree,
with at least 10 observations across eight symbols and no symbol above 25% of
the sample. The direction must also survive removing each contributing symbol
and recomputing the evidence. The percentage is the matching historical wave's
directional rate, not a guaranteed probability.

Every displayed BUY, SELL, and WAIT is also written to an append-only,
versioned direction ledger by the complete refresh. The direction scorecard
evaluates de-duplicated episodes after 21, 63, and 126 sessions and reports
matured versus pending observations, directional success, excursions, and
Brier score. WAIT is retained for coverage auditing without inventing a
directional win rate.
Current holdings are also joined back to the first direction forecast ever
persisted for that symbol in `first-observed-forecasts.json`. The dashboard's
Research tab shows the first forecast, current forecast, whether the model has
changed its view, and the first forecast outcome when it has matured.
`forecast-action-segments.json` adds an observational proxy comparison between
currently held, zero-share watchlist, and no-longer-listed forecast episodes.
It is explicitly not causal evidence that a forecast caused a trade or watchlist
decision.
Each complete refresh also publishes a private `portfolio-learning-review.md`
that summarizes model health, first-forecast accountability, proxy segment
comparisons, calibration status, and next learning priorities.
The board also shows close, gain/loss, and weight.
Robust BUY and SELL directions also show a structural review price range:
BUY uses the confirmed support zone and SELL uses the confirmed resistance
zone. The detail drawer uses a local vendored Lightweight Charts runtime for
candle-interval-specific candlesticks and volume, with support, resistance, target,
average-cost, current-price, pivot, and immutable forecast/outcome metadata supplied through
`chart-payloads-v1.json` beside the generated dashboard HTML. Daily, weekly,
monthly, quarterly, yearly, five-year, and all-history buttons redraw from the
available OHLCV history; the chart locks at the first and last available candle
instead of scrolling into empty space. The dashboard
refuses to invent a price when that structural zone is unavailable.
Clicking a holding opens its full evidence in a side panel. Larger research
tables and model-health diagnostics stay behind separate tabs. Directional
views are not certain predictions. Signal rankings use only matured forward
outcomes and always display sample size and pending observations.

When full OHLCV prices are supplied, each holding drawer leads with graphical
evidence and a 126-session daily candlestick chart. The chart overlays support
and resistance zones, the active confirmed-pivot wave, volume, and the current
direction conclusion. Dense metrics and raw reasons remain in a collapsed
advanced-details section.

The separate historical wave experiment replays each held symbol causally at
non-overlapping 21/63/126-session intervals. It reports endpoint return versus
SPY plus the maximum upside and downside reached inside each window. Rankings
use the conservative lower bound of a 95% benchmark win-rate interval so a
tiny sample cannot top the table on raw win rate. This remains exploratory
in-sample evidence and never changes investment actions automatically. The
current-wave analog ranking maps that evidence back to held symbols and labels
an analog favorable or cautionary only when pooled and cross-stock breadth
intervals agree, with at least 10 observations across eight symbols and no
single symbol supplying more than 25% of the sample.
Absolute direction and benchmark-relative evidence are deliberately separate:
the board requires robust absolute direction for BUY/SELL, while the research
tables also show whether the same wave historically beat SPY.
An additional predeclared conditional audit splits wave age into early,
mature, and extended cells and move size into volatility-normalized developing,
established, and extended cells. It can replace a broad analog only when the
same strict robustness gates pass for either absolute direction or
benchmark-relative evidence; otherwise the dashboard explicitly refuses the
extra precision. A conditional direction can be robust even while its
benchmark-relative result remains inconclusive, and the dashboard shows both.

Run two model versions against the same portfolio and preserve full snapshots,
including `HOLD` results, before comparing selectivity:

```bash
PYTHONPATH=src python3 -m stock_investor.cli monitor \
  portfolio/positions.csv data/private/robinhood-prices.csv \
  --account-summary portfolio/robinhood-summary.json \
  --model-version decision-support-v3 \
  --snapshot data/private/model-v3-snapshot.json \
  --history data/private/model-v3-alerts.jsonl
PYTHONPATH=src python3 -m stock_investor.cli compare-models \
  data/private/model-v1-snapshot.json data/private/model-v3-snapshot.json \
  --output data/private/model-v1-v3-comparison.json
PYTHONPATH=src python3 -m stock_investor.cli diagnose-fundamentals \
  portfolio/positions.csv --fundamentals data/private/fundamentals.json \
  --output data/private/fundamental-coverage.json
```

Full snapshots are required for honest selectivity measurement because the
append-only alert history intentionally omits `HOLD` results.

Run the complete offline, read-only evidence refresh after updating the
sanitized portfolio or price file:

```bash
PYTHONPATH=src python3 -m stock_investor.cli refresh \
  portfolio/positions.csv data/private/robinhood-prices.csv data/private \
  --model-version decision-support-v3 \
  --account-summary portfolio/robinhood-summary.json \
  --baseline-snapshot data/private/model-v1-snapshot.json \
  --benchmark SPY \
  --price-source "Robinhood MCP read-only export" \
  --price-adjustment unknown \
  --production-safe
```

This writes the monitor snapshot, append-only alerts and all-decision ledger,
K-line and structural-wave observations, portfolio-risk history, forward
outcomes, scorecards, diagnostics, the machine-readable `model-health.json`
gate summary, per-symbol `price-health.json` freshness/provenance report,
deterministic `input-integrity.json` SHA-256 fingerprints, comparison,
dashboard, and finally
`refresh-manifest.json`. The manifest is written last so an interrupted run
cannot appear current.

`--production-safe` refuses to run unless the output is under a private
directory and account summary, price source, and adjustment semantics are
explicitly supplied.

Production-safe refreshes also use an atomic `.refresh.lock`; overlapping runs
are rejected and the lock is removed after either success or failure.

Every completed refresh appends `refresh-history.jsonl` with duration, status,
input hashes, and per-artifact byte sizes. The current manifest remains the
last-written current-state artifact.

All current-state JSON, CSV, text, and dashboard artifacts use same-directory
temporary files followed by an atomic replace. An interrupted writer therefore
preserves the previous complete artifact. Append-only forecast, decision,
risk, feedback, and refresh histories remain append-only.

Check freshness without running analysis:

```bash
PYTHONPATH=src python3 -m stock_investor.cli check-refresh \
  data/private/refresh-manifest.json --max-age-hours 36
```

The command exits non-zero when the manifest is missing or stale.

## Always-On Mac Dashboard

Install the macOS `launchd` services to keep the private dashboard online on
this Mac and attempt a complete market-data refresh every 30 minutes:

```bash
chmod +x scripts/run_market_refresh.sh scripts/install_macos_services.sh
scripts/install_macos_services.sh
```

The stable bookmark URL is `http://127.0.0.1:8765/`. It loads the current
private dashboard without exposing the versioned HTML path, so the bookmark can
stay fixed as the dashboard evolves. The direct legacy path
`http://127.0.0.1:8765/data/private/dashboard-v3.html` also remains available.
The service is intentionally bound to localhost because it contains private
portfolio data. `launchd` starts it after login and restarts it after a crash.

Unattended latest-market-data updates use Yahoo Finance chart data by default
and do not require credentials. A private runtime file at
`~/Library/Application Support/stock-investor/data/private/service.env` is only
needed for optional settings such as archive retention.

macOS privacy controls prevent background LaunchAgents from reliably reading
`Documents`, so the installer keeps private runtime data under
`~/Library/Application Support/stock-investor`. The repo remains the source of
truth for code: the installer records the repo path in `.source-root`, and the
scheduled refresh self-syncs application code from that repo before generating
the dashboard. Re-run the installer only after moving the repo or changing
LaunchAgent templates, not after ordinary code edits.

The refresh service fetches account-aligned daily bars through Yahoo Finance chart
data by default. Set `ACCOUNT_HISTORY_START_DATE=YYYY-MM-DD` in the private
`data/private/service.env` file to anchor charts at the brokerage account open
date; `YAHOO_START_DATE` remains as a lower-priority manual override. If neither
is set, the service falls back to the recent two-year window. The fetched bars
are merged with the existing price file so unsupported or delisted
symbols keep their last known history, atomically replaces the price input only
after a successful fetch, then runs the production-safe evidence refresh. It
uses bounded Yahoo provider retries and classifies provider failures in the
refresh log as network, rate-limit, server/timeout, client, no-data, or
invalid-response events. Retryable classes are retried before the existing
merged history is used as stale fallback context. It
also creates one credential-free private archive per day under
`data/private/archives/` and retains 30 daily archives by default. It never
deletes source ledgers or rewrites forecasts; only expired archive bundles are
pruned. Set `ARCHIVE_KEEP_DAYS` in `service.env` to change the archive
retention period. Every scheduled run safely restores the daily bundle into an
isolated temporary directory, rejects unsafe paths, links, credentials, and
logs, parses every JSON/JSONL artifact, and confirms that all
manifest-declared artifacts are present.

Alpaca remains available only as an explicit opt-in override for users who
want that provider:

```bash
ENABLE_ALPACA_MARKET_DATA=1
APCA_API_KEY_ID="..."
APCA_API_SECRET_KEY="..."
ALPACA_FEED="iex"
```
Service logs are under `data/private/logs/`. macOS cannot serve or refresh
while the machine is shut down or asleep.

GitHub runs CodeQL's extended Python security queries on pushes, pull requests,
and weekly schedules. Pull requests also fail when dependency review detects a
new moderate-or-higher vulnerability. Dependabot checks Python and GitHub
Actions dependencies weekly. A permanent integration test fails if runtime
code introduces a brokerage order, cancellation, watchlist write, or HTTP
POST/PUT/PATCH/DELETE request.

Record your judgment and response without changing the original alert:

```bash
PYTHONPATH=src python3 -m stock_investor.cli list-alerts \
  data/alerts.jsonl --feedback data/alert-feedback.jsonl
PYTHONPATH=src python3 -m stock_investor.cli feedback \
  data/alerts.jsonl data/alert-feedback.jsonl ALERT_ID \
  --label HELPFUL --response WATCHING --note "Research before sizing"
```

Feedback is append-only; the latest entry for an alert is used in reports while
earlier judgments remain auditable. Labels are `HELPFUL`, `NOT_HELPFUL`, or
`UNSURE`. Responses are `ACTED`, `WATCHING`, `DISMISSED`, or `NO_ACTION`.
Supplying `--feedback` to `daily` or `evaluate-alerts` joins the latest judgment
to each outcome and adds helpful and acted rates to the scorecard. These rates
measure usability and behavior, not investment performance.

Generate a concise brief from recent action alerts, portfolio-risk breaches,
material filings, and feedback:

```bash
PYTHONPATH=src python3 -m stock_investor.cli brief data/weekly-brief.md \
  --period weekly --alerts data/alerts.jsonl \
  --risk-history data/portfolio-risk.jsonl \
  --filing-alerts data/filing-alerts.jsonl \
  --feedback data/alert-feedback.jsonl
```

The `daily` workflow can create the same artifact with `--brief-output`; choose
`--brief-period weekly` for a seven-day lookback. Briefs repeat neither old
idempotent alerts nor a recommendation to trade, and remain suitable for an
external scheduler or reminder.

The active model contract is recorded in
[models/decision-support-v1.json](models/decision-support-v1.json). Any
behavioral model change must receive a new version so old and new outcomes are
never blended silently.

Normalized snapshot scoring remains available for research:

```bash
PYTHONPATH=src python3 -m stock_investor.cli score examples/snapshot.json
```

Walk-forward test the initial technical rule before trusting it:

```bash
PYTHONPATH=src python3 -m stock_investor.cli backtest \
  examples/prices.csv --cost-bps 10
```

The backtest is intentionally modest: it uses a monthly long/cash
trend-momentum rule, applies decisions only to later returns, charges a
configurable cost on every position change, and compares with buy-and-hold.
It is a research tool, not evidence that future returns will match history.

For a formal holdout test, declare the untouched period before inspecting its
results and write it once to a new report path:

```bash
PYTHONPATH=src python3 -m stock_investor.cli backtest-oos \
  data/prices.csv data/oos/decision-support-v1-2026.json \
  --test-start 2025-01-01 --cost-bps 10
```

The dedicated OOS runner uses only information available before each evaluated
return, excludes all pre-test returns, records the model version and parameters,
and refuses to overwrite an existing report. Choose the split before looking at
the holdout results; creating another output path after seeing disappointing
results defeats the purpose.

Run tests:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

See [docs/STRATEGY.md](docs/STRATEGY.md) for the research-backed strategy and
phased roadmap.

## Input Files

`positions.csv` contains holdings and watchlist names. Set `shares` to `0` for
a watchlist candidate. Fundamental scores are values from `-1`
(poor/expensive/deteriorating) to `1` (strong/cheap/improving). Leave quality
or valuation blank to use a supplied SEC snapshot. Revisions remain manual
because SEC filings do not contain analyst-estimate revisions. V1 and v2
require revisions for buy/add reviews; experimental v3 treats unavailable
revisions as neutral while still requiring quality and valuation. Missing
required fundamentals block buy/add alerts, while risk alerts still operate.

```csv
symbol,shares,average_cost,max_portfolio_weight,quality,valuation,revisions,thesis_broken,cik,sector,theme
AAPL,10,180,0.15,,,0.4,false,320193,Technology,AI
```

The optional `cik` avoids ticker-resolution ambiguity; otherwise the SEC's
official ticker mapping is used. Store real holdings under the ignored
`portfolio/` directory.

## Investment Theses

Use a structured thesis file to make sell reviews depend on the original
business case rather than emotion:

```json
{
  "AAPL": {
    "summary": "Services and installed-base cash flow remain durable.",
    "status": "ACTIVE",
    "review_by": "2026-12-31",
    "invalidation_rules": {
      "revenue_growth_below": -0.05,
      "free_cash_flow_margin_below": 0.15
    }
  }
}
```

Supported rules compare available SEC-derived metrics using `_below` floors or
`_above` ceilings. A breached rule or `BROKEN`/`CLOSED` status creates a
`TRIM_REVIEW` for a held position. An overdue review creates `REVIEW` without
pretending the thesis is broken. Missing metrics create warnings, not invented
conclusions. When `--theses` is supplied, every held position without a thesis
is flagged for review.

`prices.csv` uses long-form daily adjusted bars:

```csv
date,symbol,close,open,high,low,volume
2026-06-10,AAPL,200.50,198.25,201.40,197.80,55740700
```

Only `date`, `symbol`, and `close` are required. Use adjusted values so splits
and dividends do not create false signals. Full K-line analysis uses optional
OHLCV fields to measure ATR, volume confirmation, 20-session breakout distance,
recent-range position, gaps, and candle bodies. Features are persisted under
the model-independent `kline-v1` version and evaluated at 21/63/126 sessions
before they receive any directional interpretation. Portfolio weights include
only listed positions unless `--cash` is supplied.

This is not a day-trading system. Daily bars support multi-week to multi-month
decisions. The model-independent `wave-v1` layer uses causally confirmed
percentage-reversal pivots to describe the active wave, its age and return, and
structural support and resistance zones. Exact tops and bottoms are unknowable;
wave observations are append-only and evaluated at 21/63/126 sessions before
they can influence investment actions. A separate causal historical replay
provides earlier exploratory evidence, but it is kept distinct from the live
out-of-sample learning loop.

## Portfolio Risk Controls

The monitor evaluates candidates in the context of the whole portfolio:

- Sector exposure blocks buy/add reviews at the configured limit.
- Optional theme exposure captures cross-sector bets such as AI or China.
- Correlation exposure uses 120 aligned daily returns and blocks candidates
  that behave too much like already-large holdings.
- Annualized volatility produces a suggested maximum weight using a fixed
  per-position risk budget.
- Optional benchmark proxies estimate each holding's rolling beta and the
  portfolio's cash-aware aggregate factor exposure.
- Negative cash from margin accounts is preserved. Gross exposure above the
  configured limit creates a high-severity leverage alert.
- Missing sector, volatility sizing, or required correlation history blocks
  buy/add reviews instead of silently treating unknown risk as safe.

Portfolio-level breaches are printed and can be persisted with
`--risk-history`. Copy and edit [examples/risk-policy.json](examples/risk-policy.json)
to set limits appropriate for the account. The daily workflow automatically
fetches factor proxy prices configured in that policy; both `fetch-yahoo` and
the optional `fetch-alpaca` provider accept repeatable `--extra-symbol`
arguments for manual workflows.

The example policy uses `SPY` as a transparent broad-US-market proxy and alerts
when absolute portfolio beta exceeds `1.25`. Beta is estimated from aligned
daily returns over the configured correlation lookback and aggregated using
actual portfolio weights including cash. It is a backward-looking sensitivity
diagnostic, not a stable trait, return forecast, or complete factor model.
`gross_exposure_limit` defaults to `1.0`; a margin account above 100% gross
exposure is flagged. Set `gross_exposure_blocks_buy` to `true` only when that
breach should also suppress buy and add candidates.
These are guardrails, not forecasts.
