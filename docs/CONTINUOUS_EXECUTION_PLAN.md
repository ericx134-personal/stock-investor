# Stock Investor Continuous Execution Plan

This is the ordered execution plan for continuously improving the read-only
stock decision-support system. The broader `LONG_HORIZON_ROADMAP.md` remains
the research backlog; this document defines the current sequence of verifiable
milestones.

Success means better calibrated and more stable decisions on matured forward
outcomes, not more BUY or SELL labels. No milestone may place trades.

Status legend: `[ ]` pending, `[~]` active, `[x]` complete.

## Operating Rules

- Never stop merely because a milestone, commit, push, report, or user-facing
  reply is complete. In every available work window, immediately continue to
  the next highest-value unblocked milestone until an external limit,
  irrecoverable blocker, or explicit user stop instruction is reached.
- A status update is not a stopping point. After reporting progress, resume
  implementation in the same turn whenever tool access and budget remain.
- Complete milestones in dependency order, choosing the highest-value unblocked
  item at each continuation.
- Treat milestone count as an implementation aid, not a target. Add, merge,
  split, reorder, or retire milestones when evidence and dependencies justify
  it; never create filler merely to preserve a number.
- Keep this as the single canonical execution list. Before adding work, search
  for overlap and consolidate duplicate or confusing tasks.
- Predeclare the hypothesis, metric, sample gate, and failure condition before
  inspecting experimental outcomes.
- Preserve every forecast and model version. Never rewrite failed predictions.
- Require focused tests, the full test suite, a real-data refresh, artifact
  inspection, documentation, and a reversible commit for completion.
- Promote a model only when it improves sealed forward evidence without
  materially worsening calibration, drawdown, coverage, or stability.

## Phase 1: Measurement Foundation

- [x] M001 Persist immutable BUY, SELL, and WAIT forecasts.
- [x] M002 Evaluate forecasts at 21, 63, and 126 sessions.
- [x] M003 De-duplicate repeated daily forecasts into episodes.
- [x] M004 Separate absolute-direction and benchmark-relative outcomes.
- [x] M005 Measure maximum favorable and adverse excursion.
- [x] M006 Add Brier score for directional forecasts.
- [x] M007 Require cross-symbol breadth and concentration gates.
- [x] M008 Require leave-one-symbol-out directional stability.
- [x] M009 Display structural BUY/SELL review zones on K-line charts.
- [x] M010 Add one machine-readable model-health summary with explicit pass/fail gates.

## Phase 2: Data Reliability

- [x] M011 Add per-symbol price freshness and source provenance.
- [x] M012 Detect missing expected market sessions.
- [x] M013 Detect invalid and implausible OHLCV values.
- [x] M014 Detect suspicious one-session gaps and classify likely corporate actions.
- [x] M015 Track adjusted/unadjusted price semantics per provider.
- [x] M016 Detect splits and preserve cost-basis reconciliation warnings.
- [ ] M017 Detect symbol changes, mergers, and delistings.
- [x] M018 Add deterministic hashes for every input data batch.
- [x] M019 Build a per-symbol data-quality scorecard.
- [x] M020 Block forecasts and charts when required inputs fail quality gates.

## Phase 3: Operational Stability

- [x] M021 Add a production-safe read-only daily refresh command.
- [x] M022 Add refresh locking to prevent overlapping runs.
- [ ] M023 Add bounded retries and provider failure classification.
- [x] M024 Persist refresh-run history, duration, and artifact sizes.
- [x] M025 Alert when a scheduled refresh is stale or incomplete.
- [x] M025A Keep the private Mac dashboard online and schedule market refreshes.
- [x] M026 Add atomic writes for every current-state artifact.
- [x] M027 Add retention and archival policy for private generated artifacts.
- [x] M028 Verify sanitized backup and restore.
- [x] M029 Add dependency and security checks.
- [x] M030 Add a permanent integration test proving no trade/write action exists.

## Phase 4: Calibration And Error Analysis

- [x] M031 Add forecast calibration buckets by displayed historical rate.
- [x] M032 Add calibration curves by BUY and SELL direction.
- [x] M033 Add precision, recall, false-positive rate, and coverage by direction.
- [x] M034 Add confidence intervals for all directional success metrics.
- [x] M035 Add bootstrap uncertainty for return and excursion metrics.
- [x] M036 Add error cohorts for the largest false BUY and false SELL episodes.
- [x] M037 Add probability shrinkage for small samples.
- [x] M038 Compare raw, Wilson-lower-bound, and shrunk displayed rates.
- [x] M039 Add time-decayed evidence as a versioned experiment.
- [ ] M040 Freeze the first calibrated direction model candidate.

## Phase 5: Statistical Safety

