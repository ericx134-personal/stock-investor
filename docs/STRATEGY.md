# Strategy and Roadmap

## Product Decision

This project should be a decision-support system before it becomes a trading
system. There is no universally reliable "best indicator," and a precise buy or
sell price implies more certainty than the evidence supports. The product will
instead produce explainable review zones and record what happened afterward.

The system does not day trade. Daily OHLCV bars are inputs for decisions about
multi-week to multi-month price waves. Exact wave highs and lows cannot be known
in advance, so the system describes confirmed pivots, active-wave direction and
age, and structural support and resistance zones rather than issuing precise
top or bottom calls.

## Signal Model

The initial score combines independent categories:

| Category | Purpose | Initial weight |
| --- | --- | ---: |
| Trend | Avoid fighting persistent deterioration | 25% |
| Momentum | Measure medium-term relative strength | 20% |
| Quality | Prefer profitable, financially safer businesses | 25% |
| Valuation | Avoid paying an unjustifiable price | 20% |
| Earnings revisions | Detect changing business expectations | 10% |

Each input is normalized from `-1` to `1`. A high composite score creates a
`BUY_CANDIDATE` for a watchlist name or an `ADD_CANDIDATE` for an undersized
holding, never an automatic order. Add signals are suppressed when a holding is
within 20% of its configured size limit. Sell-side reviews also consider
position concentration, drawdown, and thesis status.

Technical measurements implemented in the daily monitor:

- Trend: price relative to 200-day moving average and slope of that average.
- Momentum: total return over the prior 12 months, excluding the latest month.
- Volatility: use it for position sizing and risk, not directional prediction.
- Drawdown: trigger a thesis review, not a blind market sell order.

Full daily K-line/OHLCV evidence is also preserved when available:

- ATR over completed recent bars measures trading-range volatility.
- Volume ratio compares the latest completed bar with its recent average.
- Breakout distance compares the live close with the prior 20-session high.
- Recent-range position shows where the close sits between recent high and low.
- Gap and candle-body measurements remain pending until the latest bar settles.

These chart features are observational and do not change investment actions.
Each daily `kline-v1` observation is append-only and evaluated at 21, 63, and 126
sessions using raw returns before any bullish or bearish meaning is assigned.

The separate `wave-v1` evidence layer applies a causal percentage-reversal
zigzag to completed daily bars. It records only pivots that were confirmable at
the time, then describes the active structural wave, support and resistance
zones, and position within the structural range. Wave observations are also
append-only and evaluated at 21, 63, and 126 sessions. They remain explanatory
evidence until enough real forward outcomes mature.

The initial normalizations are deliberately simple and recorded in code. They
are hypotheses to validate, not optimized parameters:

- Trend combines distance from the 200-day average with its recent slope.
- Momentum uses the prior 12-month return excluding the latest month.
- Both are clamped to `-1` through `1` to prevent one signal dominating.

Fundamental measurements:

- Quality: profitability, cash generation, balance-sheet safety, and growth.
- Valuation: compare a company with its own history and relevant peers.
- Revisions: changes in forward revenue and earnings expectations.

### SEC Fundamental Model

The current objective model uses standardized annual Company Facts from the
SEC. All component facts must match the same fiscal-year end.

Quality is the mean of at least four available normalized measures:

- Net margin, with 20% mapped to the top of the range.
- Free-cash-flow margin, with 15% mapped to the top.
- Return on assets, with 15% mapped to the top.
- Equity-to-assets ratio, centered around conservative balance-sheet strength.
- Annual revenue growth, with 20% mapped to the top.

Valuation requires both earnings yield and free-cash-flow yield, with 8% mapped
to the top of each range. Scores are clamped from `-1` to `1`.

These thresholds are transparent starting hypotheses, not optimized claims.
The model records the CIK, fiscal end, filing date, component metrics, source,
and warnings. It refuses to create a score when standardized facts are
insufficient, blocks buy/add alerts when required fundamentals are missing or
stale, and warns that financial companies require separate treatment.

The parser supports US-GAAP annual facts from `10-K` filings and IFRS annual
facts from `20-F` filings. IFRS quality ratios use facts from one taxonomy,
currency, and fiscal period. IFRS/ADR valuation remains unavailable because a
USD-listed ADR price cannot safely be compared with foreign-currency ordinary
share facts without point-in-time FX and ADR-ratio data.

