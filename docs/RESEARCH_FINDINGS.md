# Research Findings And Evidence Register

This is the detailed research handoff for the stock-investor project. It
records the questions tested, methods used, results observed, negative
findings, limits, and next experiments so another teammate can continue
without repeating the same work.

The project is a read-only decision-support system for multi-week to
multi-month investing. It never places trades.

No private holdings, account balances, cost bases, account identifiers, or
ticker-level private outcomes belong in Git. Aggregate observations from the
authorized live universe are included only to explain research status. They
are not public validation and must be replicated on broader point-in-time
data.

## Executive Summary

The most important finding so far is not that a particular indicator predicts
prices. It is that honest directional prediction is rare once reasonable
statistical safeguards are applied.

The project currently has one broad wave-regime cell that passes a strict SELL
gate and one predeclared conditional wave cell that passes a strict BUY gate.
Almost every other cell remains WAIT. This is desirable: thin, concentrated,
or uncertain evidence should not be presented as conviction.

The current live decision model still has a serious alert-fatigue problem. It
asks for some form of attention on every monitored holding and produces no
ordinary HOLD decisions. Model v3 reduced the actionable rate from 81.5% to
63.0%, but that reduction mostly came from converting uncertain reviews into
DATA_REVIEW because required evidence was missing. It has not yet demonstrated
better investment outcomes.

No real live forecast has yet matured through even the first 21-session
evaluation window. Therefore:

- No displayed BUY or SELL is validated.
- No model version is proven better by forward returns.
- No K-line pattern is allowed to influence the promoted decision model.
- The current dashboard percentages are small-sample shrunk confidence scores;
  raw historical analog rates are preserved but are not calibrated
  probabilities.
- The highest-value next milestone is immutable forecast recording followed by
  patient 21/63/126-session evaluation.

## Research Objective

The original user need was: identify good times to buy and sell without day
trading, aiming to improve decisions around multi-week and multi-month price
waves.

This was translated into a narrower, testable product question:

> Which holdings deserve attention now, in which direction, why, and what
> happened after the system said so?

The system intentionally avoids claiming that it can identify exact tops or
bottoms. Exact turning points are only obvious after the fact, and optimizing
for them creates look-ahead bias.

## Core Product Conclusions

### Decision support is more defensible than automatic trading

Every signal should create a review opportunity, not an order. Human judgment
is still needed for business context, taxes, liquidity, personal conviction,
and information not represented in the model.

The permanent boundary is:

- Read portfolio and market data.
- Produce explainable BUY, SELL, WAIT, and portfolio-review evidence.
- Record forecasts and outcomes.
- Never place, cancel, or modify trades.

### Daily K-line data is the input frequency, not the trading frequency

Daily OHLCV bars contain useful structural information while avoiding the
noise and operational demands of intraday strategies. The target horizons are:

| Horizon | Interpretation |
| --- | --- |
| 21 sessions | Roughly one trading month |
| 63 sessions | Roughly one trading quarter |
| 126 sessions | Roughly half a trading year |

Repeated daily signals are de-duplicated into episodes separated by at least
21 sessions so that one persistent condition does not masquerade as many
independent successes.

### K-line charts explain evidence but do not create evidence by themselves

Candles, volume, support, resistance, and confirmed pivots make the state of a
holding understandable. Visual pattern recognition alone is too subjective
and too easy to fit after seeing the outcome.

The implemented rule is:

- Preserve chart features at the time they are observed.
- Evaluate their later 21/63/126-session returns.
- Keep them observational until enough forward outcomes mature.
- Never let a visually persuasive chart bypass statistical gates.

### Absolute direction and benchmark-relative performance are separate

A stock can decline and still beat SPY. It can rise and still lag SPY. These
answer different questions:

| Question | Metric |
| --- | --- |
| Is the stock likely to rise or fall? | Absolute forward return |
| Is the stock likely to outperform the market? | Return minus benchmark return |

BUY and SELL on the main board use absolute-direction evidence only.
Benchmark-relative evidence is shown separately and can remain inconclusive
even when absolute direction passes.

### WAIT is a useful prediction

WAIT means the system refuses to claim a direction. It is not missing output.
It is the expected result when evidence is thin, contradictory, concentrated,
or statistically weak.

