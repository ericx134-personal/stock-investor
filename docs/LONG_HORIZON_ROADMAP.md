# Stock Investor Long-Horizon Roadmap

This roadmap is the durable backlog for the read-only stock decision-support
project. Work is ordered by evidence value and dependency, not novelty. No task
may place trades. A research result becomes a promoted signal only after its
predeclared validation standard passes.

The ordered execution sequence and completion gates live in
[`CONTINUOUS_EXECUTION_PLAN.md`](CONTINUOUS_EXECUTION_PLAN.md).

Status legend: `[ ]` pending, `[~]` active, `[x]` complete.

## A. Prediction Accountability

- [x] A001 Persist every displayed BUY/SELL/WAIT directional forecast.
- [x] A002 Evaluate directional forecasts after 21, 63, and 126 sessions.
- [x] A003 Build forecast scorecards by direction and horizon.
- [ ] A004 Track forecast calibration by displayed probability bucket.
- [ ] A005 Track coverage: share of holdings receiving BUY/SELL versus WAIT.
- [ ] A006 Track false-positive BUY and SELL rates.
- [x] A007 Track maximum favorable and adverse excursion per forecast.
- [x] A008 Separate absolute-direction success from SPY-relative success.
- [x] A009 Add forecast episode de-duplication to avoid repeated-signal inflation.
- [~] A010 Display matured, pending, and invalid forecast counts.

## B. Data Integrity

- [x] B001 Add per-symbol latest-price freshness status.
- [x] B002 Detect missing sessions and suspicious price gaps.
- [x] B003 Detect stale or implausible OHLCV fields.
- [x] B004 Track adjusted versus unadjusted price provenance.
- [x] B005 Detect splits and reconcile position cost bases.
- [ ] B006 Detect symbol changes and delistings.
- [~] B007 Preserve provider and retrieval timestamps per data batch.
- [x] B008 Add deterministic price-file content hashes.
- [x] B009 Add data-quality scorecards by symbol.
- [x] B010 Block graphical conclusions when required chart data is invalid.

## C. Real-Portfolio Learning Loop

- [ ] C001 Refresh the sanitized Robinhood portfolio on a production schedule.
- [ ] C002 Refresh daily bars after the official market close.
- [ ] C003 Record portfolio additions, removals, and quantity changes.
- [ ] C004 Distinguish user trades from market-driven position-weight changes.
- [ ] C005 Join user feedback to directional forecasts.
- [ ] C006 Record whether the user acted, watched, or ignored a forecast.
- [ ] C007 Compare acted-on and ignored forecast outcomes without causal claims.
- [ ] C008 Track current holdings against their first observed forecast.
- [ ] C009 Produce a weekly portfolio-learning digest.
- [ ] C010 Produce a monthly model-health review.

## D. Wave Model Research

- [ ] D001 Audit sensitivity to the minimum reversal threshold.
- [ ] D002 Compare ATR-scaled and fixed-percent reversal thresholds.
- [ ] D003 Test early, mature, and extended wave-age buckets out of sample.
- [ ] D004 Test developing, established, and extended move-size buckets.
- [ ] D005 Test support-zone proximity as a predeclared condition.
- [ ] D006 Test resistance-zone proximity as a predeclared condition.
- [ ] D007 Test active-wave slope and acceleration.
- [ ] D008 Test wave symmetry between advances and declines.
- [ ] D009 Compare confirmed-pivot waves with simpler moving-average regimes.
- [ ] D010 Freeze and evaluate a wave-v2 candidate on a sealed holdout.

## E. K-Line And Chart Research

- [ ] E001 Add moving-average overlays to the daily K-line chart.
- [ ] E002 Add selectable 6-month, 1-year, and 2-year chart horizons.
- [ ] E003 Add chart tooltips for OHLCV and signal dates.
- [ ] E004 Mark historical forecast dates directly on K-line charts.
- [ ] E005 Mark matured forecast outcomes directly on K-line charts.
- [ ] E006 Add volume-spike and dry-up annotations.
- [ ] E007 Add gap-up and gap-down annotations.
- [ ] E008 Add breakout and failed-breakout annotations.
- [ ] E009 Add relative-strength-versus-SPY chart overlay.
- [ ] E010 Test whether chart annotations improve user decision usefulness.

## F. Benchmark And Regime Research

- [ ] F001 Add broad-market SPY regime classification.
- [ ] F002 Add growth-stock QQQ regime classification.
- [ ] F003 Add small-cap IWM regime classification.
- [ ] F004 Measure signals separately in bull, bear, and sideways markets.
- [ ] F005 Measure signals separately in high- and low-volatility markets.
- [ ] F006 Measure signals separately above and below market trend.
- [ ] F007 Add sector ETF benchmarks where mappings are available.
- [ ] F008 Compare absolute returns with sector-relative returns.
- [ ] F009 Test whether market-regime conditioning improves robust evidence.
- [ ] F010 Refuse regime conditioning when sample gates fail.