## Risk Rules Before Return Rules

- [x] Alert when one position exceeds its configured maximum weight.
- [x] Block buy/add reviews at configured sector or theme limits.
- [x] Detect highly correlated holdings using aligned daily returns.
- [x] Suggest maximum position weights from an annual volatility risk budget.
- Keep an untouchable diversified core separate from active ideas.
- Size positions using risk budget and conviction, not excitement.
- Use limit orders thoughtfully; stop and stop-limit orders have distinct risks.
- Include taxes, spread, slippage, and turnover in every backtest.

### Portfolio Risk Model

The default risk policy is explicit and configurable:

| Rule | Default |
| --- | ---: |
| Sector exposure limit | 35% |
| Theme exposure limit | 25% |
| Highly correlated exposure limit | 40% |
| High-correlation threshold | 0.75 |
| Correlation lookback | 120 daily returns |
| Minimum aligned observations | 60 |
| Annual risk budget per position | 2.5% |

Suggested maximum weight is the lower of the ticker's configured maximum and
`annual risk budget / annualized volatility`. This is sizing guidance, not a
claim that volatility is stable. Correlation can rise sharply during crises,
so the model treats it as an additional concentration warning rather than a
diversification guarantee. Missing required risk data blocks buy/add reviews.

Optional factor proxies add a transparent regression diagnostic. For each
holding, beta is estimated as covariance with the proxy divided by proxy
variance over aligned daily returns. Portfolio factor beta is the cash-aware
weighted sum of held-position betas. The default example uses `SPY` as a broad
US-market proxy and alerts beyond an absolute beta of `1.25`.

This is intentionally not a claim that one ETF explains the portfolio or that
historical beta will persist. Missing proxy or holding history creates an
explicit portfolio-risk alert rather than a fabricated exposure.

Gross exposure is always reported and can alert above a configured limit.
Whether that alert blocks buy/add candidates is a separate policy choice,
because an experienced user may intentionally accept margin exposure.

### Thesis-Driven Sell Reviews

Every held active idea should have a short written thesis, a review date, and
measurable invalidation rules. Supported rules compare SEC-derived metrics
against explicit floors (`*_below`) or ceilings (`*_above`).

- A breached rule or a `BROKEN`/`CLOSED` thesis creates `TRIM_REVIEW`.
- An overdue review date creates `REVIEW`, not an automatic sell.
- Missing metrics produce warnings instead of a false pass or failure.
- When thesis monitoring is enabled, a held position without a thesis is
  explicitly flagged.

This keeps price drawdowns from becoming automatic sales while still forcing a
decision when the business case changes.

## Validation Standard

No strategy is promoted because of one attractive backtest.

1. Define the rule before evaluating it.
2. Use point-in-time data and avoid survivorship/look-ahead bias.
3. Reserve an untouched out-of-sample period.
4. Compare against a simple benchmark.
5. Include realistic trading costs and taxes.
6. Paper-monitor for at least one market regime.
7. Record every model version and every alert.

### Live Alert Evaluation

Every investment-action alert records an immutable ID, the active model
version, signal date, and closing price. As later daily bars arrive, the
evaluation workflow measures:

- Raw and direction-aware returns after 21, 63, and 126 trading sessions.
- Benchmark-relative returns when a benchmark is configured.
- Maximum adverse and favorable excursion over the available 126-session window.
- Pending status when a horizon has not matured.

Repeated alerts with the same model, ticker, and action inside 21 trading
sessions count as one episode. This reduces false confidence from overlapping
observations. Scorecards remain observational and must not be treated as causal
evidence or permission to optimize repeatedly against the same live sample.

A separate append-only all-decision ledger records every daily model state. It
includes `HOLD` and ordinary `REVIEW` decisions that are intentionally absent
from actionable alert history. `HOLD` is evaluated as remaining long,
`TRIM_REVIEW` rewards subsequent decline, and `REVIEW` retains raw and
benchmark-relative outcomes without a directional success claim. `DATA_REVIEW`
is retained for audit coverage but excluded from investment-performance
scorecards.