A system that nearly always says BUY or SELL is likely optimizing for
engagement rather than decision quality.

## Implemented Model And Evidence Layers

| Layer | Status | Purpose |
| --- | --- | --- |
| `decision-support-v1` | Frozen baseline | Broad alerting baseline |
| `decision-support-v2` | Experimental | Higher selectivity through independent deterioration requirements |
| `decision-support-v3` | Current experimental decision model | v2 selectivity with unavailable revisions treated as neutral |
| `kline-v1` | Observational | Append-only OHLCV and chart-state features |
| `wave-v1` | Observational | Causal confirmed-pivot structural waves |
| `wave-walk-forward-v1` | Exploratory replay | Historical non-overlapping wave outcomes |
| `wave-conditional-v2` | Current exploratory audit | Predeclared conditions plus leave-one-symbol-out gate |
| `wave-direction-v1` | Frozen observational ledger | Original displayed forecasts preserved for forward evaluation |
| `wave-direction-v2` | Frozen observational ledger | Displayed forecasts requiring leave-one-symbol-out stability |
| `wave-direction-v3` | Frozen observational ledger | v2 plus explicit stale/poor data-quality blocking |
| `wave-direction-v4` | Current observational ledger | v3 plus small-sample probability shrinkage with raw rates preserved |
| `wave-direction-v4-candidate` | Frozen candidate, not promoted | Machine-readable candidate manifest with pending calibration gates |

None is promoted as a proven predictive model.

## Base Decision Model

### Signal construction

The base composite score combines five normalized inputs from `-1` to `1`:

| Signal | Weight | Intended role |
| --- | ---: | --- |
| Trend | 25% | Avoid fighting persistent deterioration |
| Momentum | 20% | Measure intermediate return persistence |
| Quality | 25% | Prefer profitable, safer businesses |
| Valuation | 20% | Avoid unjustifiable price |
| Earnings revisions | 10% | Detect changes in expectations |

The current v3 buy-candidate threshold is `0.50`. A high score alone is not
enough. Buy/add review also requires complete required fundamentals, nonnegative
quality, portfolio-risk permission, and room below the position-size limit.

### Sell/review construction

The decision model does not treat price decline alone as an automatic sell.
It creates review pressure from:

- Position weight above its configured maximum.
- Drawdown at or below `-30%`.
- Severe drawdown at or below `-50%`.
- Materially negative trend at or below `-0.50`.
- Materially negative revisions at or below `-0.50`.
- Broken, overdue, or missing thesis information.

Ordinary deterioration requires at least two independent signals in v2/v3,
unless the severe-drawdown threshold is crossed. A broken thesis or position
limit can create a trim review directly.

### Model v1 versus v3 result

The first authorized live-universe comparison covered 27 held positions:

| Metric | v1 | v3 | Change |
| --- | ---: | ---: | ---: |
| Actionable rate | 81.5% | 63.0% | -18.5 percentage points |
| DATA_REVIEW rate | 18.5% | 37.0% | +18.5 percentage points |
| HOLD rate | 0% | 0% | No improvement |
| Positions requesting any attention | 100% | 100% | No improvement |

Five ordinary REVIEW states became DATA_REVIEW under v3. The count of
TRIM_REVIEW states did not decline.

Interpretation:

- Requiring more complete evidence reduced unsupported actionability.
- The apparent selectivity improvement is mostly stricter missing-data
  handling, not demonstrated predictive improvement.
- The model still has alert fatigue because every holding requests attention.
- v3 must remain experimental until forward outcomes show better usefulness.

This is a negative but valuable result: changing labels is not the same as
improving decisions.

## Technical Signal Findings

### Long-horizon momentum and drawdown often conflict

The first real-portfolio diagnostic found many cases where a holding retained
strong long-horizon momentum while still sitting far below its prior high.
That state can describe either a genuine rebound or a temporary recovery
inside continued deterioration.

Finding:

- Momentum and drawdown are not interchangeable.
- A large drawdown does not prove a future decline.
- Strong trailing momentum does not prove the recovery will continue.
- The interaction needs a separately predeclared recent-regime experiment.

No model change was promoted from this observation.

### K-line feature coverage is good, but predictive evidence is absent

Full OHLCV/K-line features were available for 25 of 27 monitored positions,
or 92.6% coverage.