- [ ] M041 Create a multiple-testing ledger for every experiment.
- [ ] M042 Add false-discovery warnings after repeated hypothesis tests.
- [ ] M043 Create fixed train, development, and sealed test periods.
- [ ] M044 Add expanding-window walk-forward validation.
- [ ] M045 Add time-period stability checks.
- [ ] M046 Add bull, bear, sideways, and high-volatility stability checks.
- [ ] M047 Add sector-level stability checks.
- [ ] M048 Add sensitivity analysis around every promoted threshold.
- [ ] M049 Define formal model promotion, probation, retirement, and rollback gates.
- [ ] M050 Publish the first reproducible model-governance report.

## Phase 6: Wave And Price-Zone Research

- [ ] M051 Audit sensitivity to reversal thresholds.
- [ ] M052 Compare ATR-scaled and fixed-percent wave definitions.
- [ ] M053 Compare confirmed-pivot waves with moving-average baselines.
- [ ] M054 Test wave age buckets on sealed data.
- [ ] M055 Test normalized wave magnitude buckets on sealed data.
- [ ] M056 Test support-zone proximity as a predeclared condition.
- [ ] M057 Test resistance-zone proximity as a predeclared condition.
- [ ] M058 Evaluate target-zone touch rate, time-to-touch, and post-touch outcome.
- [ ] M059 Evaluate midpoint versus full-zone usefulness without claiming exact fills.
- [ ] M060 Freeze or reject wave-v2 and price-zone-v2 using promotion gates.
- [x] M060A Add rolling historical price-zone replay: pretend each past session is today,
  emit the buy/sell/retest zone, reveal the next bars, and score touch, miss,
  breakout invalidation, retest behavior, and opportunity cost.

## Phase 7: Market, Fundamental, And Event Context

- [ ] M061 Add point-in-time SPY, QQQ, and IWM market regimes.
- [ ] M062 Add sector ETF mappings and sector-relative outcomes.
- [ ] M063 Test whether market conditioning improves sealed precision.
- [ ] M064 Increase SEC company-facts coverage for US issuers.
- [ ] M065 Add ADR and foreign-issuer coverage diagnostics.
- [ ] M066 Add revenue, margin, cash-flow, balance-sheet, and dilution trends.
- [ ] M067 Add filing-recency and stale-fundamental warnings.
- [ ] M068 Add forward earnings-calendar context and chart markers.
- [ ] M069 Track post-earnings gap and drift outcomes.
- [ ] M070 Promote or reject each context feature independently.

## Phase 8: Portfolio Decision Quality

- [ ] M071 Add marginal risk contribution by holding.
- [ ] M072 Add rolling correlation and exposure clusters.
- [ ] M073 Add sector, theme, volatility, and drawdown contribution graphics.
- [ ] M074 Add gross/net exposure history while keeping leverage informational.
- [ ] M075 Add configurable rebalance-review bands.
- [ ] M076 Simulate risk-aware sizing suggestions as read-only research.
- [ ] M077 Compare current, equal-weight, and volatility-weight outcomes.
- [ ] M078 Add first-observed-forecast tracking for every holding.
- [ ] M079 Compare acted-on, watched, and ignored forecasts without causal claims.
- [ ] M080 Publish a monthly portfolio-learning review.

## Phase 9: Dashboard And User Comprehension

- [ ] M081 Add compact model-health and opportunity summaries.
- [ ] M082 Add BUY/SELL/WAIT, sector, weight, and confidence filters.
- [ ] M083 Add ticker search and probability sorting.
- [ ] M084 Add chart crosshair and OHLCV tooltips.
- [ ] M085 Mark historical forecasts and matured outcomes on K-line charts.
- [ ] M086 Add selectable 6-month, 1-year, and 2-year horizons.
- [ ] M087 Add relative-strength and volume annotations.
- [ ] M088 Complete keyboard, screen-reader, and mobile chart support.
- [ ] M089 Add concise-language and explanation usefulness tests.
- [ ] M090 Add downloadable sanitized evidence reports.

## Phase 10: Broader Validation And Continuous Improvement

- [ ] M091 Build a broader point-in-time validation universe.
- [ ] M092 Add liquidity and tradability diagnostics.
- [ ] M093 Separate watchlist candidates from held-position forecasts.
- [ ] M094 Add realized-return and dividend context.
- [ ] M095 Add options exposure as risk context only.
- [ ] M096 Add weekly learning digest and quarterly governance report.
- [ ] M097 Run shadow comparison of champion and challenger models.
- [ ] M098 Automatically flag degradation without auto-promoting a challenger.
- [ ] M099 Complete a disaster-recovery and reproducibility audit.
- [ ] M100 Demonstrate sustained calibrated improvement on matured sealed outcomes.

## Long-Term Completion Gate

The long-term objective is complete only after a challenger beats the frozen champion on a sealed
forward period with adequate BUY and SELL samples, while passing calibration,
drawdown, cross-symbol, cross-period, data-quality, and operational-reliability
gates. Until then, continuous improvement remains active.