### Dashboard Evidence Rules

The dashboard ranks signal types by matured directional win rate only when
forward outcomes exist. Every ranking must show its observation count and
pending count; a high win rate from a small sample is not presented as strong
evidence. Per-holding labels are directional views such as bullish candidate,
neutral, caution, or bearish/trim review, never promises of a future price.

The default dashboard surface is a compact all-holdings portfolio board.
It leads with a large color-coded BUY/SELL/WAIT badge and the matching
historical-wave directional rate, then close, gain/loss, and weight. BUY or
SELL requires the pooled 95% absolute-direction interval and per-symbol
positive-mean-return breadth interval to agree, at least 10 observations across
eight symbols, no symbol above 25% of the sample, and the same direction after
removing every contributing symbol one at a time. Otherwise the board shows
WAIT. The percentage is an exploratory analog rate, not a calibrated
probability.
Holding evidence opens in a side panel; research tables and model-health
diagnostics remain behind separate tabs so the main portfolio view stays
glanceable.

The holding side panel explains high-confidence directions graphically before
showing raw metrics. It combines a directional-probability ring, pooled and
cross-stock evidence bars, and a 126-session daily K-line chart. Support and
resistance zones, the current confirmed-pivot wave, volume, and the direction
label are overlaid directly on the chart; dense text remains collapsed under
advanced details.

For a robust BUY or SELL direction, the dashboard derives a review price range
from the same confirmed structure: BUY maps to the support zone and SELL maps
to the resistance zone. The active range and reference midpoint are drawn
directly on the K-line chart; supporting text is kept in an info tooltip. The
dashboard refuses to invent a price if the matching structural zone is
unavailable.

The historical wave experiment is a separate exploratory surface. It replays
only information available at each historical signal date, uses non-overlapping
windows within each symbol and horizon, and reports return versus SPY plus
maximum favorable and adverse excursions. Historical wave rows are ranked by
the lower bound of a 95% benchmark win-rate interval, not raw win rate. This
reduces small-sample leaderboard noise but does not make the replay
out-of-sample; it cannot promote or modify live actions.

The current-holdings analog ranking applies the best-supported historical
horizon to each live wave regime. A favorable or cautionary label requires the
pooled benchmark win-rate interval and the per-symbol positive-excess breadth
interval to agree, at least 10 observations across eight symbols, and no single
symbol above 25% of the sample; otherwise the result is explicitly
inconclusive.

Absolute direction is evaluated separately from benchmark-relative evidence.
A wave can decline while still beating SPY, or rise while lagging SPY; the
dashboard therefore never converts relative evidence directly into BUY/SELL.

The conditional-wave audit uses fixed buckets selected before outcome review:
early (at most 10 sessions), mature (11–25), and extended (more than 25);
move size is developing (less than 1.5×), established (1.5–3×), or extended
(more than 3×) relative to the signal's causal reversal threshold. Conditional
evidence replaces a broad regime analog only when it passes the same pooled,
cross-stock, and concentration gates for either absolute direction or relative
performance. Thin cells remain visible but are explicitly refused as extra
precision. Direction and SPY-relative evidence keep separate classifications.

The v2 direction gate adds a leave-one-symbol-out requirement. It removes each
contributing symbol and recomputes the full pooled, breadth, and concentration
classification. A BUY or SELL survives only when every removal retains the
same direction. The prior `wave-direction-v1` ledger remains immutable;
forecasts under this stricter rule use `wave-direction-v2`.

Every direction displayed on the portfolio board is now recorded in a separate
append-only, versioned direction ledger. BUY and SELL forecasts retain their
displayed historical analog rate, selected broad or conditional evidence
source, horizon, and entry close. WAIT is also retained so coverage and
selectivity cannot be hidden. Repeated same-direction displays for one symbol
inside 21 sessions count as one episode.

The direction scorecard evaluates 21-, 63-, and 126-session raw,
benchmark-relative, and direction-aware returns, plus favorable and adverse
excursions. It reports forecast episodes, matured observations, pending
observations, directional success, and Brier score. WAIT has no invented
directional success or Brier score.