Implemented features include:

- 20-session ATR as a percentage of price.
- Current volume relative to the recent average.
- Distance from the prior 20-session high.
- Position within the recent high-low range.
- Latest gap and candle-body measurements when the bar is complete.

Finding:

- The data is useful for graphical explanation and future study.
- No live K-line forward outcome has matured.
- No individual candle or chart regime currently earns predictive authority.

### Structural waves are more explainable than exact top/bottom calls

### Price zones need walk-forward error scoring

The HOOD breakout on June 15, 2026 exposed a weakness in the first price-zone
display: a static SELL resistance band can become misleading after price closes
above its upper bound. In that state the old resistance is no longer a valid
sell cap; it should be treated as a breakout/retest area until forward price
action confirms rejection or support.

The next improvement loop should replay zone forecasts historically. For each
past session, pretend that day is "today," compute the available wave and
buy/sell/retest zone, then reveal later bars and score:

- Whether the zone was touched.
- Time to first touch.
- Whether price broke through and invalidated the zone.
- Whether a broken resistance later held as support, or broken support became
  resistance.
- Forward return and adverse/favorable excursion after touch or miss.
- Opportunity cost when the zone was too conservative and price never returned.

This is the right way to improve the zones: evaluate rolling pretend-day
forecast errors before changing thresholds or promoting a new model.

`wave-v1` uses a causal percentage-reversal zigzag on completed daily bars.
Only pivots confirmable with information available at the time are recorded.
The feature layer describes:

- Current advancing or declining wave.
- Confirmed structural support and resistance.
- Wave age in sessions.
- Active-wave return.
- Magnitude relative to the reversal threshold.
- Position within the structural range.

This representation is useful because it explains where price sits inside a
larger move without pretending the current bar is the final top or bottom.

## Wave Walk-Forward Experiment

### Experimental design

The historical wave replay:

1. Iterates through each eligible symbol chronologically.
2. Calculates the wave state using only bars available at the signal date.
3. Measures forward return at 21, 63, and 126 sessions.
4. Measures SPY-relative return where benchmark data aligns.
5. Measures maximum favorable and adverse excursion.
6. Uses non-overlapping windows within each symbol and horizon.
7. Aggregates results by broad wave regime.

The current replay produced:

- 225 historical non-overlapping observations.
- 18 broad regime/horizon scorecard cells.
- 64 predeclared conditional scorecard cells.

These counts are from an authorized private live universe and are not a broad
market sample.

### Robust absolute-direction gate

A broad or conditional cell becomes BUY or SELL only when all requirements
pass:

1. At least 10 observations.
2. At least eight distinct symbols.
3. No symbol contributes more than 25% of observations.
4. The pooled Wilson 95% interval for positive return excludes 50%.
5. The Wilson 95% interval for the share of symbols with positive mean return
   also excludes 50% in the same direction.

The cross-symbol gate matters because many observations from one ticker are
not broad evidence.

### Robust benchmark-relative gate

Relative evidence uses the same minimum observation, symbol-breadth, and
concentration requirements, but tests:

- The pooled rate of beating SPY.
- The share of symbols with positive mean excess return.

Relative evidence produces favorable, cautionary, or inconclusive research
labels. It never directly becomes absolute BUY or SELL.

### Broad wave finding

One of 18 broad regime/horizon cells passed the strict absolute SELL gate:

| Field | Aggregate result |
| --- | --- |
| Regime | Advancing wave near structural resistance |
| Horizon | 21 sessions |
| Observations | 19 |
| Distinct symbols | 16 |
| Positive-return rate | 21.1% |
| Symbols with positive mean return | 18.75% |
| Directional result | SELL |

Interpretation:

- In this sample, an advancing wave close to structural resistance was often
  followed by a negative one-month return.
- Breadth across symbols agreed with the pooled result.
- The result is plausible and passed the current gate.
- It is still exploratory because the universe is small, privately selected,
  and already inspected.

It must be replicated on a broader point-in-time universe and on future live
signals before promotion.

### Conditional wave finding and subsequent rejection

The conditional audit uses buckets defined before outcome review:

| Dimension | Buckets |
| --- | --- |
| Wave age | Early: <=10 sessions; Mature: 11-25; Extended: >25 |
| Wave magnitude | Developing: <1.5x reversal threshold; Established: 1.5-3x; Extended: >3x |

