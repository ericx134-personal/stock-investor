# K-Line Chart Rewrite Research

Status: M085A, M085B, and M085 implemented on 2026-06-18.

## Why Rewrite

The current K-line chart is a server-rendered SVG. It is useful for static
evidence, but it has repeatedly failed the product bar for interactive charting:

- Range tabs have required custom DOM state management.
- Pan/zoom and visible-scale behavior are fragile.
- Labels, zones, and markers compete for the same fixed SVG space.
- Adding Robinhood-like interactions increases complexity in the wrong layer.

The next version should be a chart runtime, not another SVG patch.

## Product Bar

The detail chart should feel close to Robinhood's chart experience while keeping
our unique overlays:

- Show selectable candle intervals: Daily, Weekly, Monthly, Quarterly, YTD,
  Yearly, 5 years, and All where data exists.
- Use interval-appropriate bars:
  - Daily: all available daily OHLCV candles, with the initial viewport focused
    on recent candles.
  - Weekly, Monthly, Quarterly, and Yearly: aggregate from the full available
    daily history.
  - YTD and 5 years: retain their calendar-window meaning.
- Always draw support and resistance zones as visible horizontal bands.
- Draw average cost, current price, buy/sell zone, active wave, and forecast
  markers without hiding candles.
- Show OHLCV, date, zone, and forecast metadata on hover/crosshair.
- Keep text sparse on the chart. Dense explanation belongs in side panels or
  expandable details.
- Work in the drawer on desktop and mobile without page-level zoom tricks.

## Research Findings

- Robinhood's user-facing docs describe basic charts as line or candlestick
  charts, with candlesticks exposing open, close, low, high, and price direction.
- Robinhood Legend docs emphasize configurable intervals and indicators in chart
  widgets; this matches the user's expectation that range and candle resolution
  are first-class controls.
- TradingView Lightweight Charts is a strong candidate because it is compact,
  open source, canvas-based, and has official candlestick series support.
- Lightweight Charts supports the primitives we need: candlesticks, separate
  series, markers, price lines, crosshair data, time scale control, and
  streaming/historical updates.

Sources:

- Robinhood, "Using charts":
  https://robinhood.com/us/en/support/articles/using-charts/
- Robinhood, "Widgets in Robinhood Legend":
  https://robinhood.com/us/en/support/articles/widgets-in-robinhood-legend/
- Robinhood, "Chart indicators on Legend":
  https://robinhood.com/us/en/support/articles/chart-indicators-on-legend/
- TradingView Lightweight Charts:
  https://www.tradingview.com/lightweight-charts/
- TradingView Lightweight Charts series docs:
  https://tradingview.github.io/lightweight-charts/docs/series-types
- TradingView Lightweight Charts markers tutorial:
  https://tradingview.github.io/lightweight-charts/tutorials/how_to/series-markers

## Architecture Decision

Adopt a client-side chart runtime for detail charts.

Implemented path:

1. Export chart-ready JSON next to the dashboard HTML.
2. Render holdings list server-side as today.
3. Render detail chart containers server-side with a compact JSON reference.
4. Initialize charts client-side when a drawer opens.
5. Use a local vendored chart runtime; no credentialed data provider or CDN is required.

The old hand-written SVG chart is no longer the primary rendering path. The
dashboard writes `chart-payloads-v1.json` beside `dashboard-v3.html`; the HTML
keeps only a small pointer to that sidecar so the page stays responsive.

## Data Contract

Each symbol chart payload should include:

- `symbol`
- `displayName` when known
- `quotes`: current price, previous close, today return, today dollars
- `position`: shares, average cost, market value, cost basis, total return
- `bars`: time, open, high, low, close, volume, source
- `ranges`: selected range, bar interval, start, end, aggregation method
- `zones`: support, resistance, next resistance, price plan
- `markers`: forecast dates, matured outcomes, earnings, pivots, average cost
- `quality`: freshness, OHLCV coverage, fallback reasons

## Validation Gates

M085A completes when:

- The research/spec exists and names a chart runtime path.
- The expected chart data contract is documented.
- Failure modes and fallbacks are documented.

M085B completes when:

- Range tabs visibly change candle count, scale, and dates in browser tests.
- The chart supports hover/crosshair OHLCV.
- Support/resistance zones and average cost render on every eligible holding.
- Forecast and outcome markers render from ledger data when available.
- The old SVG path remains only as a fallback or is removed with tests.
- Full tests and public-safety checks pass.

## Implemented

- `chart-payloads-v1.json` generation from existing price, wave, position, and
  signal data.
- Local `TradingView Lightweight Charts` production bundle under `web/assets`.
- Client-side candlestick and volume rendering in `web/assets/kline-chart.js`.
- Support, resistance, target, average-cost, current-price, and pivot metadata
  in the payload.
- Immutable direction forecast and evaluated outcome markers in the payload,
  de-duplicated by `forecast_id` with outcome records preferred over raw
  forecast records.
- Overlay bands for support/resistance/target zones.
- Range buttons for Daily, Weekly, Monthly, Quarterly, YTD, Yearly, 5 years,
  and All; unavailable long ranges are disabled.
- The chart renders all available history for each interval, then sets an
  initial recent viewport. Dragging is clamped at the first and last available
  candle so users do not scroll into blank space.
- Browser verification on the fixed local URL confirmed drawer chart switching:
  Monthly and Quarterly buttons update active state, aggregation status, and
  canvases with no console errors.
- Live sidecar verification on `http://127.0.0.1:8765/data/private/dashboard-v3.html`
  confirmed 26 symbols with forecast markers. HOOD currently has six forecast
  markers, including 2026-06-12 SELL, 2026-06-16 SELL, and 2026-06-18 WAIT.

## Remaining Follow-Ups

- Add real intraday bars as a separate Daily-detail overlay when the provider
  supports it cleanly.
- Add relative-strength and volume annotations without crowding the chart.
- Complete keyboard and screen-reader chart inspection support.