Alert burden is a model-health diagnostic. A model that asks for action review
on most holdings is likely too noisy even when its individual reasons are
valid. Future model versions should prove that they improve selectivity and
forward outcomes without silently changing or overwriting version 1.

The refresh pipeline also writes `model-health.json`, a versioned
machine-readable summary of explicit gates. Safety and required price-data
failures are blocking; data coverage and selectivity failures mark the model
degraded; insufficient matured outcomes remain pending rather than receiving a
false pass or failure.

`price-health.json` records each held symbol's latest date, calendar-day age,
history length, OHLCV completeness, and price-source provenance. Explicit
`--price-source` values are marked declared; conservative filename inference is
marked inferred or unknown. Fresh prices and complete K-line data remain
separate concepts.

### Model V2 Selectivity Experiment

`decision-support-v2` is an experimental candidate, not the promoted default.
It requires at least two independent deterioration signals for an ordinary
review, while preserving standalone reviews for severe drawdowns, concentration
breaches, and broken theses. It also raises the buy-candidate threshold from
`0.45` to `0.50`.

On the sealed June 12, 2026 real-portfolio snapshot, v2 reduced actionable
reviews from 22 of 27 holdings to 17 of 27. It demoted five unconfirmed
drawdown-only reviews to data review and preserved all 12 v1 trim reviews.
This improves selectivity but still exceeds the 50% alert-fatigue threshold.
V2 must remain experimental until its separately versioned forward outcomes
mature and compare favorably with v1. Ten of 27 holdings still require data
review, making missing fundamental coverage the next major confidence
bottleneck for buy/add decisions.

### Model V3 Fundamental-Coverage Experiment

`decision-support-v3` preserves v2's selectivity rules while treating
unavailable analyst revisions as an explicit neutral input. This does not
invent an estimate: revisions remain visible as missing and quality plus
valuation remain required for buy/add reviews. V2 is unchanged so its pending
outcomes remain reproducible.

The initial real-portfolio coverage audit found zero populated quality,
valuation, or revisions inputs across all 27 holdings. Consequently, v3
currently produces the same action distribution as v2. Its value can only be
measured after conservative SEC fundamental snapshots are populated.

### Human Feedback Loop

The system records feedback separately from immutable alerts. A user can label
an alert `HELPFUL`, `NOT_HELPFUL`, or `UNSURE`, record whether they acted,
watched, dismissed, or took no action, and add a note. Corrections append a new
entry; the latest entry is joined into outcome reports while the full history
remains auditable.

Helpful and acted rates reveal whether alerts support decisions or merely
create noise. They must be interpreted separately from forward returns: an
alert can be helpful without being profitable, and acting on an alert does not
prove that the model caused the result.

### Material Filing Events

New SEC filing alerts classify structured 8-K item numbers into readable event
categories. High-importance review flags cover bankruptcy, material
cybersecurity incidents, acquisitions or dispositions, financial-obligation
triggers, impairments, delisting risk, unreliable financial statements, and
changes in control. Item 2.02 identifies a reported earnings release.

The classification is deterministic and retains the original item numbers and
filing URL. It does not summarize unstructured filing text, determine whether
an event is good or bad for the investment thesis, or predict price impact.

### Dedicated Out-of-Sample Evaluation

The OOS runner requires a predeclared test start date and a new report path. It
uses the earlier history only as signal warm-up, makes every decision from data
available before the evaluated return, and excludes all pre-test returns from
performance. The sealed report records the model version, requested split,
actual per-symbol evaluation dates, costs, rebalance interval, and results, and
refuses to overwrite an existing report.

This protects the audit trail, but it cannot prevent a researcher from creating
many new reports. The holdout period must be chosen once before its result is
inspected; after inspection it becomes development data for any later model.

## Data and Account Access

Recommended sequence:

1. Read all linked Robinhood account positions and balances through the
   official Trading MCP, then convert a sanitized snapshot into monitor inputs.
2. Add a supported market-data provider for prices and news.
3. Add SEC EDGAR APIs for filings and standardized company facts.
4. Connect Robinhood's official Trading MCP only if desired. It can read
   positions and transactions across Robinhood accounts, but can place trades
   only in a dedicated Agentic account.