Under the original v1 gate, one of 64 conditional cells passed the strict
absolute BUY gate:

| Field | Aggregate result |
| --- | --- |
| Broad regime | Advancing wave |
| Wave age | Mature |
| Wave magnitude | Developing |
| Horizon | 21 sessions |
| Observations | 18 |
| Distinct symbols | 14 |
| Positive-return rate | 83.3% |
| Symbols with positive mean return | 78.6% |
| Absolute-direction result | BUY |
| SPY-relative result | Inconclusive |

Interpretation:

- In this sample, a mature but still-developing advancing wave often continued
  rising over the next month.
- The result was broad enough across symbols to pass the absolute gate.
- The cell did not prove that the same stocks would beat SPY.
- Conditional evidence can reveal useful distinctions hidden by a broad
  regime, but only when the same strict gates pass.

The later leave-one-symbol-out audit rejected this BUY. Removing each
contributing symbol in turn retained BUY status in only 3 of 14 runs, a 21.4%
stability rate. The original pooled and cross-symbol intervals were real, but
the cell sat too close to the minimum breadth and confidence thresholds to
survive modest universe changes.

The original `wave-direction-v1` BUY forecasts remain immutable for honest
forward evaluation. The current v2 gate downgrades the pattern to WAIT and
requires 100% leave-one-symbol-out classification stability.

### Negative wave findings

The negative results are more important than the two passing cells:

- 17 of 18 broad cells remained WAIT for absolute direction.
- 63 of 64 conditional cells remained WAIT for absolute direction.
- All 64 conditional cells remained inconclusive on benchmark-relative
  evidence.
- Sparse long-horizon cells produced wide confidence intervals.
- Raw win rates often looked interesting but failed breadth or uncertainty
  gates.

This shows why ranking by raw win rate alone would be misleading.

After leave-one-symbol-out gating, all conditional cells are WAIT. The broad
near-resistance SELL remains supported after removing each of its 16
contributing symbols.

### Current live-board mapping

When the exploratory wave evidence was mapped back to the 27 current holdings,
the original v1 board produced:

| Direction | Holdings |
| --- | ---: |
| BUY | 3 |
| SELL | 1 |
| WAIT | 23 |

The four directional labels inherit the exploratory cells above. They are not
independent forecasts, and they are not yet validated by future live outcomes.
The 23 WAIT results are evidence that the gate is behaving conservatively.

After the leave-one-symbol-out v2 gate, the current board becomes 0 BUY,
1 SELL, and 26 WAIT. This is a deliberate loss of apparent opportunity in
exchange for evidence that is less dependent on the selected symbol universe.

## Fundamental Research Findings

### Current coverage result

The first live refresh had:

| Required evidence | Coverage |
| --- | ---: |
| Quality | 0% |
| Valuation | 0% |
| Earnings revisions | 0% |
| v3 buy-ready holdings | 0 |

This does not mean the companies have no fundamentals. It means the current
pipeline had no accepted, comparable fundamental snapshots for this universe.

Interpretation:

- Current model BUY/ADD actions cannot be trusted or emitted from the base
  decision model.
- DATA_REVIEW is the correct response when evidence is missing.
- Improving fundamental coverage is a higher-value task than weakening the
  requirement.

### SEC Company Facts design finding

SEC Company Facts can support transparent annual features when facts share the
same fiscal-year end, taxonomy, currency, and filing context.

The implemented quality hypothesis combines available measures such as:

- Net margin.
- Free-cash-flow margin.
- Return on assets.
- Equity-to-assets ratio.
- Annual revenue growth.

Valuation requires both earnings yield and free-cash-flow yield.

Important limitations:

- Financial companies require specialized accounting treatment.
- Foreign issuers and ADRs require point-in-time FX and ADR-ratio handling for
  defensible valuation.
- Missing or stale facts must not be silently treated as good fundamentals.

## Portfolio-Risk Findings

Portfolio risk and price direction must stay separate.

Implemented risk context includes:

- Single-position maximum weights.
- Sector and theme concentration limits.
- Rolling return correlation and correlated-exposure limits.
- Volatility-budget position sizing.
- Broad-market proxy beta.
- Cash-aware gross exposure.
- Leverage alerts.