## G. Fundamental Evidence

- [ ] G001 Increase SEC company-facts coverage for US issuers.
- [ ] G002 Add explicit ADR and foreign-issuer coverage status.
- [ ] G003 Add revenue-growth trend evidence.
- [ ] G004 Add profitability and margin trend evidence.
- [ ] G005 Add free-cash-flow trend evidence.
- [ ] G006 Add balance-sheet safety evidence.
- [ ] G007 Add dilution and share-count trend evidence.
- [ ] G008 Add valuation-history percentiles.
- [ ] G009 Add filing-recency and stale-fundamental warnings.
- [ ] G010 Test whether fundamentals improve BUY/SELL precision out of sample.

## H. Events And Thesis Monitoring

- [ ] H001 Add forward earnings-calendar alerts.
- [ ] H002 Mark earnings dates on K-line charts.
- [ ] H003 Add post-earnings gap and drift tracking.
- [ ] H004 Add material 8-K event summaries to holding details.
- [ ] H005 Add thesis-review reminders.
- [ ] H006 Add explicit thesis invalidation dashboard status.
- [ ] H007 Track outcomes after thesis-break alerts.
- [ ] H008 Add earnings-risk suppression as an experiment, not a default.
- [ ] H009 Add corporate-action alerts.
- [ ] H010 Add event-risk coverage diagnostics.

## I. Portfolio Construction Research

- [ ] I001 Add marginal portfolio-risk contribution by holding.
- [ ] I002 Add rolling correlation clusters.
- [ ] I003 Add sector and theme concentration graphics.
- [ ] I004 Add volatility-budget graphics.
- [ ] I005 Add drawdown contribution graphics.
- [ ] I006 Add gross and net exposure history.
- [ ] I007 Add configurable rebalance-review bands.
- [ ] I008 Simulate risk-aware position-sizing suggestions.
- [ ] I009 Compare equal-weight, volatility-weight, and current-weight outcomes.
- [ ] I010 Keep leverage as an alert metric unless policy explicitly blocks it.

## J. Validation And Statistical Safety

- [ ] J001 Add probability calibration curves.
- [x] J002 Add Brier score for directional forecasts.
- [ ] J003 Add precision, recall, and coverage for BUY and SELL separately.
- [ ] J004 Add bootstrap uncertainty for return statistics.
- [ ] J005 Add multiple-testing ledger for every research experiment.
- [ ] J006 Add false-discovery warnings after repeated experiments.
- [ ] J007 Add walk-forward train/development/test partitions.
- [x] J008 Add symbol-level leave-one-out robustness checks.
- [ ] J009 Add time-period stability checks.
- [ ] J010 Define formal promotion and retirement gates for models.

## K. Dashboard And Explanation

- [ ] K001 Add forecast validation graphics to holding details.
- [ ] K002 Add compact portfolio-level opportunity summary.
- [ ] K003 Add probability sorting controls.
- [ ] K004 Add filters for BUY, SELL, WAIT, sector, and weight.
- [ ] K005 Add search by ticker.
- [ ] K006 Add accessible chart labels and keyboard navigation.
- [ ] K007 Add mobile chart inspection controls.
- [ ] K008 Add downloadable sanitized research report.
- [ ] K009 Add dashboard artifact-size monitoring.
- [ ] K010 Add concise plain-language explanation quality tests.

## L. Operations And Read-Only Automation

- [x] L001 Add a production-safe daily refresh command.
- [ ] L002 Add refresh locking to prevent overlapping runs.
- [ ] L003 Add retry and failure reporting for read-only providers.
- [ ] L004 Add manifest history and run-duration tracking.
- [ ] L005 Add alerting for stale refreshes.
- [ ] L006 Add scheduled weekly and monthly briefs.
- [ ] L007 Add artifact retention and archival policy.
- [ ] L008 Add sanitized backup and recovery verification.
- [ ] L009 Add dependency and security update checks.
- [ ] L010 Add an explicit permanent no-trade integration test.

## M. Research Expansion

- [ ] M001 Add watchlist candidates without mixing them with held positions.
- [ ] M002 Add liquidity and tradability diagnostics.
- [ ] M003 Add tax-lot-aware review context without making tax advice.
- [ ] M004 Add realized-return import for outcome context.
- [ ] M005 Add dividend and distribution context.
- [ ] M006 Add options-position visibility as risk context only.
- [ ] M007 Add macro-calendar context as an exploratory layer.
- [ ] M008 Add news-source provenance and deduplication.
- [ ] M009 Add model-change decision records with rationale.
- [ ] M010 Publish a quarterly evidence and model-governance report.

## Execution Rule

At each continuation, first choose the highest-value unblocked milestone from
`CONTINUOUS_EXECUTION_PLAN.md`, then use this roadmap for its detailed
research backlog. Finish it end to end: implementation, tests, real-data
refresh, artifact inspection, and documentation. Keep all trading actions
disabled.