Never use unofficial login automation or store brokerage credentials.
Never persist Robinhood account numbers in monitoring artifacts. The importer
aggregates equity holdings across accounts, excludes non-equity positions, and
preserves separately maintained risk metadata.

## Delivery Phases

### Phase 1: Trustworthy Daily Brief

- [x] Portfolio and watchlist CSV import
- [x] Sanitized read-only Robinhood multi-account snapshot import
- [x] Provider-neutral daily adjusted-close import
- [x] Explainable review alerts
- [x] Concentration and drawdown warnings
- [x] Idempotent alert history
- [x] Automatic supported Alpaca adjusted-price ingestion
- [x] Sector, theme, correlation, and volatility-budget risk controls
- [x] Structured thesis notes, review dates, and measurable invalidation rules
- [x] Append-only user feedback labels and responses on individual alerts

### Phase 2: Research Lab

- [x] Reproducible initial technical-rule backtest
- [x] Buy-and-hold benchmark and transaction costs
- [x] Walk-forward decisions without same-close execution
- [x] Immutable model-versioned alert records
- [x] Forward 21/63/126-session alert outcome scorecards
- [x] Append-only all-decision ledger including HOLD and REVIEW outcomes
- [x] Episode de-duplication for repeated overlapping alerts
- [x] Dedicated predeclared, write-once out-of-sample evaluation
- [x] Machine-readable strategy version registry

### Phase 3: Rich Monitoring

- [x] SEC annual fundamental snapshots with filing provenance
- [x] Idempotent new `10-K`, `10-Q`, and `8-K` filing alerts
- [x] Structured 8-K material-event classification and importance
- [ ] Forward earnings-calendar alerts
- [x] Thesis notes and invalidation conditions
- [x] Sector, theme, correlation, and configurable proxy-factor exposure
- [x] Margin-aware cash and gross-exposure risk alerts
- [x] Daily and weekly brief generator ready for scheduling
- [x] Manifest-last read-only refresh pipeline and dashboard regeneration
- [x] Full daily K-line/OHLCV feature preservation and forward evaluation
- [x] Confirmed-pivot structural-wave evidence and long-horizon evaluation
- [x] Causal non-overlapping historical wave experiment with uncertainty
- [ ] Production schedule connected to the real portfolio

### Phase 3A: Real-Portfolio Learning Loop

- [x] Establish read-only access to the real Robinhood portfolio
- [x] Measure live leverage and single-name concentration
- [x] Make leverage tolerance independently configurable from leverage alerts
- [x] Persist sanitized live snapshots without account identifiers
- [x] Convert exported Robinhood MCP daily histories into monitor prices
- [x] Run the complete monitor on every held position using current daily bars
- [x] Establish a sealed baseline of model-v1 alerts before changing signals
- [ ] Compare alerts with 21/63/126-session forward outcomes and user feedback
- [ ] Promote changes only when they improve out-of-sample usefulness

The first sealed real-portfolio regime diagnostic found that long-horizon
momentum and drawdown frequently conflict: a holding can retain a strong
12-month return while remaining far below its peak, and recent behavior can be
either a rebound or continued deterioration. A recent-regime feature is now a
predeclared experiment candidate, but it must not change model-v1 until tested
under a new version with forward or sealed out-of-sample evidence.

### Phase 4: Limited Automation

- Paper trading first
- Robinhood official Agentic account only
- Small isolated capital allocation
- Position limits, trade previews, and immediate kill switch

## Research Basis

- Time-series momentum research documents return persistence over intermediate
  horizons: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2089463
- Quality research defines quality using profitability, growth, safety, and
  payout: https://www.aqr.com/Insights/Datasets/Quality-Minus-Junk-Factors-Monthly
- Backtest-overfitting research explains why selecting the best-looking tested
  strategy often fails out of sample:
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253
- Investor.gov explains asset allocation, diversification, and rebalancing:
  https://www.investor.gov/introduction-investing/getting-started/asset-allocation
- FINRA explains concentration risk:
  https://www.finra.org/investors/insights/concentration-risk
- Robinhood documents its official Agentic Trading access:
  https://robinhood.com/us/en/support/articles/agentic-trading-overview/
- SEC EDGAR provides public filing and company-facts APIs:
  https://www.sec.gov/search-filings/edgar-application-programming-interfaces