Key conclusions:

- High concentration can justify a review even when price evidence is bullish.
- Volatility is useful for sizing, not as a direction forecast.
- Historical correlation can fail during crises, so it is a warning rather
  than proof of diversification.
- Leverage should remain visible as an alert metric. It should block buys only
  when the configured policy explicitly says so.
- A risk-driven TRIM_REVIEW is not the same as a bearish price prediction.

## Dashboard And Explanation Findings

Repeated interface iterations produced several durable conclusions:

### Default view

A compact portfolio display board is more useful than a dense research table.
The main page should answer:

- What deserves attention?
- In which direction?
- How strong is the matching historical evidence?
- What is the current position context?

BUY and SELL should appear first, sorted by evidence rate. WAIT should be
folded by default.

### Color and hierarchy

- BUY is green.
- SELL is red.
- WAIT is amber and visually quieter.
- A Robinhood-inspired black/green base makes the board familiar.
- Direction and percentage should be the strongest visual element.

### Detail view

Dense metrics were difficult to interpret. The holding drawer is clearer when
it leads with:

- A directional-rate ring.
- Pooled matching-wave evidence.
- Cross-symbol agreement.
- Separate SPY-relative evidence.
- A 126-session K-line chart.
- Support and resistance zones.
- Volume and active confirmed-pivot wave.

Advanced text and raw tables should remain collapsed by default.

### Important visual distinction

The forecast direction and current wave direction can disagree. For example, a
stock may still be advancing while historical analogs near resistance imply a
SELL review.

Therefore:

- BUY/SELL badge color represents the forecast.
- Active-wave line color represents observed wave direction.
- The interface must never color the current wave as bearish merely because
  the forecast says SELL.

## Validation And Statistical Safety Findings

### What currently works

- Causal feature calculation using only information available at signal time.
- Immutable model versions.
- Append-only alert, decision, K-line, and wave histories.
- Non-overlapping wave replay windows.
- 21/63/126-session evaluation horizons.
- Benchmark-relative and absolute returns kept separate.
- Maximum favorable and adverse excursion measurement.
- Episode de-duplication for repeated signals.
- Wilson confidence intervals.
- Cross-symbol breadth and concentration gates.
- Manifest-last refresh pipeline.

### What remains missing

- Mature live directional forecast outcomes.
- Calibrated probabilities.
- Brier score and calibration curves.
- BUY and SELL precision/recall with adequate samples.
- Broader point-in-time universe validation.
- Leave-one-symbol-out robustness.
- Market-regime stability checks.
- Multiple-testing ledger and false-discovery control.
- Sealed holdout for the wave-direction model.

### Why the dashboard percentage is still not a calibrated probability

The displayed percentage is now a shrunk confidence score based on the fraction
of matching historical observations that moved in the labeled direction. The
raw analog rate is retained as `raw_probability`, but the board shows a value
shrunk toward 50% with a 20-observation neutral prior.

This is deliberately more conservative than showing the raw rate, but it is
still not calibrated against future live outcomes and does not account for
every source of selection bias.

Until calibration work is complete, the honest language is:

> Small-sample shrunk directional confidence

not:

> Probability the stock will rise or fall

## Failed, Inconclusive, And Refused Conclusions

The project explicitly refuses the following claims:

- Exact wave highs and lows can be predicted reliably.
- One attractive backtest proves an edge.
- Strong historical momentum guarantees continued gains.
- A large drawdown automatically means sell.
- A stock beating SPY means its price will rise.
- A high raw win rate from a small cell is strong evidence.
- Repeated daily signals are independent observations.
- Missing fundamentals can be treated as neutral good news.
- Leverage alone predicts direction.
- A visually persuasive K-line pattern is predictive.
- v3 is better than v1 because it emits fewer actionable labels.

These refusals are part of the research output, not limitations to hide.

## Evidence Status Matrix

