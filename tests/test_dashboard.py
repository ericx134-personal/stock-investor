import tempfile
import unittest
import json
from datetime import date, timedelta
from pathlib import Path

from stock_investor.dashboard import (
    _chart_ranges,
    _kline_chart,
    _kline_chart_payload,
    _mini_sparkline,
    _next_resistance_zone,
    _price_plan,
    _professional_plan,
    _sparkline_points,
    build_dashboard,
    write_dashboard,
)
from stock_investor.data import Price


class DashboardTests(unittest.TestCase):
    def test_kline_chart_emits_interactive_payload_and_true_ranges(self):
        history = [
            Price(
                date=date(2026, 1, 1) + timedelta(days=index),
                open=100 + index,
                high=102 + index,
                low=99 + index,
                close=101 + index,
                volume=1_000_000 + index,
            )
            for index in range(25)
        ]
        page = _kline_chart(
            history,
            {
                "support_zone_low": 95,
                "support_zone_high": 98,
                "resistance_zone_low": 125,
                "resistance_zone_high": 128,
                "latest_close": 125,
            },
            "SELL",
            "sell",
            0.72,
            {"low": 125, "high": 128, "midpoint": 126.5, "plan_class": "sell", "label": "Sell zone"},
            average_cost=90,
        )
        self.assertIn('class="interactive-kline"', page)
        self.assertIn('class="kline-local-payload"', page)
        self.assertIn('class="chart-tooltip"', page)
        self.assertIn('"label":"Pressure"', page)
        self.assertIn('"label":"Sell zone"', page)
        self.assertIn('"open":124.0', page)
        self.assertIn('"close":125.0', page)
        self.assertNotIn("pinch/scroll", page)
        self.assertIn('data-active-chart-range="1D"', page)
        self.assertIn('data-chart-range="1D"', page)
        self.assertIn('data-chart-range="MAX"', page)
        self.assertIn(">Daily</button>", page)
        self.assertIn(">Weekly</button>", page)
        self.assertIn(">Monthly</button>", page)
        self.assertIn(">Quarterly</button>", page)
        self.assertNotIn('class="kline-chart"', page)
        self.assertNotIn('class="candle-hitbox"', page)
        self.assertIn('class="chart-range-tabs"', page)
        self.assertIn('class="chart-mode-tabs"', page)
        self.assertIn('data-chart-mode="line" class="active">Line</button>', page)
        self.assertIn('data-chart-mode="candles">Candle</button>', page)
        self.assertIn('data-chart-range="1D" data-chart-bars="25" class="active">Daily</button>', page)

    def test_kline_payload_preserves_far_cost_basis_as_line_metadata(self):
        history = [
            Price(
                date=date(2026, 1, 1) + timedelta(days=index),
                open=100 + index * 0.2,
                high=102 + index * 0.2,
                low=99 + index * 0.2,
                close=101 + index * 0.2,
                volume=1_000_000,
            )
            for index in range(35)
        ]
        page = _kline_chart(
            history,
            {
                "support_zone_low": 98,
                "support_zone_high": 100,
                "resistance_zone_low": 107,
                "resistance_zone_high": 110,
                "latest_close": 108,
            },
            "SELL",
            "sell",
            0.64,
            {"low": 107, "high": 110, "midpoint": 108.5, "plan_class": "sell", "label": "Sell zone"},
            average_cost=19.77,
        )
        self.assertIn('"id":"average_cost"', page)
        self.assertIn('"price":19.77', page)
        self.assertNotIn('class="average-cost-line"', page)

    def test_chart_ranges_use_ytd_and_aggregate_dense_history(self):
        history = [
            Price(
                date=date(2024, 1, 1) + timedelta(days=index),
                open=100 + index * 0.01,
                high=101 + index * 0.01,
                low=99 + index * 0.01,
                close=100.5 + index * 0.01,
                volume=1_000 + index,
            )
            for index in range(760)
        ]
        ranges = _chart_ranges(history)

        self.assertEqual(ranges["1D"]["label"], "Daily")
        self.assertEqual(ranges["1D"]["raw_bar_count"], 760)
        self.assertEqual(ranges["1W"]["label"], "Weekly")
        self.assertEqual(ranges["1W"]["raw_bar_count"], 760)
        self.assertEqual(ranges["1W"]["aggregation"], "weekly")
        self.assertEqual(ranges["1M"]["aggregation"], "monthly")
        self.assertEqual(ranges["3M"]["aggregation"], "quarterly")
        self.assertEqual(ranges["1Y"]["aggregation"], "yearly")
        self.assertEqual(ranges["1M"]["raw_bar_count"], 760)
        self.assertGreater(ranges["1M"]["bar_count"], 1)
        self.assertEqual(ranges["YTD"]["start"], "2026-01-01")
        self.assertEqual(ranges["MAX"]["aggregation"], "none")
        self.assertEqual(ranges["MAX"]["bar_count"], ranges["MAX"]["raw_bar_count"])

    def test_kline_runtime_keeps_drag_inside_available_history(self):
        runtime = Path("web/assets/kline-chart.js").read_text()

        self.assertIn("fixLeftEdge: false", runtime)
        self.assertIn("fixRightEdge: false", runtime)
        self.assertIn("rightBarStaysOnScroll: false", runtime)
        self.assertIn("pressedMouseMove: false", runtime)
        self.assertIn("function installManualPan", runtime)
        self.assertIn("rightOffset: 0", runtime)
        self.assertIn("function clampVisibleLogicalRange", runtime)
        self.assertIn("function boundedLogicalRange", runtime)
        self.assertIn("const first = 0", runtime)
        self.assertIn("function initialLogicalRange", runtime)
        self.assertIn("function installVerticalZoom", runtime)
        self.assertIn('{ passive: false }', runtime)
        self.assertIn("edgeTolerance", runtime)
        self.assertIn("function inspectCard", runtime)
        self.assertIn("recordChartDebugState", runtime)
        self.assertIn("chartHasWhitespace", runtime)
        self.assertIn("hasWhitespace", runtime)
        self.assertIn("readableVisibleBars", runtime)
        self.assertIn("visibleBarCapacity", runtime)
        self.assertNotIn("range.initial_bar_count", runtime)

    def test_chart_payload_schema_and_dashboard_sidecar_are_written(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            history = [
                Price(
                    date=date(2026, 1, 1) + timedelta(days=index),
                    open=100 + index,
                    high=102 + index,
                    low=99 + index,
                    close=101 + index,
                    volume=10_000 + index,
                )
                for index in range(30)
            ]
            payload = _kline_chart_payload(
                history,
                {"support_zone_low": 98, "support_zone_high": 101},
                "BUY",
                "buy",
                0.66,
                {"low": 98, "high": 101, "midpoint": 99.5, "plan_class": "buy", "label": "Buy zone"},
                95,
                "ABC",
                130,
                0.02,
            )
            html = (
                '<html><script type="application/json" id="chart-payloads-v1">'
                + json.dumps({"version": 1, "symbols": {"ABC": payload}}, sort_keys=True)
                + "</script></html>"
            )
            output = root / "dashboard-v3.html"
            write_dashboard(html, output)

            sidecar = json.loads((root / "chart-payloads-v1.json").read_text())
            dashboard_html = output.read_text()
        self.assertEqual(sidecar["symbols"]["ABC"]["symbol"], "ABC")
        self.assertIn("bars_daily", sidecar["symbols"]["ABC"])
        self.assertIn("ranges", sidecar["symbols"]["ABC"])
        self.assertEqual(sidecar["symbols"]["ABC"]["ranges"]["1D"]["label"], "Daily")
        self.assertIsNone(sidecar["symbols"]["ABC"]["ranges"]["1D"]["fallback_reason"])
        self.assertIn('data-src="chart-payloads-v1.json"', dashboard_html)
        self.assertNotIn("bars_daily", dashboard_html)

    def test_direction_forecast_outcomes_become_kline_markers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            alerts = root / "alerts.jsonl"
            alerts.write_text(
                json.dumps(
                    {
                        "symbol": "ABC",
                        "shares": 10,
                        "average_cost": 90,
                        "latest_close": 120,
                        "portfolio_weight": 0.2,
                        "alert": {"action": "HOLD", "score": 0, "reasons": []},
                        "technicals": {"ohlcv_available": True},
                    }
                )
                + "\n"
            )
            start = date(2026, 1, 1)
            prices = root / "prices.csv"
            prices.write_text(
                "date,symbol,close,open,high,low,volume\n"
                + "".join(
                    f"{(start + timedelta(days=index)).isoformat()},ABC,{100 + index:.2f},"
                    f"{99 + index:.2f},{102 + index:.2f},{98 + index:.2f},100000\n"
                    for index in range(70)
                )
            )
            forecasts = root / "wave-direction-forecasts.jsonl"
            forecasts.write_text(
                json.dumps(
                    {
                        "forecast_id": "abc-buy-1",
                        "forecast_version": "wave-direction-v1",
                        "symbol": "ABC",
                        "signal_date": "2026-01-20",
                        "entry_close": 119,
                        "direction": "BUY",
                        "probability": 0.72,
                        "horizon": "21d",
                    }
                )
                + "\n"
            )
            outcomes = root / "wave-direction-forecast-outcomes.json"
            outcomes.write_text(
                json.dumps(
                    [
                        {
                            "forecast_id": "abc-buy-1",
                            "forecast_version": "wave-direction-v1",
                            "symbol": "ABC",
                            "signal_date": "2026-01-20",
                            "entry_close": 119,
                            "direction": "BUY",
                            "probability": 0.72,
                            "horizon": "21d",
                            "status": "MATURED",
                            "returns": {"21d": 0.1},
                            "directional_returns": {"21d": 0.1},
                            "excess_returns": {"21d": 0.04},
                            "max_favorable_excursion": 0.14,
                            "max_adverse_excursion": -0.03,
                        }
                    ]
                )
            )
            output = root / "dashboard-v3.html"
            write_dashboard(
                build_dashboard(
                    alerts,
                    prices_path=prices,
                    direction_forecasts_path=forecasts,
                    direction_forecast_outcomes_path=outcomes,
                ),
                output,
            )

            payload = json.loads((root / "chart-payloads-v1.json").read_text())
        markers = payload["symbols"]["ABC"]["markers"]
        forecast_marker = next(marker for marker in markers if marker["type"] == "forecast")
        self.assertEqual(forecast_marker["forecast_id"], "abc-buy-1")
        self.assertEqual(forecast_marker["label"], "BUY HIT")
        self.assertEqual(forecast_marker["status"], "MATURED")
        self.assertEqual(forecast_marker["outcome"], "hit")
        self.assertAlmostEqual(forecast_marker["directional_return"], 0.1)
        self.assertAlmostEqual(forecast_marker["max_adverse_excursion"], -0.03)

    def test_price_plan_uses_structural_zone_and_refuses_wait(self):
        wave = {
            "support_zone_low": 90,
            "support_zone_high": 94,
            "resistance_zone_low": 108,
            "resistance_zone_high": 112,
        }
        buy = _price_plan("BUY", wave, 100)
        sell = _price_plan("SELL", wave, 100)
        self.assertEqual((buy["low"], buy["high"], buy["midpoint"]), (90, 94, 92))
        self.assertEqual((sell["low"], sell["high"], sell["midpoint"]), (108, 112, 110))
        self.assertIn("below the current price", buy["proximity"])
        self.assertIn("above the current price", sell["proximity"])
        breakout = _price_plan("SELL", wave, 118)
        self.assertEqual(breakout["label"], "Breakout retest zone")
        self.assertEqual(breakout["plan_class"], "breakout")
        self.assertIn("invalidated", breakout["interpretation"])
        self.assertIn("below the current price", breakout["proximity"])
        self.assertIsNone(_price_plan("WAIT", wave, 100))

    def test_price_plan_prefers_upper_pressure_after_breakout(self):
        wave = {
            "resistance_zone_low": 108,
            "resistance_zone_high": 112,
            "next_resistance_zone_low": 124,
            "next_resistance_zone_high": 130,
            "next_resistance_source": "nearest historical overhead cluster",
        }
        sell = _price_plan("SELL", wave, 118)
        self.assertEqual(sell["label"], "Upper sell zone")
        self.assertEqual((sell["low"], sell["high"]), (124, 130))
        self.assertIn("above the current price", sell["proximity"])

    def test_next_resistance_zone_uses_history_above_current_price(self):
        history = [
            Price(date(2026, 1, 1) + timedelta(days=index), 100 + index, high=100 + index)
            for index in range(35)
        ]
        zone = _next_resistance_zone(history, 120, 118)
        self.assertGreater(zone["next_resistance_zone_low"], 120)
        self.assertIn("historical overhead", zone["next_resistance_source"])

    def test_professional_plan_distinguishes_sell_management_modes(self):
        wave = {
            "latest_close": 118,
            "support_zone_low": 100,
            "support_zone_high": 104,
            "resistance_zone_low": 108,
            "resistance_zone_high": 112,
        }
        breakout_zone = _price_plan("SELL", wave, 118)
        breakout = _professional_plan(
            "SELL",
            {"shares": 10, "unrealized_return": 0.4, "alert": {"action": "HOLD"}},
            wave,
            breakout_zone,
        )
        self.assertEqual(breakout["label"], "BREAKOUT RETEST")
        self.assertEqual(breakout["class"], "breakout")
        self.assertIn("trailing-profit", breakout["management"])

        trail = _professional_plan(
            "SELL",
            {"shares": 10, "unrealized_return": 0.4, "alert": {"action": "HOLD"}},
            {**wave, "latest_close": 110},
            {"plan_class": "sell"},
        )
        self.assertEqual(trail["label"], "TRAIL PROFIT")
        self.assertEqual(trail["stage"], "Winner management")

        trim = _professional_plan(
            "SELL",
            {"shares": 10, "unrealized_return": 0.05, "alert": {"action": "TRIM_REVIEW"}},
            wave,
            {"plan_class": "sell"},
        )
        self.assertEqual(trim["label"], "TRIM REVIEW")

        exit_review = _professional_plan(
            "SELL",
            {
                "shares": 10,
                "unrealized_return": -0.2,
                "alert": {"action": "REVIEW", "reasons": ["Thesis broken"]},
            },
            wave,
            {"plan_class": "sell"},
        )
        self.assertEqual(exit_review["label"], "EXIT REVIEW")

    def test_dashboard_prioritizes_and_escapes_alerts(self):
        with tempfile.TemporaryDirectory() as directory:
            alerts = Path(directory) / "alerts.jsonl"
            alerts.write_text(
                '{"symbol":"ABC","portfolio_weight":0.2,"latest_close":10,'
                '"observed_at":"2026-01-01","alert":{"action":"TRIM_REVIEW",'
                '"score":-0.4,"reasons":["Drawdown < review"]},'
                '"technicals":{"drawdown_from_high":-0.3,"return_12_to_1":0.1}}\n'
            )
            scorecard = Path(directory) / "scorecard.json"
            scorecard.write_text(
                '[{"action":"TRIM_REVIEW","horizon":"21d","observations":4,'
                '"directional_success_rate":0.75,"mean_directional_return":0.1}]'
            )
            decision_scorecard = Path(directory) / "decision-scorecard.json"
            decision_scorecard.write_text(
                '[{"model_version":"test-v1","action":"HOLD","horizon":"21d",'
                '"observations":3,"positive_rate":0.67,"mean_excess_return":0.04,'
                '"directional_success_rate":0.67}]'
            )
            direction_scorecard = Path(directory) / "direction-scorecard.json"
            direction_scorecard.write_text(
                '[{"forecast_version":"wave-direction-v1","direction":"BUY",'
                '"horizon":"21d","forecast_episodes":3,'
                '"observations":1,"pending":2,"mean_probability":0.8,'
                '"directional_success_rate":1.0,"brier_score":0.04}]'
            )
            first_observed = Path(directory) / "first-observed-forecasts.json"
            first_observed.write_text(
                json.dumps(
                    {
                        "schema_version": "first-observed-forecasts-v1",
                        "tracked_count": 1,
                        "missing_count": 0,
                        "changed_since_first_count": 1,
                        "holdings": [
                            {
                                "symbol": "ABC",
                                "status": "TRACKED",
                                "changed_since_first": True,
                                "first_forecast": {
                                    "forecast_version": "wave-direction-v1",
                                    "direction": "SELL",
                                    "probability": 0.64,
                                    "signal_date": "2026-01-01",
                                    "entry_close": 10,
                                },
                                "current_forecast": {"direction": "WAIT"},
                                "first_outcome": {"status": "PENDING"},
                            }
                        ],
                    }
                )
            )
            forecast_action_segments = Path(directory) / "forecast-action-segments.json"
            forecast_action_segments.write_text(
                json.dumps(
                    {
                        "schema_version": "forecast-action-segments-v1",
                        "methodology_note": "Segments are current-state observational proxies only.",
                        "episode_segment_counts": {
                            "ACTED_ON_PROXY": 2,
                            "WATCHED_PROXY": 1,
                        },
                        "scorecard": [
                            {
                                "segment": "ACTED_ON_PROXY",
                                "segment_label": "Acted-on proxy",
                                "direction": "SELL",
                                "horizon": "21d",
                                "forecast_episodes": 2,
                                "matured_observations": 1,
                                "pending": 1,
                                "directional_success_rate": 1.0,
                                "mean_directional_return": 0.12,
                                "mean_excess_return": 0.05,
                                "symbols": ["ABC"],
                            }
                        ],
                    }
                )
            )
            learning_review = Path(directory) / "portfolio-learning-review.md"
            learning_review.write_text("# Monthly Portfolio Learning Review\n")
            model_health = Path(directory) / "model-health.json"
            model_health.write_text(
                json.dumps(
                    {
                        "overall_status": "PENDING",
                        "failed_gates": [],
                        "pending_gates": ["matured_directional_evidence"],
                        "blocking_failures": [],
                        "gates": [
                            {
                                "id": "read_only",
                                "status": "PASS",
                                "actual": True,
                                "threshold": True,
                                "detail": "No brokerage writes.",
                            }
                        ],
                    }
                )
            )
            price_health = Path(directory) / "price-health.json"
            price_health.write_text(
                json.dumps(
                    {
                        "symbols": [
                            {
                                "symbol": "ABC",
                                "status": "FRESH",
                                "latest_date": "2026-01-01",
                                "age_calendar_days": 1,
                                "ohlcv_coverage_rate": 0.9,
                                "source": "Test provider",
                                "source_confidence": "DECLARED",
                            }
                        ]
                    }
                )
            )
            page = build_dashboard(
                alerts,
                scorecard_path=scorecard,
                decision_scorecard_path=decision_scorecard,
                direction_forecast_scorecard_path=direction_scorecard,
                first_observed_forecasts_path=first_observed,
                forecast_action_segments_path=forecast_action_segments,
                portfolio_learning_review_path=learning_review,
                model_health_path=model_health,
                price_health_path=price_health,
            )
        self.assertIn("ABC", page)
        self.assertIn("TRIM REVIEW", page)
        self.assertIn("Drawdown &lt; review", page)
        self.assertIn("100%", page)
        self.assertIn("75%", page)
        self.assertIn("Bearish / trim review", page)
        self.assertIn("K-line evidence", page)
        self.assertNotIn("<h2>Account Overview</h2>", page)
        self.assertNotIn("Robinhood-style account view", page)
        self.assertIn('id="portfolio-sort"', page)
        self.assertIn('data-portfolio-holdings', page)
        self.assertIn('class="portfolio-holding-card signal-wait"', page)
        self.assertIn("Market Value", page)
        self.assertIn("Gain/Loss %", page)
        self.assertIn("12-1 momentum", page)
        self.assertIn("Pressure", page)
        self.assertIn("Today Return %", page)
        self.assertIn("Today Return $", page)
        self.assertIn('const selectedSort = portfolioSort.value;', page)
        self.assertIn('const field = selectedSort.replace(/-(asc|desc)$/, "");', page)
        self.assertNotIn('const [field, direction] = portfolioSort.value.split("-");', page)
        self.assertIn("First Observed Forecast Tracking", page)
        self.assertIn("wave-direction-v1", page)
        self.assertIn("M078 accountability", page)
        self.assertIn("Forecast Action Segment Comparison", page)
        self.assertIn("Acted-on proxy", page)
        self.assertIn("M079 observational comparison", page)
        self.assertIn("Open monthly portfolio-learning review", page)
        self.assertIn("sortHoldings", page)
        self.assertIn("arrangePortfolioRows", page)
        self.assertIn('row.style.gridColumn = "1"', page)
        self.assertIn("window.StockInvestorKline?.initVisibleCharts();", page)
        self.assertIn("kline-chart.js?v=20260623-scratch-ui", page)
        self.assertIn('class="refresh-strip"', page)
        self.assertIn("data-refresh-button", page)
        self.assertIn('role="progressbar"', page)
        self.assertIn("payload.progress", page)
        self.assertNotIn("@keyframes refresh-progress", page)
        self.assertIn("/api/refresh", page)
        self.assertIn("white-space:nowrap", page)
        self.assertIn("overflow-x:auto", page)
        self.assertIn('class="account-overview"', page)
        self.assertIn("Account value", page)
        self.assertIn("Margin used", page)
        self.assertIn("Gain/Loss", page)
        self.assertIn("Buying power", page)
        self.assertNotIn("<small>Cash</small>", page)
        self.assertIn('data-tab-target="opportunities"', page)
        self.assertNotIn("Latest prices", page)
        self.assertIn("Opportunities", page)
        self.assertIn("2026-01-01", page)
        self.assertIn('class="decision-board"', page)
        self.assertIn('class="signal-column buy-column"', page)
        self.assertIn('class="signal-column sell-column"', page)
        self.assertIn('<details class="signal-column wait-column">', page)
        self.assertNotIn('<details class="signal-column wait-column" open>', page)
        self.assertIn("JIRA-style BUY / SELL / WAIT lanes", page)
        self.assertIn("All-Decision Forward Evidence", page)
        self.assertIn("Displayed Direction Forecast Validation", page)
        self.assertIn("Explicit Model-Health Gates", page)
        self.assertIn("Per-Symbol Price Freshness", page)
        self.assertIn("Symbol lifecycle", page)
        self.assertIn("Test provider · declared", page)
        self.assertIn("Read Only", page)
        self.assertIn("wave-direction-v1", page)
        self.assertIn("<td>3</td><td>1</td><td>2</td>", page)
        self.assertIn("Brier score", page)
        self.assertIn("BUY/SELL Calibration Curves", page)
        self.assertIn("Directional Classification Metrics", page)
        self.assertIn("Largest False Direction Episodes", page)
        self.assertIn("Includes HOLD and ordinary REVIEW decisions", page)
        self.assertIn('class="holding-row trim_review signal-wait"', page)
        self.assertIn('data-detail-target="holding-detail-0"', page)
        self.assertIn('id="holding-drawer"', page)
        self.assertIn('data-tab-target="research"', page)
        self.assertIn("Gain / loss", page)
        self.assertIn("<strong>WAIT</strong><b>--</b>", page)
        self.assertIn("no wave analog", page)
        self.assertNotIn("Prioritized Signals", page)

    def test_dashboard_uses_latest_quote_overlay_for_front_page_price(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            alerts = root / "alerts.jsonl"
            alerts.write_text(
                json.dumps(
                    {
                        "symbol": "ABC",
                        "shares": 10,
                        "average_cost": 90,
                        "cost_basis": 900,
                        "market_value": 1000,
                        "portfolio_weight": 0.2,
                        "latest_close": 100,
                        "unrealized_return": 0.111111,
                        "alert": {"action": "HOLD", "score": 0, "reasons": []},
                        "technicals": {"return_12_to_1": 0.25},
                    }
                )
                + "\n"
            )
            quotes = root / "latest-quotes.json"
            quotes.write_text(
                json.dumps(
                    {
                        "ABC": {
                            "price": 105,
                            "previous_close": 100,
                            "today_return": 0.05,
                            "source": "test quote",
                        }
                    }
                )
            )
            page = build_dashboard(alerts, latest_quotes_path=quotes)
        self.assertIn("$105.00", page)
        self.assertIn("+5.0%", page)
        self.assertIn("$1,050.00", page)
        self.assertIn("+$150.00", page)
        self.assertIn("16.7%", page)
        self.assertIn('value="today-desc" selected>Today Return %</option>', page)
        self.assertIn('value="today-dollars-desc">Today Return $</option>', page)
        self.assertIn('class="today-pill positive"', page)
        self.assertIn('data-label="Today return %"><b>+5.0%</b>', page)
        self.assertNotIn('<small>Today</small>', page)
        self.assertIn('data-label="Today $"><b>+$50</b>', page)
        self.assertIn(".holding-today-cash,.holding-market-value,.holding-weight,.holding-gain-loss { display:block }", page)
        self.assertIn('data-label="Price"><small>Price</small><b>$105.00</b>', page)
        self.assertIn('data-label="Market Value"><small>Market Value</small><b>$1,050.00</b>', page)
        self.assertIn('data-label="Weight"><small>Weight</small><b>20.0%</b>', page)
        self.assertIn('data-label="Gain/Loss"><small>Gain/Loss</small><b>+16.7%</b>', page)
        self.assertNotIn('data-label="Prediction"', page)
        self.assertIn('rel="icon"', page)
        self.assertIn('class="mini-sparkline', page)
        self.assertNotIn("<span>Today %</span><span>Today $</span>", page)
        self.assertNotIn("<span>Portfolio %</span><span>Prediction</span>", page)
        self.assertIn("<div><small>Shares</small><b>10</b></div>", page)
        self.assertIn("<small>10 shares</small>", page)
        self.assertNotIn("<span>More</span>", page)

    def test_sparkline_points_accepts_datetime_quote_time(self):
        points = _sparkline_points(
            {
                "price": 101.0,
                "regular_market_time": "2026-06-24 20:44:12.459",
                "intraday_path": [],
            }
        )

        self.assertEqual(points[-1]["price"], 101.0)
        self.assertIsInstance(points[-1]["time"], int)

    def test_dashboard_account_overview_uses_margin_summary_and_account_chart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            alerts = root / "alerts.jsonl"
            alerts.write_text(
                json.dumps(
                    {
                        "symbol": "ABC",
                        "shares": 10,
                        "average_cost": 90,
                        "cost_basis": 900,
                        "market_value": 1000,
                        "portfolio_weight": 1.2,
                        "latest_close": 100,
                        "unrealized_return": 0.111111,
                        "alert": {"action": "HOLD", "score": 0, "reasons": []},
                        "technicals": {"return_12_to_1": 0.25},
                    }
                )
                + "\n"
            )
            prices = root / "prices.csv"
            start = date(2026, 1, 1)
            prices.write_text(
                "date,symbol,close,open,high,low,volume\n"
                + "".join(
                    f"{(start + timedelta(days=index)).isoformat()},ABC,{100 + index:.2f},"
                    f"{99 + index:.2f},{102 + index:.2f},{98 + index:.2f},100000\n"
                    for index in range(30)
                )
            )
            quotes = root / "latest-quotes.json"
            quotes.write_text(
                json.dumps(
                    {
                        "ABC": {
                            "price": 105,
                            "previous_close": 100,
                            "today_return": 0.05,
                            "intraday_path": [
                                {"time": 1_787_000_000, "price": 100},
                                {"time": 1_787_000_060, "price": 104},
                                {"time": 1_787_000_120, "price": 105},
                            ],
                        }
                    }
                )
            )
            summary = root / "summary.json"
            summary.write_text(
                json.dumps(
                    {
                        "institution_name": "Robinhood",
                        "total_cash": -250,
                        "total_buying_power": 100,
                    }
                )
            )
            snaptrade = root / "snaptrade-accounts.json"
            snaptrade.write_text(
                json.dumps(
                    {
                        "captured_at": "2026-02-01T00:00:00+00:00",
                        "accounts": [
                            {
                                "account": {
                                    "name": "Robinhood Individual",
                                    "number": "***1234",
                                    "institution_name": "Robinhood",
                                    "balance": {
                                        "total": {"amount": 800, "currency": "USD"}
                                    },
                                },
                                "balances": [{"cash": -250, "buying_power": 100}],
                                "positions": [
                                    {
                                        "symbol": "ABC",
                                        "units": 10,
                                        "price": 105,
                                        "market_value": 1050,
                                    }
                                ],
                                "balance_history": {
                                    "currency": "USD",
                                    "history": [
                                        {
                                            "date": (start + timedelta(days=index)).isoformat(),
                                            "total_value": f"{700 + index * 5:.2f}",
                                        }
                                        for index in range(30)
                                    ],
                                },
                            }
                        ],
                    }
                )
            )

            page = build_dashboard(
                alerts,
                prices_path=prices,
                latest_quotes_path=quotes,
                account_summary_path=summary,
                snaptrade_accounts_path=snaptrade,
            )

        self.assertIn("Robinhood via SnapTrade", page)
        self.assertIn("$800.00", page)
        self.assertIn("Margin used", page)
        self.assertIn("$250.00", page)
        self.assertIn("Buying power", page)
        self.assertIn("$100.00", page)
        self.assertNotIn("on cost", page)
        self.assertNotIn("net capital", page)
        self.assertIn('data-chart-symbol="__ACCOUNT__-robinhood-1234"', page)
        self.assertIn('"symbol":"__ACCOUNT__-robinhood-1234"', page)
        self.assertIn('"source":"snaptrade_balance_history"', page)
        self.assertIn("Broker-reported account value", page)
        self.assertIn('data-chart-mode="line"', page)
        self.assertIn('data-chart-range="1W"', page)

    def test_dashboard_does_not_draw_approximate_account_chart_without_balance_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            alerts = root / "alerts.jsonl"
            alerts.write_text(
                json.dumps(
                    {
                        "symbol": "ABC",
                        "shares": 10,
                        "average_cost": 90,
                        "cost_basis": 900,
                        "market_value": 1000,
                        "portfolio_weight": 1.0,
                        "latest_close": 100,
                        "unrealized_return": 0.111111,
                        "alert": {"action": "HOLD", "score": 0, "reasons": []},
                        "technicals": {},
                    }
                )
                + "\n"
            )
            prices = root / "prices.csv"
            prices.write_text(
                "date,symbol,close,open,high,low,volume\n"
                + "".join(
                    f"2026-01-{index + 1:02d},ABC,{100 + index:.2f},{99 + index:.2f},{102 + index:.2f},{98 + index:.2f},100000\n"
                    for index in range(20)
                )
            )
            summary = root / "summary.json"
            summary.write_text(
                json.dumps(
                    {
                        "institution_name": "Robinhood",
                        "account_value": 1000,
                        "total_cash": 0,
                    }
                )
            )
            snaptrade = root / "snaptrade-accounts.json"
            snaptrade.write_text(
                json.dumps(
                    {
                        "captured_at": "2026-02-01T00:00:00+00:00",
                        "accounts": [
                            {
                                "account": {
                                    "name": "Robinhood Individual",
                                    "number": "***1234",
                                    "institution_name": "Robinhood",
                                    "balance": {
                                        "total": {"amount": 1000, "currency": "USD"}
                                    },
                                },
                                "balances": [{"cash": 0, "buying_power": 100}],
                                "positions": [
                                    {
                                        "symbol": "ABC",
                                        "units": 10,
                                        "price": 100,
                                        "market_value": 1000,
                                    }
                                ],
                            }
                        ],
                    }
                )
            )
            page = build_dashboard(
                alerts,
                prices_path=prices,
                account_summary_path=summary,
                snaptrade_accounts_path=snaptrade,
            )

        self.assertIn("Exact broker account history is not available for this account yet.", page)
        self.assertNotIn('data-chart-symbol="__ACCOUNT__-"', page)

    def test_dashboard_adds_broker_tab_from_snaptrade_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            alerts = root / "alerts.jsonl"
            alerts.write_text(
                json.dumps(
                    {
                        "symbol": "ABC",
                        "shares": 10,
                        "average_cost": 90,
                        "cost_basis": 900,
                        "market_value": 1000,
                        "portfolio_weight": 1.0,
                        "latest_close": 100,
                        "unrealized_return": 0.111111,
                        "alert": {"action": "HOLD", "score": 0, "reasons": []},
                        "technicals": {},
                    }
                )
                + "\n"
            )
            snaptrade = root / "snaptrade-accounts.json"
            snaptrade.write_text(
                json.dumps(
                    {
                        "captured_at": "2026-06-24T00:25:08+00:00",
                        "position_count": 2,
                        "unique_symbols": ["FDIC91315", "TCEHY"],
                        "accounts": [
                            {
                                "account": {
                                    "name": "Robinhood Individual",
                                    "number": "***8183",
                                    "institution_name": "Robinhood",
                                    "balance": {
                                        "total": {"amount": 1000.0, "currency": "USD"}
                                    },
                                },
                                "balances": [{"cash": -50.0, "buying_power": 100.0}],
                                "balance_history": {
                                    "currency": "USD",
                                    "history": [
                                        {
                                            "date": "2026-06-23",
                                            "total_value": 950.0,
                                        },
                                        {
                                            "date": "2026-06-24",
                                            "total_value": 1000.0,
                                        },
                                    ],
                                },
                                "positions": [
                                    {
                                        "symbol": "HOOD",
                                        "description": "Robinhood Markets",
                                        "units": 10,
                                        "price": 100.0,
                                        "average_purchase_price": 70.0,
                                    }
                                ],
                            },
                            {
                                "account": {
                                    "name": "Empty Roth",
                                    "number": "***0000",
                                    "institution_name": "Fidelity",
                                    "balance": {
                                        "total": {"amount": 0.0, "currency": "USD"}
                                    },
                                },
                                "balances": [{"cash": 0.0, "buying_power": 0.0}],
                                "positions": [],
                            },
                            {
                                "account": {
                                    "name": "BrokerageLink",
                                    "number": "***4500",
                                    "institution_name": "Fidelity",
                                    "balance": {
                                        "total": {"amount": 1550.0, "currency": "USD"}
                                    },
                                    "sync_status": {
                                        "holdings": {
                                            "last_successful_sync": "2026-06-24T00:11:13+00:00"
                                        }
                                    },
                                },
                                "balances": [{"cash": 50.0, "buying_power": 75.0}],
                                "positions": [
                                    {
                                        "symbol": "TCEHY",
                                        "description": "Tencent Holdings Ltd UNS ADR",
                                        "units": 30,
                                        "price": 50.0,
                                        "average_purchase_price": 45.0,
                                    }
                                ],
                            },
                            {
                                "account": {
                                    "name": "Health Savings Account",
                                    "number": "***0135",
                                    "institution_name": "Fidelity",
                                    "balance": {
                                        "total": {"amount": 1200.0, "currency": "USD"}
                                    },
                                },
                                "balances": [{"cash": 1200.0, "buying_power": 1200.0}],
                                "positions": [
                                    {
                                        "symbol": "FDIC91315",
                                        "description": "FDIC insured deposit",
                                        "units": 1200,
                                        "price": 1.0,
                                    }
                                ],
                            },
                        ],
                    }
                )
            )

            page = build_dashboard(alerts, snaptrade_accounts_path=snaptrade)

        self.assertIn('data-tab-target="home"', page)
        self.assertIn(">Home</button>", page)
        self.assertIn('data-tab-target="broker-robinhood"', page)
        self.assertIn('data-tab-target="broker-fidelity"', page)
        self.assertIn('id="tab-broker-robinhood"', page)
        self.assertIn('id="tab-broker-fidelity"', page)
        self.assertNotIn('data-tab-target="broker"', page)
        self.assertIn("Robinhood via SnapTrade", page)
        self.assertIn("Fidelity via SnapTrade", page)
        self.assertIn("$3,750.00", page)
        self.assertIn("2 brokers · 3 funded accounts · 3 positions", page)
        self.assertIn("1 funded accounts · 1 positions · 1 symbols", page)
        self.assertIn("2 funded accounts · 2 positions · 2 symbols", page)
        self.assertEqual(page.count('class="broker-account-panel"'), 3)
        self.assertIn('data-chart-symbol="__ACCOUNT__-robinhood-8183"', page)
        self.assertIn('"source":"snaptrade_balance_history"', page)
        self.assertIn("broker-logo-robinhood", page)
        self.assertIn("broker-logo-fidelity", page)
        self.assertIn("https://robinhood.com/favicon.ico", page)
        self.assertIn("https://www.fidelity.com/favicon.ico", page)
        self.assertIn("requestAnimationFrame(() => window.StockInvestorKline?.initVisibleCharts())", page)
        self.assertNotIn("Empty Roth", page)
        self.assertIn("Robinhood Individual", page)
        self.assertIn("BrokerageLink", page)
        self.assertIn("Health Savings Account", page)
        self.assertIn("HOOD", page)
        self.assertIn("TCEHY", page)
        self.assertIn("FDIC91315", page)
        self.assertIn("401k funds, cash sweeps, and non-stock instruments", page)

    def test_dashboard_adds_moomoo_watchlist_tab(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            alerts = root / "alerts.jsonl"
            alerts.write_text(
                json.dumps(
                    {
                        "symbol": "ABC",
                        "shares": 10,
                        "average_cost": 90,
                        "cost_basis": 900,
                        "market_value": 1000,
                        "portfolio_weight": 1.0,
                        "latest_close": 100,
                        "unrealized_return": 0.111111,
                        "alert": {"action": "HOLD", "score": 0, "reasons": []},
                        "technicals": {},
                    }
                )
                + "\n"
            )
            watchlists = root / "moomoo-watchlists.json"
            watchlists.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "source": "moomoo-opend",
                        "captured_at": "2026-06-25T00:00:00+00:00",
                        "group_count": 2,
                        "symbol_count": 3,
                        "groups": [
                            {
                                "group_name": "Robinhood",
                                "symbol_count": 2,
                                "symbols": ["AFRM", "HOOD"],
                            },
                            {
                                "group_name": "401k",
                                "symbol_count": 1,
                                "symbols": ["FXAIX"],
                            },
                        ],
                        "items": [
                            {
                                "group_name": "Robinhood",
                                "code": "US.HOOD",
                                "symbol": "HOOD",
                                "market": "US",
                                "name": "Robinhood Markets",
                            },
                            {
                                "group_name": "Robinhood",
                                "code": "US.AFRM",
                                "symbol": "AFRM",
                                "market": "US",
                                "name": "Affirm",
                            },
                            {
                                "group_name": "401k",
                                "code": "US.FXAIX",
                                "symbol": "FXAIX",
                                "market": "US",
                                "name": "Fidelity 500 Index",
                            },
                        ],
                    }
                )
            )

            page = build_dashboard(alerts, moomoo_watchlists_path=watchlists)

        self.assertIn('data-tab-target="moomoo"', page)
        self.assertIn('id="tab-moomoo"', page)
        self.assertIn("broker-logo-moomoo", page)
        self.assertIn("https://www.moomoo.com/favicon.ico", page)
        self.assertIn("Moomoo OpenD · read only", page)
        self.assertIn("3 symbols", page)
        self.assertIn("Robinhood</h3>", page)
        self.assertIn("401k</h3>", page)
        self.assertIn("HOOD", page)
        self.assertIn("AFRM", page)
        self.assertIn("FXAIX", page)

    def test_dashboard_warns_but_keeps_stale_broker_account_view_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            alerts = root / "alerts.jsonl"
            alerts.write_text(
                json.dumps(
                    {
                        "symbol": "ABC",
                        "shares": 10,
                        "average_cost": 90,
                        "cost_basis": 900,
                        "market_value": 1000,
                        "portfolio_weight": 1.0,
                        "latest_close": 100,
                        "unrealized_return": 0.111111,
                        "alert": {"action": "HOLD", "score": 0, "reasons": []},
                        "technicals": {},
                    }
                )
                + "\n"
            )
            summary = root / "summary.json"
            summary.write_text(
                json.dumps(
                    {
                        "imported_at": "2026-01-01T00:00:00+00:00",
                        "total_cash": -250,
                        "total_buying_power": 100,
                    }
                )
            )

            page = build_dashboard(alerts, account_summary_path=summary)

        self.assertIn('class="account-connection-notice"', page)
        self.assertIn('data-account-data-stale="true"', page)
        self.assertIn("Account data needs refresh", page)
        self.assertIn("Showing the last imported read-only portfolio for now.", page)
        self.assertIn("Login/connect work is shelved.", page)
        self.assertNotIn('type="password"', page)
        self.assertNotIn("robinhood.com/login", page)
        self.assertNotIn('class="robinhood-connect-page"', page)
        self.assertIn('class="account-overview"', page)
        self.assertIn('class="portfolio-holdings-panel"', page)
        self.assertIn('id="holding-detail-0"', page)
        self.assertIn("<h2>$750.00</h2>", page)

    def test_dashboard_does_not_blend_evidence_across_model_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / "snapshot.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "model_version": "decision-support-v2",
                        "observed_at": "2026-01-01",
                        "results": [
                            {
                                "symbol": "ABC",
                                "alert": {
                                    "action": "TRIM_REVIEW",
                                    "score": -0.4,
                                    "reasons": [],
                                },
                            }
                        ],
                    }
                )
            )
            scorecard = Path(directory) / "scorecard.json"
            scorecard.write_text(
                '[{"model_version":"decision-support-v1","action":"TRIM_REVIEW",'
                '"horizon":"21d","observations":4,"directional_success_rate":0.75,'
                '"mean_directional_return":0.1}]'
            )
            comparison = Path(directory) / "comparison.json"
            comparison.write_text(
                json.dumps(
                    {
                        "baseline": {"actionable_rate": 0.8},
                        "candidate": {"actionable_rate": 0.6},
                        "actionable_count_change": -5,
                        "changed_symbols": {"ABC": {}},
                    }
                )
            )
            coverage = Path(directory) / "coverage.json"
            coverage.write_text(
                json.dumps(
                    {
                        "quality_coverage_rate": 0.5,
                        "valuation_coverage_rate": 0.25,
                        "revisions_coverage_rate": 0.0,
                        "v3_buy_ready_symbols": ["ABC"],
                    }
                )
            )
            page = build_dashboard(
                snapshot,
                scorecard_path=scorecard,
                comparison_path=comparison,
                fundamental_coverage_path=coverage,
            )
        self.assertIn("decision-support-v2", page)
        self.assertNotIn("75%", page)
        self.assertIn("Model Experiment", page)
        self.assertIn("Fundamental Coverage", page)
        self.assertIn("ABC", page)

    def test_dashboard_separates_exploratory_wave_history_from_live_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "snapshot.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "model_version": "decision-support-v3",
                        "results": [
                            {
                                "symbol": "ABC",
                                "alert": {"action": "HOLD", "score": 0.1, "reasons": []},
                            }
                        ],
                    }
                )
            )
            wave_snapshot = root / "wave-snapshot.json"
            wave_snapshot.write_text(
                json.dumps(
                    {
                        "waves": {
                            "ABC": {
                                "regime": "Advancing wave",
                                "active_wave_return": 0.12,
                                "wave_age_sessions": 30,
                            }
                        }
                    }
                )
            )
            experiment = root / "wave-experiment-scorecard.json"
            experiment.write_text(
                json.dumps(
                    [
                        {
                            "regime": "Advancing wave",
                            "horizon": "63d",
                            "positive_rate": 0.7,
                            "positive_rate_ci_low": 0.55,
                            "positive_rate_ci_high": 0.85,
                            "directional_symbols": 10,
                            "symbol_positive_return_rate": 0.8,
                            "symbol_positive_return_ci_low": 0.55,
                            "symbol_positive_return_ci_high": 0.95,
                            "top_symbol_return_observation_share": 0.1,
                            "beat_benchmark_rate": 0.6,
                            "beat_benchmark_ci_low": 0.31,
                            "beat_benchmark_ci_high": 0.83,
                            "benchmark_symbols": 10,
                            "symbol_positive_excess_rate": 0.6,
                            "symbol_positive_excess_ci_low": 0.31,
                            "symbol_positive_excess_ci_high": 0.83,
                            "top_symbol_observation_share": 0.1,
                            "median_return": 0.08,
                            "mean_max_gain": 0.2,
                            "mean_max_loss": -0.1,
                            "observations": 10,
                        }
                    ]
                )
            )
            conditional = root / "wave-conditional-scorecard.json"
            conditional.write_text(
                json.dumps(
                    [
                        {
                            "regime": "Advancing wave",
                            "horizon": "63d",
                            "wave_age_bucket": "EXTENDED",
                            "wave_magnitude_bucket": "DEVELOPING",
                            "positive_rate": 0.8,
                            "beat_benchmark_rate": 0.8,
                            "beat_benchmark_ci_low": 0.3,
                            "beat_benchmark_ci_high": 0.95,
                            "benchmark_symbols": 4,
                            "symbol_positive_excess_rate": 0.75,
                            "symbol_positive_excess_ci_low": 0.3,
                            "symbol_positive_excess_ci_high": 0.95,
                            "top_symbol_observation_share": 0.25,
                            "median_return": 0.1,
                            "mean_max_gain": 0.2,
                            "mean_max_loss": -0.1,
                            "observations": 5,
                        }
                    ]
                )
            )
            page = build_dashboard(
                snapshot,
                wave_snapshot_path=wave_snapshot,
                wave_experiment_scorecard_path=experiment,
                wave_conditional_scorecard_path=conditional,
            )
        self.assertIn("Historical Wave Experiment", page)
        self.assertIn("Current Wave Analog Ranking", page)
        self.assertIn("Live Structural Wave Evidence", page)
        self.assertIn("Exploratory historical 63d analogs", page)
        self.assertIn("60% (31%–83%) beat SPY", page)
        self.assertIn("cross-stock breadth", page)
        self.assertIn("Cross-stock breadth (95% CI)", page)
        self.assertIn("Inconclusive", page)
        self.assertIn('id="tab-research" class="tab-view"', page)
        self.assertIn('id="holding-detail-0" class="holding-detail" hidden', page)
        self.assertIn("not a promoted prediction model", page)
        self.assertIn("Conditional Wave Precision Audit", page)
        self.assertIn("Leave-one-symbol-out", page)
        self.assertIn("Conditional precision refused", page)
        self.assertIn("<strong>BUY</strong><b>57%</b>", page)
        self.assertIn("raw analog rate 70%", page)
        self.assertIn("57% shrunk confidence; raw analog rate 70%", page)
        self.assertIn("shrunk robust evidence", page)
        self.assertIn("direction gate", page)

    def test_review_outcome_without_directional_rate_does_not_crash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "snapshot.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "model_version": "decision-support-v3",
                        "results": [
                            {
                                "symbol": "ABC",
                                "alert": {"action": "REVIEW", "score": -0.1, "reasons": []},
                            }
                        ],
                    }
                )
            )
            scorecard = root / "decision-scorecard.json"
            scorecard.write_text(
                '[{"model_version":"decision-support-v3","action":"REVIEW",'
                '"horizon":"21d","observations":5,"positive_rate":0.6,'
                '"directional_success_rate":null}]'
            )
            page = build_dashboard(snapshot, decision_scorecard_path=scorecard)
        self.assertIn("60% positive-return rate across 5 matured outcomes", page)

    def test_research_tab_shows_direction_rate_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "snapshot.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "results": [
                            {
                                "symbol": "ABC",
                                "shares": 10,
                                "average_cost": 100,
                                "cost_basis": 1000,
                                "market_value": 1195,
                                "portfolio_weight": 0.12,
                                "latest_close": 119.5,
                                "unrealized_return": 0.195,
                                "alert": {"action": "HOLD", "score": 0, "reasons": []},
                            }
                        ]
                    }
                )
            )
            comparison = root / "direction-rate-comparison.json"
            comparison.write_text(
                json.dumps(
                    [
                        {
                            "comparison_version": "direction-rate-comparison-v1",
                            "source": "BROAD",
                            "direction": "BUY",
                            "horizon": "63d",
                            "regime": "Advancing wave",
                            "wave_age_bucket": None,
                            "wave_magnitude_bucket": None,
                            "observations": 20,
                            "directional_symbols": 12,
                            "raw_probability": 0.8,
                            "shrunk_probability": 0.65,
                            "wilson_lower_probability": 0.6,
                        }
                    ]
                )
            )
            page = build_dashboard(
                snapshot,
                direction_rate_comparison_path=comparison,
            )
        self.assertIn("Raw vs Shrunk vs Wilson Direction Rates", page)
        self.assertIn("<td>80.0%</td><td>65.0%</td><td>60.0%</td>", page)
        self.assertIn("raw rates are not promoted directly", page)

    def test_research_tab_shows_time_decayed_wave_experiment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "snapshot.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "results": [
                            {
                                "symbol": "ABC",
                                "shares": 10,
                                "average_cost": 100,
                                "cost_basis": 1000,
                                "market_value": 1195,
                                "portfolio_weight": 0.12,
                                "latest_close": 119.5,
                                "unrealized_return": 0.195,
                                "alert": {"action": "HOLD", "score": 0, "reasons": []},
                            }
                        ]
                    }
                )
            )
            time_decay = root / "wave-time-decay-scorecard.json"
            time_decay.write_text(
                json.dumps(
                    [
                        {
                            "decay_version": "wave-time-decay-v1",
                            "regime": "Advancing wave",
                            "horizon": "21d",
                            "weighted_positive_rate": 0.66,
                            "weighted_mean_return": 0.12,
                            "weighted_mean_excess_return": 0.04,
                            "weighted_observations": 8.5,
                            "symbols": 9,
                            "observations": 12,
                            "top_symbol_weight_share": 0.2,
                        }
                    ]
                )
            )
            page = build_dashboard(
                snapshot,
                wave_time_decay_scorecard_path=time_decay,
            )
        self.assertIn("Time-Decayed Wave Experiment", page)
        self.assertIn("older analogs decay with a one-year half-life", page)
        self.assertIn("<td>66.0%</td><td>12.0%</td><td>4.0%</td>", page)

    def test_research_tab_shows_multiple_testing_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "snapshot.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "results": [
                            {
                                "symbol": "ABC",
                                "alert": {"action": "HOLD", "score": 0, "reasons": []},
                            }
                        ]
                    }
                )
            )
            ledger = root / "multiple-testing-ledger.json"
            ledger.write_text(
                json.dumps(
                    {
                        "ledger_version": "multiple-testing-ledger-v1",
                        "total_hypothesis_count": 33,
                        "family_hypothesis_counts": {"structural_wave": 33},
                        "rows": [
                            {
                                "family": "structural_wave",
                                "id": "wave_conditional_scorecard",
                                "hypothesis_count": 33,
                                "multiple_testing_risk": "HIGH",
                                "family_hypothesis_count": 33,
                                "family_multiple_testing_risk": "HIGH",
                                "predeclared": True,
                                "promotion_status": "LEDGER_ONLY",
                            }
                        ],
                    }
                )
            )
            page = build_dashboard(snapshot, multiple_testing_ledger_path=ledger)
        self.assertIn("Multiple-Testing Ledger", page)
        self.assertIn("Total tested rows", page)
        self.assertIn("family-level false-discovery controls", page)
        self.assertIn("<td>structural_wave</td><td>wave_conditional_scorecard</td>", page)

    def test_research_tab_shows_false_discovery_warnings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "snapshot.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "results": [
                            {
                                "symbol": "ABC",
                                "alert": {"action": "HOLD", "score": 0, "reasons": []},
                            }
                        ]
                    }
                )
            )
            warnings = root / "false-discovery-warnings.json"
            warnings.write_text(
                json.dumps(
                    [
                        {
                            "warning_version": "false-discovery-warnings-v1",
                            "family": "structural_wave",
                            "family_hypothesis_count": 100,
                            "risk": "HIGH",
                            "status": "BLOCK_PROMOTION",
                            "message": "structural_wave has 100 tested rows; raw winners need false-discovery control.",
                        }
                    ]
                )
            )
            page = build_dashboard(snapshot, false_discovery_warnings_path=warnings)
        self.assertIn("False-Discovery Warnings", page)
        self.assertIn("BLOCK_PROMOTION", page)
        self.assertIn("Warnings block model promotion", page)

    def test_robust_conditional_direction_can_override_inconclusive_broad_direction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "snapshot.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "results": [
                            {
                                "symbol": "ABC",
                                "shares": 10,
                                "average_cost": 100,
                                "cost_basis": 1000,
                                "market_value": 1195,
                                "portfolio_weight": 0.12,
                                "latest_close": 119.5,
                                "unrealized_return": 0.195,
                                "alert": {"action": "HOLD", "score": 0, "reasons": []},
                            }
                        ]
                    }
                )
            )
            wave_snapshot = root / "waves.json"
            start = date(2025, 1, 1)
            wave_snapshot.write_text(
                json.dumps(
                    {
                        "waves": {
                            "ABC": {
                                "regime": "Advancing wave",
                                "wave_age_sessions": 15,
                                "active_wave_return": 0.1,
                                "reversal_threshold": 0.08,
                                "last_pivot_date": (start + timedelta(days=110)).isoformat(),
                                "last_pivot_price": 110,
                                "support_zone_low": 106,
                                "support_zone_high": 112,
                                "resistance_zone_low": 124,
                                "resistance_zone_high": 130,
                            }
                        }
                    }
                )
            )
            broad = root / "broad.json"
            broad.write_text(
                json.dumps(
                    [
                        {
                            "regime": "Advancing wave",
                            "horizon": "21d",
                            "observations": 20,
                            "positive_rate": 0.4,
                            "median_return": -0.01,
                            "mean_max_gain": 0.1,
                            "mean_max_loss": -0.1,
                        }
                    ]
                )
            )
            conditional = root / "conditional.json"
            conditional.write_text(
                json.dumps(
                    [
                        {
                            "regime": "Advancing wave",
                            "horizon": "21d",
                            "wave_age_bucket": "MATURE",
                            "wave_magnitude_bucket": "DEVELOPING",
                            "observations": 18,
                            "directional_symbols": 14,
                            "positive_rate": 0.83,
                            "positive_rate_ci_low": 0.6,
                            "positive_rate_ci_high": 0.95,
                            "symbol_positive_return_rate": 0.79,
                            "symbol_positive_return_ci_low": 0.52,
                            "symbol_positive_return_ci_high": 0.92,
                            "top_symbol_return_observation_share": 0.12,
                            "median_return": 0.1,
                            "mean_max_gain": 0.2,
                            "mean_max_loss": -0.05,
                        }
                    ]
                )
            )
            prices = root / "prices.csv"
            prices.write_text(
                "date,symbol,close,open,high,low,volume\n"
                + "".join(
                    f"{(start + timedelta(days=index)).isoformat()},ABC,{100 + index * 0.15:.2f},"
                    f"{99.5 + index * 0.15:.2f},{101 + index * 0.15:.2f},"
                    f"{99 + index * 0.15:.2f},{100000 + index * 100}\n"
                    for index in range(130)
                )
            )
            page = build_dashboard(
                snapshot,
                wave_snapshot_path=wave_snapshot,
                wave_experiment_scorecard_path=broad,
                wave_conditional_scorecard_path=conditional,
                prices_path=prices,
            )
        self.assertIn("<strong>BUY</strong><b>66%</b>", page)
        self.assertIn("66% shrunk confidence; raw analog rate 83%", page)
        self.assertIn('class="price-target">$106.00–$112.00</small>', page)
        self.assertIn("<h3>$106.00–$112.00</h3>", page)
        self.assertIn('class="info-tip"', page)
        self.assertIn('"label":"Buy zone"', page)
        self.assertIn('"low":106.0', page)
        self.assertIn('"high":112.0', page)
        self.assertIn("Conditional age/magnitude evidence used", page)
        self.assertIn("direction gate <b>BUY</b>", page)
        self.assertIn('class="interactive-kline"', page)
        self.assertIn('id="chart-payloads-v1"', page)
        self.assertIn("Interactive K-line · switched by candle interval", page)
        self.assertIn('data-chart-range="1D"', page)
        self.assertNotIn(">Advanced</button>", page)
        self.assertIn("Support zone", page)
        self.assertIn("Your position", page)
        self.assertIn("Average cost", page)
        self.assertIn("Cost basis", page)
        self.assertIn("PROFESSIONAL PLAN", page)
        self.assertIn("ADD REVIEW", page)
        self.assertIn("Average cost", page)
        self.assertIn('"id":"average_cost"', page)
        self.assertIn('"price":100.0', page)
        self.assertIn('<details class="advanced-details">', page)
        self.assertNotIn('<details class="advanced-details" open>', page)

    def test_mini_sparkline_uses_direction_color_and_previous_close_baseline(self):
        history = [
            Price(date=date(2026, 1, 1), close=100),
            Price(date=date(2026, 1, 2), close=103),
        ]
        sparkline = _mini_sparkline([100, 101, 103], history, "positive")

        self.assertIn('class="mini-sparkline positive"', sparkline)
        self.assertIn('class="mini-sparkline-baseline"', sparkline)
        self.assertIn("<polyline", sparkline)

    def test_poor_data_quality_blocks_kline_chart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "snapshot.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "results": [
                            {
                                "symbol": "ABC",
                                "alert": {"action": "HOLD", "score": 0, "reasons": []},
                            }
                        ]
                    }
                )
            )
            quality = root / "price-health.json"
            quality.write_text(
                json.dumps(
                    {
                        "symbols": [
                            {"symbol": "ABC", "data_quality_status": "POOR"}
                        ]
                    }
                )
            )
            page = build_dashboard(snapshot, price_health_path=quality)
        self.assertIn("K-line chart blocked by the data-quality gate", page)


if __name__ == "__main__":
    unittest.main()