| Claim | Current status | Reason |
| --- | --- | --- |
| Near-resistance advancing waves tend to fall over 21 sessions | Exploratory support | Passed aggregate and 16-of-16 leave-one-symbol-out gates |
| Mature, developing advancing waves tend to rise over 21 sessions | Rejected as fragile | Only 3 of 14 leave-one-symbol-out runs retained BUY |
| Conditional BUY cell beats SPY | Inconclusive | Relative evidence gate did not pass |
| K-line regimes predict forward returns | Unproven | No mature live outcomes |
| v3 improves investment outcomes over v1 | Unproven | No mature forward comparison |
| v3 reduces unsupported actionability | Supported operationally | More uncertain states become DATA_REVIEW |
| Current base model is selective enough | Refuted operationally | 100% attention rate and 0% HOLD rate |
| Current fundamental pipeline supports live BUY/ADD | Refuted by coverage | 0% accepted live coverage |
| Strict gates make WAIT the dominant output | Supported operationally | v2 maps 26 of 27 current holdings to WAIT |

## Reproducible Public Workflow

Generate synthetic daily prices, run the complete refresh, and execute all
tests:

```bash
python3 examples/generate_demo_prices.py
PYTHONPATH=src python3 -m stock_investor.cli refresh \
  examples/positions.csv examples/prices.csv data/demo \
  --model-version decision-support-v3 --benchmark SPY
PYTHONPATH=src python3 -m unittest discover -s tests
```

Generated `data/` and all real `portfolio/` artifacts are ignored. Teammates
should use synthetic, licensed, or personally authorized data.

## Highest-Value Next Experiments

### Immediate: prediction accountability

1. Accumulate mature versioned direction outcomes without rewriting frozen
   forecast definitions.
2. Report invalid forecasts separately from matured and pending forecasts.
3. Add displayed-rate calibration curves and probability buckets.
4. Measure false-positive BUY and SELL rates.
5. Test whether Brier score and directional success remain stable over time.

### Validation expansion

1. Replay the frozen wave rules on a broader point-in-time universe.
2. Test stability across bull, bear, sideways, and high-volatility periods.
3. Compare wave rules against simpler moving-average baselines.
4. Create a multiple-testing register before adding more conditions.
5. Freeze a wave-v2 candidate and evaluate it on an untouched holdout.

### Data quality and fundamentals

1. Add per-symbol freshness and missing-session diagnostics.
2. Detect splits, symbol changes, stale OHLCV, and suspicious gaps.
3. Improve SEC coverage without mixing periods, currencies, or taxonomies.
4. Add explicit specialized handling for financials and ADRs.

### Product usefulness

1. Record whether the user acted, watched, or dismissed each forecast.
2. Measure whether graphical explanations improve decisions without creating
   false confidence.
3. Produce weekly learning digests focused on changed evidence and matured
   outcomes.

## Rules For Adding A New Finding

Every new research result must state:

1. The hypothesis before outcome review.
2. The exact feature and decision rule.
3. Dataset provenance and point-in-time limitations.
4. Signal horizon and benchmark.
5. Observation count and distinct-symbol count.
6. Largest single-symbol contribution.
7. Uncertainty interval and cross-symbol breadth.
8. Failure cases and contradictory evidence.
9. Whether it replicated on a separate sample.
10. Whether its status is observational, exploratory, candidate, or promoted.

Research that cannot answer these questions remains a hypothesis and cannot
change the promoted model.

## Model-Health V1 Baseline

`model-health-v1` consolidates explicit safety, data, behavior, and validation
gates into one machine-readable artifact. On the June 14, 2026 real-portfolio
refresh, the system is `DEGRADED`, not blocked:

- Five gates pass: read-only safety, complete held-symbol price coverage, price
  freshness, K-line coverage, and structural-wave coverage.
- Three gates fail: alert selectivity, data-review burden, and fundamental
  coverage.
- Two validation gates remain pending because no BUY or SELL forecast horizon
  has matured.

Pending evidence is never treated as a pass. Blocking safety or required-price
failures are kept separate from non-blocking research-quality failures.

## Per-Symbol Price Freshness Baseline

The June 14, 2026 refresh writes `price-health-v1` with declared provenance
`Robinhood MCP read-only export`. All 27 held symbols have a latest observation
dated June 12, 2026 and pass the current seven-calendar-day freshness gate.

Freshness does not imply complete chart data. `SPCX` is fresh but has 0% full
OHLCV coverage in the current file, so downstream K-line conclusions remain
unavailable for it. Expected-market-session gap detection remains a separate
next milestone.

Using the latest 252 observed SPY sessions as the expected market calendar, the
current 27 held symbols have no missing expected sessions. This does not test
for suspicious price gaps or invalid bars; those remain separate diagnostics.

The first OHLCV plausibility audit found no hard-invalid bars, but flagged one
greater-than-50% intraday range for each of `BBBY`, `NVTS`, `OPEN`, and `STEM`.
These observations remain in the dataset pending corporate-action and
cross-provider review; they do not automatically alter forecasts.

The first close-gap audit flagged `FSLY`, `NVTS`, `OPEN`, and `STEM` for one or
more greater-than-40% close-to-close moves. Every current event classified as
an extreme-move candidate; none met the heuristic for a possible corporate
action. The classification is not confirmation and does not rewrite prices.

The current Robinhood CSV's adjustment semantics are not auditable from the
file itself. The live baseline is therefore explicitly recorded as `unknown`,
not assumed to be split- or dividend-adjusted.

No current close-gap event meets the possible-split heuristic. Cost-basis
reconciliation remains warning-only; the system never mutates imported
position quantities or average costs.

The first per-symbol data-quality scorecard rates 26 holdings `GOOD` and one
holding, `SPCX`, `REVIEW`. `SPCX` remains price-fresh but lacks complete OHLCV
history, so it is unsuitable for K-line conclusions.

`wave-direction-v3` blocks directional conclusions for STALE or POOR inputs and
blocks K-line rendering for POOR inputs. `wave-direction-v4` keeps those
blockers and additionally shrinks displayed BUY/SELL confidence toward 50% so
thin-but-robust samples do not look more certain than they are. The current
real portfolio has no POOR symbol, so the refreshed board should preserve the
same directional conclusion count while writing a new versioned ledger for
forward comparison.

## Direction Rate Comparison V1

Hypothesis: a displayed BUY or SELL confidence should not use the raw historical
positive-rate directly, because raw rates are too sensitive to small samples and
single-regime luck. M038 therefore writes `direction-rate-comparison-v1`, which
compares three values for every robust BUY/SELL analog row:

- raw direction probability from the historical positive-rate.
- shrunk displayed probability using the neutral 20-observation prior.
- Wilson-lower probability as the conservative audit floor.

The artifact includes both broad regime rows and conditional age/magnitude rows,
but only after the existing pooled, cross-symbol breadth, concentration, and
leave-one-symbol-out gates classify the row as BUY or SELL. WAIT rows are
excluded to avoid inventing confidence for non-signals.

Decision rule: keep displaying the shrunk rate for readability, keep the Wilson
floor visible in the Research tab, and never promote raw rates directly. This is
a calibration audit artifact, not a new signal version. Failure gate: if future
outcomes show that displayed confidence remains materially above realized
directional success, the next candidate must move closer to the Wilson floor or
add stronger time-period stability gates before promotion.

## Wave Time Decay V1

Hypothesis: older wave analogs may describe a different market regime and should
be audited separately from the equal-weight walk-forward scorecard before any
live signal policy changes. M039 therefore writes `wave-time-decay-v1`, an
experimental broad-regime scorecard that applies exponential decay to historical
wave outcomes using a one-year half-life.

The experiment reports weighted positive rate, weighted mean return, weighted
mean excess return, weighted observation count, symbol count, and the largest
single-symbol weight share for each wave regime and horizon. It uses the same
causal non-overlapping walk-forward outcomes as the equal-weight wave
experiment; only the aggregation changes.

Decision rule: time-decayed rows are research-only and cannot replace the
current equal-weight evidence. Failure gate: do not promote a time-decayed
candidate unless sealed forward outcomes improve calibration and do not increase
single-symbol concentration or false-direction cohorts.

## Wave Direction V4 Candidate Freeze

M040 freezes `wave-direction-v4-candidate` in
`models/wave-direction-v4-candidate.json`. This is not a promoted model and does
not change live decision-support behavior. It is a reviewable candidate manifest
that pins the current v4 direction gate, the shrunk confidence display policy,
the raw-vs-Wilson audit artifact, and the time-decay research audit.

Promotion remains blocked until fixed forward outcomes mature. The required
gates are sealed calibration, BUY/SELL precision, false-direction cohort review,
and time-decay replication. Any Robinhood write action, use of stale or poor
price data for BUY/SELL, or promotion based only on raw in-sample rates
invalidates the candidate.
