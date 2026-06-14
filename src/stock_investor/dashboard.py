from __future__ import annotations

import html
import json
from collections import Counter
from pathlib import Path

from .data import Price, load_prices
from .diagnostics import analyze_alert_burden, load_monitor_records
from .kline import classify_kline
from .wave import (
    classify_wave_directional_evidence,
    classify_wave_walk_forward_evidence,
    wave_age_bucket,
    wave_magnitude_bucket,
)


ACTION_RANK = {
    "TRIM_REVIEW": 0,
    "REVIEW": 1,
    "BUY_CANDIDATE": 2,
    "ADD_CANDIDATE": 2,
    "DATA_REVIEW": 3,
    "HOLD": 4,
}


def _load_jsonl(path: str | Path | None) -> list[dict]:
    if not path or not Path(path).exists():
        return []
    return load_monitor_records(path)


def _latest_by_symbol(records: list[dict]) -> list[dict]:
    latest = {}
    for record in records:
        symbol = str(record.get("symbol", "")).strip().upper()
        if symbol:
            latest[symbol] = record
    return sorted(
        latest.values(),
        key=lambda item: (
            ACTION_RANK.get(item.get("alert", {}).get("action", ""), 9),
            -float(item.get("portfolio_weight", 0)),
            item.get("symbol", ""),
        ),
    )


def _percent(value: object) -> str:
    return f"{float(value or 0):.1%}"


def _optional_percent(value: object) -> str:
    return "pending" if value is None else f"{float(value):.1%}"


def _optional_ratio(value: object) -> str:
    return "pending" if value is None else f"{float(value):.2f}×"


def _optional_number(value: object) -> str:
    return "pending" if value is None else f"{float(value):.3f}"


def _optional_money(value: object) -> str:
    return "pending" if value is None else f"${float(value):,.2f}"


def _health_value(value: object) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float) and 0 <= value <= 1:
        return f"{value:.0%}"
    if isinstance(value, dict):
        return " · ".join(f"{key} {item}" for key, item in sorted(value.items()))
    return str(value)


def _rate_interval(rate: object, low: object, high: object) -> str:
    if rate is None or low is None or high is None:
        return "pending"
    return f"{float(rate):.0%} ({float(low):.0%}–{float(high):.0%})"


def _clamped_rate(value: object) -> float:
    return max(0.0, min(1.0, float(value or 0)))


def _directional_rate(row: dict | None, signal_label: str, key: str) -> float | None:
    if not row or row.get(key) is None:
        return None
    rate = float(row[key])
    return 1 - rate if signal_label == "SELL" else rate


def _evidence_bar(label: str, rate: float | None, detail: str, css_class: str) -> str:
    if rate is None:
        return f"""<div class="evidence-bar {css_class}">
          <div><span>{html.escape(label)}</span><b>pending</b></div>
          <div class="bar-track"><i style="width:0%"></i></div>
          <small>{html.escape(detail)}</small>
        </div>"""
    return f"""<div class="evidence-bar {css_class}">
      <div><span>{html.escape(label)}</span><b>{rate:.0%}</b></div>
      <div class="bar-track"><i style="width:{_clamped_rate(rate):.0%}"></i></div>
      <small>{html.escape(detail)}</small>
    </div>"""


def _evidence_graphics(
    historical: dict | None,
    wave: dict,
    signal_label: str,
    signal_class: str,
) -> str:
    if not historical:
        return """<section class="evidence-graphics wait">
          <div class="probability-ring" style="--probability:0%"><b>--</b><span>direction</span></div>
          <div class="why-copy"><small>WHY WAIT</small><h3>No comparable wave sample</h3>
          <p>The system refuses a directional probability until a matching historical sample exists.</p></div>
        </section>"""
    direction_rate = _directional_rate(historical, signal_label, "positive_rate")
    breadth_rate = _directional_rate(
        historical, signal_label, "symbol_positive_return_rate"
    )
    beat_spy = historical.get("beat_benchmark_rate")
    probability = direction_rate if signal_label in {"BUY", "SELL"} else None
    direction_word = (
        "rose" if signal_label == "BUY" else "fell" if signal_label == "SELL" else "agreed"
    )
    horizon = str(historical.get("horizon", "selected horizon"))
    observations = int(historical.get("observations", 0))
    symbols = int(historical.get("directional_symbols", historical.get("symbols", 0)))
    headline = (
        f"{direction_rate:.0%} of matching waves {direction_word} over {horizon}"
        if direction_rate is not None and signal_label in {"BUY", "SELL"}
        else "Historical direction is not proven"
    )
    relative_detail = (
        f"{_historical_stance(historical)} versus SPY"
        if beat_spy is not None
        else "SPY comparison unavailable"
    )
    return f"""<section class="evidence-graphics {signal_class}">
      <div class="evidence-hero">
        <div class="probability-ring" style="--probability:{_clamped_rate(probability):.0%}">
          <b>{"--" if probability is None else f"{probability:.0%}"}</b><span>{html.escape(signal_label)} direction</span>
        </div>
        <div class="why-copy"><small>WHY {html.escape(signal_label)}</small><h3>{html.escape(headline)}</h3>
        <p>{observations} non-overlapping analogs across {symbols} stocks. BUY/SELL appears only when pooled and cross-stock 95% intervals agree.</p></div>
      </div>
      <div class="evidence-bars">
        {_evidence_bar("Matching waves", direction_rate, f"{observations} historical analogs over {horizon}", signal_class)}
        {_evidence_bar("Cross-stock agreement", breadth_rate, f"{symbols} independently contributing stocks", signal_class)}
        {_evidence_bar("Beat SPY", float(beat_spy) if beat_spy is not None else None, relative_detail, "relative")}
      </div>
    </section>"""


def _kline_chart(
    history: list[Price],
    wave: dict,
    signal_label: str,
    signal_class: str,
    probability: float | None,
    price_plan: dict | None = None,
) -> str:
    candles = [
        item
        for item in history[-126:]
        if item.open is not None and item.high is not None and item.low is not None
    ]
    if len(candles) < 20:
        return '<div class="chart-unavailable">Daily OHLCV chart unavailable.</div>'
    width, height = 580, 330
    left, right, top, price_bottom = 12, 54, 22, 240
    volume_top, volume_bottom = 260, 302
    plot_width = width - left - right
    plot_height = price_bottom - top
    price_values = [
        value
        for item in candles
        for value in (float(item.high), float(item.low))
    ]
    for key in (
        "support_zone_low",
        "support_zone_high",
        "resistance_zone_low",
        "resistance_zone_high",
        "last_pivot_price",
        "latest_close",
    ):
        if wave.get(key) is not None:
            price_values.append(float(wave[key]))
    price_low, price_high = min(price_values), max(price_values)
    padding = max((price_high - price_low) * 0.06, price_high * 0.01)
    price_low, price_high = price_low - padding, price_high + padding
    price_span = price_high - price_low or 1
    x_step = plot_width / len(candles)
    body_width = max(1.2, min(4.0, x_step * 0.62))

    def x(index: int) -> float:
        return left + (index + 0.5) * x_step

    def y(value: float) -> float:
        return top + (price_high - value) / price_span * plot_height

    zones = []
    for label, low_key, high_key, css_class in (
        ("Resistance", "resistance_zone_low", "resistance_zone_high", "resistance-zone"),
        ("Support", "support_zone_low", "support_zone_high", "support-zone"),
    ):
        if wave.get(low_key) is None or wave.get(high_key) is None:
            continue
        zone_top = y(float(wave[high_key]))
        zone_bottom = y(float(wave[low_key]))
        zones.append(
            f'<rect class="{css_class}" x="{left:.1f}" y="{zone_top:.1f}" '
            f'width="{plot_width:.1f}" height="{max(1, zone_bottom - zone_top):.1f}"/>'
            f'<text class="zone-label" x="{left + 4:.1f}" y="{zone_top + 11:.1f}">{label}</text>'
        )
    target_zone = ""
    if price_plan:
        target_top = y(float(price_plan["high"]))
        target_bottom = y(float(price_plan["low"]))
        target_mid = y(float(price_plan["midpoint"]))
        target_label = f'{signal_label} ${price_plan["low"]:.2f}–${price_plan["high"]:.2f}'
        target_zone = (
            f'<rect class="target-zone {signal_class}" x="{left:.1f}" y="{target_top:.1f}" '
            f'width="{plot_width:.1f}" height="{max(1, target_bottom - target_top):.1f}"/>'
            f'<line class="target-mid {signal_class}" x1="{left:.1f}" y1="{target_mid:.1f}" '
            f'x2="{left + plot_width:.1f}" y2="{target_mid:.1f}"/>'
            f'<rect class="target-label-bg {signal_class}" x="{left + 5:.1f}" '
            f'y="{max(top + 2, target_top + 3):.1f}" width="126" height="17" rx="4"/>'
            f'<text class="target-label" x="{left + 11:.1f}" '
            f'y="{max(top + 14, target_top + 15):.1f}">{html.escape(target_label)}</text>'
        )
    grid = []
    for fraction in (0, 0.25, 0.5, 0.75, 1):
        grid_y = top + plot_height * fraction
        grid_price = price_high - price_span * fraction
        grid.append(
            f'<line class="chart-grid" x1="{left}" y1="{grid_y:.1f}" x2="{left + plot_width:.1f}" y2="{grid_y:.1f}"/>'
            f'<text class="axis-label" x="{left + plot_width + 5:.1f}" y="{grid_y + 4:.1f}">${grid_price:.2f}</text>'
        )
    volumes = [float(item.volume or 0) for item in candles]
    max_volume = max(volumes) or 1
    candle_shapes = []
    for index, item in enumerate(candles):
        center = x(index)
        open_value, close_value = float(item.open), float(item.close)
        high_value, low_value = float(item.high), float(item.low)
        css_class = "up-candle" if close_value >= open_value else "down-candle"
        body_top = y(max(open_value, close_value))
        body_height = max(1.2, abs(y(open_value) - y(close_value)))
        volume_height = float(item.volume or 0) / max_volume * (volume_bottom - volume_top)
        candle_shapes.append(
            f'<line class="{css_class}" x1="{center:.1f}" y1="{y(high_value):.1f}" x2="{center:.1f}" y2="{y(low_value):.1f}"/>'
            f'<rect class="{css_class}" x="{center - body_width / 2:.1f}" y="{body_top:.1f}" width="{body_width:.1f}" height="{body_height:.1f}"/>'
            f'<rect class="volume {css_class}" x="{center - body_width / 2:.1f}" y="{volume_bottom - volume_height:.1f}" width="{body_width:.1f}" height="{volume_height:.1f}"/>'
        )
    pivot_line = ""
    pivot_date = wave.get("last_pivot_date")
    wave_class = (
        "buy"
        if wave.get("direction") == "ADVANCING"
        else "sell" if wave.get("direction") == "DECLINING" else "wait"
    )
    if pivot_date:
        pivot_index = next(
            (index for index, item in enumerate(candles) if item.date.isoformat() == pivot_date),
            None,
        )
        if pivot_index is not None and wave.get("last_pivot_price") is not None:
            pivot_line = (
                f'<line class="active-wave {wave_class}" x1="{x(pivot_index):.1f}" '
                f'y1="{y(float(wave["last_pivot_price"])):.1f}" x2="{x(len(candles) - 1):.1f}" '
                f'y2="{y(float(candles[-1].close)):.1f}"/>'
                f'<circle class="pivot-point {wave_class}" cx="{x(pivot_index):.1f}" '
                f'cy="{y(float(wave["last_pivot_price"])):.1f}" r="4"/>'
            )
    date_labels = "".join(
        f'<text class="axis-label date-label" x="{x(index):.1f}" y="322">{candles[index].date.strftime("%b %d")}</text>'
        for index in (0, len(candles) // 2, len(candles) - 1)
    )
    signal_probability = "--" if probability is None else f"{probability:.0%}"
    return f"""<section class="kline-chart-card">
      <div class="chart-heading"><div><small>126-session daily K-line</small><h3>Price wave in context</h3></div>
      <span class="chart-signal {signal_class}">{html.escape(signal_label)} {signal_probability}</span></div>
      <svg class="kline-chart" viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(signal_label)} evidence on daily candlestick chart">
        {''.join(grid)}{''.join(zones)}{target_zone}{''.join(candle_shapes)}{pivot_line}
        <line class="volume-divider" x1="{left}" y1="{volume_top - 5}" x2="{left + plot_width}" y2="{volume_top - 5}"/>
        {date_labels}
      </svg>
      <div class="chart-legend"><span class="support-key">Support zone</span><span class="resistance-key">Resistance zone</span><span class="wave-key">Active wave</span><span>Volume</span></div>
    </section>"""


def _sample_tier(observations: int) -> str:
    if observations >= 20:
        return "developing"
    if observations >= 10:
        return "early"
    return "very small"


def _select_historical_wave(wave: dict, evidence: dict[tuple[object, object], dict]) -> dict | None:
    if not wave:
        return None
    candidates = [
        evidence.get((wave.get("regime"), horizon))
        for horizon in ("63d", "126d", "21d")
    ]
    return next(
        (
            row
            for row in candidates
            if row and int(row.get("observations", 0)) >= 10
        ),
        None,
    ) or next((row for row in candidates if row), None)


def _select_conditional_wave(
    wave: dict,
    evidence: dict[tuple[object, object, object, object], dict],
    horizon: object,
) -> dict | None:
    _, magnitude_bucket = wave_magnitude_bucket(
        wave.get("active_wave_return"), wave.get("reversal_threshold")
    )
    return evidence.get(
        (
            wave.get("regime"),
            horizon,
            wave_age_bucket(wave.get("wave_age_sessions")),
            magnitude_bucket,
        )
    )


def _effective_historical_wave(broad: dict | None, conditional: dict | None) -> dict | None:
    if conditional and (
        _historical_stance(conditional) != "Inconclusive"
        or _directional_stance(conditional) != "WAIT"
    ):
        return conditional
    return broad


def _outcome_summary(row: dict | None) -> str:
    if not row or not row.get("observations"):
        return "No matured outcomes"
    if row.get("directional_success_rate") is not None:
        return (
            f"{float(row['directional_success_rate']):.0%} win rate "
            f"across {row['observations']} matured outcomes"
        )
    if row.get("positive_rate") is not None:
        return (
            f"{float(row['positive_rate']):.0%} positive-return rate "
            f"across {row['observations']} matured outcomes"
        )
    return f"{row['observations']} matured outcomes"


def _board_signal(historical: dict | None) -> tuple[str, str, str, str]:
    if not historical:
        return "WAIT", "wait", "--", "no wave analog"
    classification = historical.get("directional_evidence_classification")
    if classification not in {"BUY", "SELL", "WAIT"}:
        classification = classify_wave_directional_evidence(historical)
    positive_rate = historical.get("positive_rate")
    if classification == "BUY" and positive_rate is not None:
        return "BUY", "buy", f"{float(positive_rate):.0%}", "robust direction evidence"
    if classification == "SELL" and positive_rate is not None:
        return "SELL", "sell", f"{1 - float(positive_rate):.0%}", "robust direction evidence"
    return "WAIT", "wait", "--", "direction not proven"


def _price_plan(signal_label: str, wave: dict, current_price: object) -> dict | None:
    """Return a structural review zone without inventing an exact execution price."""
    if signal_label == "BUY":
        label, low_key, high_key = (
            "Buy zone",
            "support_zone_low",
            "support_zone_high",
        )
        source = "confirmed structural support"
    elif signal_label == "SELL":
        label, low_key, high_key = (
            "Sell zone",
            "resistance_zone_low",
            "resistance_zone_high",
        )
        source = "confirmed structural resistance"
    else:
        return None
    if wave.get(low_key) is None or wave.get(high_key) is None:
        return None
    low, high = sorted((float(wave[low_key]), float(wave[high_key])))
    if low <= 0 or high <= 0:
        return None
    midpoint = (low + high) / 2
    current = float(current_price or wave.get("latest_close") or 0)
    if current <= 0:
        proximity = "Current-price distance unavailable."
    elif low <= current <= high:
        proximity = "Current price is inside this review zone."
    elif current < low:
        proximity = (
            f"Zone is {low / current - 1:.1%} to {high / current - 1:.1%} "
            "above the current price."
        )
    else:
        proximity = (
            f"Zone is {1 - high / current:.1%} to {1 - low / current:.1%} "
            "below the current price."
        )
    return {
        "label": label,
        "low": low,
        "high": high,
        "midpoint": midpoint,
        "source": source,
        "proximity": proximity,
    }


def _price_plan_card(plan: dict | None, signal_class: str) -> str:
    if not plan:
        return """<section class="price-plan unavailable">
          <div><small>PRICE PLAN</small><h3>Structural price zone unavailable</h3></div>
          <p>The system refuses to invent a buy or sell price without a confirmed structural zone.</p>
        </section>"""
    tooltip = (
        f'{plan["proximity"]} Based on {plan["source"]}. '
        "Review area only; no automatic order."
    )
    return f"""<section class="price-plan {signal_class}">
      <div><small>{html.escape(plan["label"])}</small>
      <h3>{_optional_money(plan["low"])}–{_optional_money(plan["high"])}</h3></div>
      <div class="price-plan-mid"><small>Mid</small><b>{_optional_money(plan["midpoint"])}</b></div>
      <span class="info-tip" tabindex="0" data-tip="{html.escape(tooltip)}" aria-label="{html.escape(tooltip)}">i</span>
    </section>"""


def _historical_stance(row: dict) -> str:
    classification = row.get("evidence_classification")
    if classification not in {"FAVORABLE", "CAUTION", "INCONCLUSIVE"}:
        classification = classify_wave_walk_forward_evidence(row)
    if classification == "FAVORABLE":
        return "Historically favorable"
    if classification == "CAUTION":
        return "Historical caution"
    return "Inconclusive"


def _directional_stance(row: dict) -> str:
    classification = row.get("directional_evidence_classification")
    if classification not in {"BUY", "SELL", "WAIT"}:
        classification = classify_wave_directional_evidence(row)
    return classification


def _view(action: str, score: float) -> str:
    if action in {"BUY_CANDIDATE", "ADD_CANDIDATE"}:
        return "Bullish candidate"
    if action == "TRIM_REVIEW":
        return "Bearish / trim review"
    if action == "REVIEW" and score <= -0.25:
        return "Bearish review"
    if action == "REVIEW":
        return "Caution / thesis review"
    if action == "DATA_REVIEW":
        return "Insufficient evidence"
    return "Neutral"


def build_dashboard(
    alerts_path: str | Path,
    risk_path: str | Path | None = None,
    scorecard_path: str | Path | None = None,
    title: str = "Stock Investor",
    decision_scorecard_path: str | Path | None = None,
    comparison_path: str | Path | None = None,
    fundamental_coverage_path: str | Path | None = None,
    kline_scorecard_path: str | Path | None = None,
    wave_snapshot_path: str | Path | None = None,
    wave_scorecard_path: str | Path | None = None,
    wave_experiment_scorecard_path: str | Path | None = None,
    wave_conditional_scorecard_path: str | Path | None = None,
    direction_forecast_scorecard_path: str | Path | None = None,
    model_health_path: str | Path | None = None,
    price_health_path: str | Path | None = None,
    prices_path: str | Path | None = None,
) -> str:
    records = _latest_by_symbol(_load_jsonl(alerts_path))
    diagnostic = analyze_alert_burden(records)
    actions = Counter(record.get("alert", {}).get("action", "UNKNOWN") for record in records)
    kline_ready = sum(
        bool((record.get("technicals") or {}).get("ohlcv_available"))
        for record in records
    )
    model_versions = sorted(
        {record.get("model_version") for record in records if record.get("model_version")}
    )
    risk_records = _load_jsonl(risk_path)
    latest_risk = {}
    for record in risk_records:
        latest_risk[record.get("key", record.get("event_key", "risk"))] = record
    scorecard = (
        json.loads(Path(scorecard_path).read_text())
        if scorecard_path and Path(scorecard_path).exists()
        else []
    )
    decision_scorecard = (
        json.loads(Path(decision_scorecard_path).read_text())
        if decision_scorecard_path and Path(decision_scorecard_path).exists()
        else []
    )
    comparison = (
        json.loads(Path(comparison_path).read_text())
        if comparison_path and Path(comparison_path).exists()
        else None
    )
    fundamental_coverage = (
        json.loads(Path(fundamental_coverage_path).read_text())
        if fundamental_coverage_path and Path(fundamental_coverage_path).exists()
        else None
    )
    kline_scorecard = (
        json.loads(Path(kline_scorecard_path).read_text())
        if kline_scorecard_path and Path(kline_scorecard_path).exists()
        else []
    )
    wave_snapshot = (
        json.loads(Path(wave_snapshot_path).read_text()).get("waves", {})
        if wave_snapshot_path and Path(wave_snapshot_path).exists()
        else {}
    )
    chart_prices = (
        load_prices(prices_path)
        if prices_path and Path(prices_path).exists()
        else {}
    )
    wave_scorecard = (
        json.loads(Path(wave_scorecard_path).read_text())
        if wave_scorecard_path and Path(wave_scorecard_path).exists()
        else []
    )
    wave_experiment_scorecard = (
        json.loads(Path(wave_experiment_scorecard_path).read_text())
        if wave_experiment_scorecard_path
        and Path(wave_experiment_scorecard_path).exists()
        else []
    )
    historical_wave_evidence = {
        (row.get("regime"), row.get("horizon")): row
        for row in wave_experiment_scorecard
    }
    wave_conditional_scorecard = (
        json.loads(Path(wave_conditional_scorecard_path).read_text())
        if wave_conditional_scorecard_path
        and Path(wave_conditional_scorecard_path).exists()
        else []
    )
    direction_forecast_scorecard = (
        json.loads(Path(direction_forecast_scorecard_path).read_text())
        if direction_forecast_scorecard_path
        and Path(direction_forecast_scorecard_path).exists()
        else []
    )
    model_health = (
        json.loads(Path(model_health_path).read_text())
        if model_health_path and Path(model_health_path).exists()
        else None
    )
    price_health = (
        json.loads(Path(price_health_path).read_text())
        if price_health_path and Path(price_health_path).exists()
        else None
    )
    conditional_wave_evidence = {
        (
            row.get("regime"),
            row.get("horizon"),
            row.get("wave_age_bucket"),
            row.get("wave_magnitude_bucket"),
        ): row
        for row in wave_conditional_scorecard
    }
    relevant_scorecard = [
        row
        for row in scorecard
        if not model_versions or row.get("model_version") in model_versions
    ]
    evidence = {
        (row.get("action"), row.get("horizon")): row for row in relevant_scorecard
    }
    relevant_decision_scorecard = [
        row
        for row in decision_scorecard
        if not model_versions or row.get("model_version") in model_versions
    ]
    decision_evidence = {
        (row.get("action"), row.get("horizon")): row
        for row in relevant_decision_scorecard
    }
    health_gate_rows = "".join(
        f"""<tr><td><span class="health-status {str(gate.get("status", "")).lower()}">{html.escape(str(gate.get("status", "")))}</span></td>
        <td>{html.escape(str(gate.get("id", "")).replace("_", " ").title())}</td>
        <td>{html.escape(_health_value(gate.get("actual", "")))}</td>
        <td>{html.escape(_health_value(gate.get("threshold", "")))}</td>
        <td>{html.escape(str(gate.get("detail", "")))}</td></tr>"""
        for gate in (model_health or {}).get("gates", [])
    )
    model_health_panel = (
        f"""<section class="panel"><h2>Explicit Model-Health Gates</h2>
        <p class="health-summary"><span class="health-status {str(model_health.get("overall_status", "")).lower()}">{html.escape(str(model_health.get("overall_status", "")))}</span>
        {len(model_health.get("failed_gates", []))} failed · {len(model_health.get("pending_gates", []))} pending · {len(model_health.get("blocking_failures", []))} blocking</p>
        <table><thead><tr><th>Status</th><th>Gate</th><th>Actual</th><th>Threshold</th><th>Meaning</th></tr></thead>
        <tbody>{health_gate_rows}</tbody></table>
        <p class="note">PENDING means evidence has not matured; it is not treated as a pass or a failed prediction. BLOCKED means a safety or required-data gate failed.</p></section>"""
        if model_health
        else ""
    )
    price_health_rows = "".join(
        f"""<tr><td><b>{html.escape(str(row.get("symbol", "")))}</b></td>
        <td><span class="health-status {str(row.get("data_quality_status", "")).lower()}">{html.escape(str(row.get("data_quality_status", "")))}</span> {_percent(row.get("data_quality_score"))}</td>
        <td><span class="health-status {str(row.get("status", "")).lower()}">{html.escape(str(row.get("status", "")))}</span></td>
        <td>{html.escape(str(row.get("latest_date") or "missing"))}</td>
        <td>{html.escape(str(row.get("age_calendar_days") if row.get("age_calendar_days") is not None else "missing"))}</td>
        <td>{_percent(row.get("session_coverage_rate")) if row.get("session_coverage_rate") is not None else "pending"}</td>
        <td>{html.escape(str(row.get("missing_session_count", 0)))}</td>
        <td>{_percent(row.get("ohlcv_coverage_rate"))}</td>
        <td>{html.escape(str(row.get("suspicious_intraday_range_count", 0)))}</td>
        <td>{html.escape(str(row.get("suspicious_close_gap_count", 0)))}</td>
        <td>{"Review" if row.get("cost_basis_reconciliation_warning") else "—"}</td>
        <td>{html.escape(str(row.get("adjustment_type", "unknown")))} · {html.escape(str(row.get("adjustment_confidence", "unknown")).lower())}</td>
        <td>{html.escape(str(row.get("source", "")))} · {html.escape(str(row.get("source_confidence", "")).lower())}</td></tr>"""
        for row in (price_health or {}).get("symbols", [])
    )
    price_health_panel = (
        f"""<section class="panel"><h2>Per-Symbol Price Freshness</h2>
        <table><thead><tr><th>Symbol</th><th>Data quality</th><th>Status</th><th>Latest</th><th>Age days</th><th>Session coverage</th><th>Missing</th><th>OHLCV coverage</th><th>Extreme ranges</th><th>Close gaps</th><th>Cost basis</th><th>Adjustment</th><th>Source</th></tr></thead>
        <tbody>{price_health_rows}</tbody></table>
        <p class="note">Expected sessions use the latest 252 observed {html.escape(str(price_health.get("expected_session_source") or "benchmark"))} market dates, avoiding an invented holiday calendar. Source confidence distinguishes declared provenance from conservative filename inference.</p></section>"""
        if price_health
        else ""
    )

    board_rows: dict[str, list[tuple[float, float, str, str]]] = {
        "BUY": [],
        "SELL": [],
        "WAIT": [],
    }
    detail_panels = []
    for index, record in enumerate(records):
        alert = record.get("alert", {})
        action = alert.get("action", "UNKNOWN")
        score = float(alert.get("score", 0))
        action_evidence = (
            decision_evidence.get((action, "63d"))
            or decision_evidence.get((action, "21d"))
            or evidence.get((action, "63d"))
            or evidence.get((action, "21d"))
        )
        wins = _outcome_summary(action_evidence)
        reasons = "".join(
            f"<li>{html.escape(reason)}</li>" for reason in alert.get("reasons", [])
        )
        technicals = record.get("technicals") or {}
        wave = wave_snapshot.get(record.get("symbol", ""), {})
        broad_historical_wave = _select_historical_wave(wave, historical_wave_evidence)
        conditional_wave = _select_conditional_wave(
            wave,
            conditional_wave_evidence,
            broad_historical_wave.get("horizon") if broad_historical_wave else None,
        )
        historical_wave = _effective_historical_wave(
            broad_historical_wave, conditional_wave
        )
        signal_label, signal_class, signal_percent, signal_evidence = _board_signal(
            historical_wave
        )
        signal_probability = (
            float(historical_wave.get("positive_rate", 0))
            if signal_label == "BUY" and historical_wave
            else (
                1 - float(historical_wave.get("positive_rate", 1))
                if signal_label == "SELL" and historical_wave
                else None
            )
        )
        price_plan = _price_plan(
            signal_label,
            wave,
            record.get("latest_close") or wave.get("latest_close"),
        )
        evidence_graphics = _evidence_graphics(
            historical_wave, wave, signal_label, signal_class
        )
        kline_chart = _kline_chart(
            chart_prices.get(record.get("symbol", ""), []),
            wave,
            signal_label,
            signal_class,
            signal_probability,
            price_plan,
        )
        unrealized_return = record.get("unrealized_return")
        return_class = (
            "positive"
            if unrealized_return is not None and float(unrealized_return) >= 0
            else "negative"
        )
        wave_view = (
            f"""<div class="wave">
              <b>{html.escape(wave.get("regime", "Wave unavailable"))}</b> ·
              active move <b>{_optional_percent(wave.get("active_wave_return"))}</b> ·
              wave age <b>{wave.get("wave_age_sessions", "pending")} sessions</b> ·
              support zone <b>{_optional_money(wave.get("support_zone_low"))}–{_optional_money(wave.get("support_zone_high"))}</b> ·
              resistance zone <b>{_optional_money(wave.get("resistance_zone_low"))}–{_optional_money(wave.get("resistance_zone_high"))}</b> ·
              structural position <b>{_optional_percent(wave.get("structural_range_position"))}</b>
            </div>"""
            if wave
            else '<div class="wave">Structural wave evidence unavailable.</div>'
        )
        wave_history_view = (
            f"""<div class="wave-history">
              Exploratory historical {html.escape(historical_wave["horizon"])} analogs:
              <b>{html.escape(_historical_stance(historical_wave))}</b> ·
              direction gate <b>{html.escape(_directional_stance(historical_wave))}</b> ·
              <b>{_percent(historical_wave.get("positive_rate"))} positive</b> ·
              <b>{_rate_interval(historical_wave.get("beat_benchmark_rate"), historical_wave.get("beat_benchmark_ci_low"), historical_wave.get("beat_benchmark_ci_high"))} beat SPY</b> ·
              cross-stock breadth <b>{_rate_interval(historical_wave.get("symbol_positive_excess_rate"), historical_wave.get("symbol_positive_excess_ci_low"), historical_wave.get("symbol_positive_excess_ci_high"))}</b>
              across <b>{int(historical_wave.get("benchmark_symbols", 0))} symbols</b> ·
              median return <b>{_percent(historical_wave.get("median_return"))}</b> ·
              mean path <b>{_percent(historical_wave.get("mean_max_gain"))} upside /
              {_percent(historical_wave.get("mean_max_loss"))} downside</b> ·
              {_sample_tier(int(historical_wave.get("observations", 0)))} sample,
              n={int(historical_wave.get("observations", 0))}
            </div>"""
            if historical_wave
            else '<div class="wave-history">No exploratory historical analog sample for this wave regime.</div>'
        )
        conditional_wave_view = (
            f"""<div class="wave-history">
              Conditional age/magnitude evidence used:
              <b>{html.escape(conditional_wave.get("wave_age_bucket", ""))} · {html.escape(conditional_wave.get("wave_magnitude_bucket", ""))}</b> ·
              direction gate <b>{html.escape(_directional_stance(conditional_wave))}</b> ·
              relative evidence <b>{html.escape(_historical_stance(conditional_wave))}</b> ·
              n={int(conditional_wave.get("observations", 0))} across {int(conditional_wave.get("benchmark_symbols", 0))} symbols.
            </div>"""
            if conditional_wave
            and (
                _historical_stance(conditional_wave) != "Inconclusive"
                or _directional_stance(conditional_wave) != "WAIT"
            )
            else (
                f"""<div class="wave-history">
                  Conditional precision refused:
                  <b>{html.escape(conditional_wave.get("wave_age_bucket", ""))} · {html.escape(conditional_wave.get("wave_magnitude_bucket", ""))}</b>
                  remains inconclusive at n={int(conditional_wave.get("observations", 0))} across {int(conditional_wave.get("benchmark_symbols", 0))} symbols.
                </div>"""
                if conditional_wave
                else '<div class="wave-history">Conditional precision refused: no matching age/magnitude cell at the selected horizon.</div>'
            )
        )
        kline = (
            f"""<div class="kline">
              <b>{html.escape(classify_kline(technicals))}</b> ·
              K-line: ATR20 <b>{_percent(technicals.get("atr_20_percent"))}</b> ·
              volume <b>{_optional_ratio(technicals.get("volume_ratio_20"))}</b> ·
              20d breakout <b>{_percent(technicals.get("breakout_20"))}</b> ·
              range position <b>{_percent(technicals.get("close_position_20"))}</b> ·
              latest gap <b>{_optional_percent(technicals.get("latest_gap"))}</b>
            </div>"""
            if technicals.get("ohlcv_available")
            else '<div class="kline">Full K-line OHLCV evidence unavailable.</div>'
        )
        detail_id = f"holding-detail-{index}"
        board_rows[signal_label].append(
            (
                signal_probability or 0,
                float(record.get("portfolio_weight") or 0),
                str(record.get("symbol", "")),
                f"""
            <button type="button" class="holding-row {action.lower()} signal-{signal_class}" data-detail-target="{detail_id}">
                <span class="ticker"><strong>{html.escape(record.get("symbol", ""))}</strong></span>
                <span class="decision-signal {signal_class}">
                  <strong>{signal_label}</strong><b>{signal_percent}</b>
                  <small>{signal_evidence}</small>
                  {f'<small class="price-target">{_optional_money(price_plan["low"])}–{_optional_money(price_plan["high"])}</small>' if price_plan else ''}
                </span>
                <span class="board-basics">
                  <span><small>Close</small><b>${float(record.get("latest_close") or 0):,.2f}</b></span>
                  <span class="{return_class}"><small>Gain / loss</small><b>{_optional_percent(unrealized_return)}</b></span>
                  <span><small>Weight</small><b>{_percent(record.get("portfolio_weight"))}</b></span>
                </span>
            </button>""",
            )
        )
        detail_panels.append(
            f"""
            <section id="{detail_id}" class="holding-detail" hidden>
              <div class="drawer-heading">
                <div><h2>{html.escape(record.get("symbol", ""))}</h2><span class="decision-signal {signal_class}"><strong>{signal_label}</strong><b>{signal_percent}</b></span></div>
                <span class="board-action">{html.escape(action.replace("_", " "))}</span>
              </div>
                {evidence_graphics}
                {_price_plan_card(price_plan, signal_class) if signal_label in {"BUY", "SELL"} else ""}
                {kline_chart}
                <details class="advanced-details">
                  <summary>Advanced details</summary>
                <div class="detail-title">
                  <div><b>{html.escape(_view(action, score))}</b><span>Portfolio action view</span></div>
                  <div><b>{html.escape(wins)}</b><span>Live outcome validation</span></div>
                </div>
                <div class="metrics">
                  <span>Market value <b>${float(record.get("market_value") or 0):,.2f}</b></span>
                  <span>Drawdown <b>{_percent(technicals.get("drawdown_from_high"))}</b></span>
                  <span>12-1 momentum <b>{_percent(technicals.get("return_12_to_1"))}</b></span>
                  <span>Suggested max weight <b>{_optional_percent((record.get("risk") or {}).get("suggested_max_weight"))}</b></span>
                </div>
                {wave_view}
                {wave_history_view}
                {conditional_wave_view}
                {kline}
                <ul>{reasons}</ul>
                </details>
            </section>"""
        )

    sorted_board_rows = {
        signal: [
            row[3]
            for row in sorted(
                signal_rows,
                key=lambda row: (-row[0], -row[1], row[2]),
            )
        ]
        for signal, signal_rows in board_rows.items()
    }
    prioritized_board = f"""
    <section class="decision-board" aria-label="Prioritized directional signals">
      <section class="signal-column buy-column">
        <header><div><small>Highest probability first</small><h3>BUY</h3></div><b>{len(sorted_board_rows["BUY"])}</b></header>
        <div class="signal-stack">{''.join(sorted_board_rows["BUY"]) or '<p class="empty-state">No robust buy direction today.</p>'}</div>
      </section>
      <section class="signal-column sell-column">
        <header><div><small>Highest probability first</small><h3>SELL</h3></div><b>{len(sorted_board_rows["SELL"])}</b></header>
        <div class="signal-stack">{''.join(sorted_board_rows["SELL"]) or '<p class="empty-state">No robust sell direction today.</p>'}</div>
      </section>
      <details class="signal-column wait-column">
        <summary><div><small>Direction not proven</small><h3>WAIT</h3></div><b>{len(sorted_board_rows["WAIT"])}</b></summary>
        <div class="signal-stack">{''.join(sorted_board_rows["WAIT"]) or '<p class="empty-state">No holdings are waiting.</p>'}</div>
      </details>
    </section>"""

    current_analogs = []
    for record in records:
        wave = wave_snapshot.get(record.get("symbol", ""), {})
        broad_historical = _select_historical_wave(wave, historical_wave_evidence)
        conditional = _select_conditional_wave(
            wave,
            conditional_wave_evidence,
            broad_historical.get("horizon") if broad_historical else None,
        )
        historical = _effective_historical_wave(broad_historical, conditional)
        if historical:
            current_analogs.append((record, wave, historical))
    current_wave_rows = "".join(
        f"<tr><td><b>{html.escape(record.get('symbol', ''))}</b></td>"
        f"<td>{html.escape(_directional_stance(historical))}</td>"
        f"<td>{html.escape(_historical_stance(historical))}</td>"
        f"<td>{html.escape(wave.get('regime', ''))}</td>"
        f"<td>{html.escape(historical['horizon'])}</td>"
        f"<td>{_rate_interval(historical.get('beat_benchmark_rate'), historical.get('beat_benchmark_ci_low'), historical.get('beat_benchmark_ci_high'))}</td>"
        f"<td>{_rate_interval(historical.get('symbol_positive_excess_rate'), historical.get('symbol_positive_excess_ci_low'), historical.get('symbol_positive_excess_ci_high'))}</td>"
        f"<td>{_percent(historical.get('median_return'))}</td>"
        f"<td>{_percent(historical.get('mean_max_gain'))} / {_percent(historical.get('mean_max_loss'))}</td>"
        f"<td>{_optional_percent(historical.get('directional_leave_one_out_rate'))}</td>"
        f"<td>{int(historical.get('benchmark_symbols', 0))} symbols · {int(historical['observations'])} observations</td></tr>"
        for record, wave, historical in sorted(
            current_analogs,
            key=lambda item: (
                -float(item[2].get("beat_benchmark_ci_low") or 0),
                -int(item[2].get("observations", 0)),
                item[0].get("symbol", ""),
            ),
        )
    ) or '<tr><td colspan="11">No current holdings have historical wave analog evidence.</td></tr>'

    risk_items = "".join(
        f"<li><b>{html.escape(record.get('severity', ''))}</b> "
        f"{html.escape(record.get('message', ''))}</li>"
        for record in latest_risk.values()
    ) or "<li>No persisted portfolio-risk alerts.</li>"
    ranked_evidence = sorted(
        (
            row
            for row in relevant_scorecard
            if row.get("directional_success_rate") is not None
            and row.get("observations", 0) > 0
        ),
        key=lambda row: (
            -float(row["directional_success_rate"]),
            -int(row["observations"]),
        ),
    )
    evidence_rows = "".join(
        f"<tr><td>{html.escape(row['action'].replace('_', ' '))}</td>"
        f"<td>{html.escape(row['horizon'])}</td>"
        f"<td>{float(row['directional_success_rate']):.0%}</td>"
        f"<td>{int(row['observations'])}</td>"
        f"<td>{_percent(row.get('mean_directional_return'))}</td></tr>"
        for row in ranked_evidence
    ) or '<tr><td colspan="5">No matured forward outcomes yet. Win rates will appear after 21+ sessions.</td></tr>'
    decision_evidence_rows = "".join(
        f"<tr><td>{html.escape(row['action'].replace('_', ' '))}</td>"
        f"<td>{html.escape(row['horizon'])}</td>"
        f"<td>{int(row['observations'])}</td>"
        f"<td>{_optional_percent(row.get('positive_rate'))}</td>"
        f"<td>{_optional_percent(row.get('mean_excess_return'))}</td>"
        f"<td>{_optional_percent(row.get('directional_success_rate'))}</td></tr>"
        for row in sorted(
            relevant_decision_scorecard,
            key=lambda row: (
                row.get("action", ""),
                int(str(row.get("horizon", "0d")).removesuffix("d")),
            ),
        )
    ) or '<tr><td colspan="6">No all-decision observations have been recorded yet.</td></tr>'
    generated = max(
        (record.get("observed_at") or "unknown" for record in records),
        default="unknown",
    )
    model_label = ", ".join(model_versions) or "model version unavailable"
    comparison_html = ""
    if comparison:
        baseline = comparison["baseline"]
        candidate = comparison["candidate"]
        changed = ", ".join(sorted(comparison.get("changed_symbols", {}))) or "none"
        comparison_html = f"""
<section class="panel"><h2>Model Experiment</h2>
<div class="experiment">
  <div><b>{baseline["actionable_rate"]:.0%}</b><span>Baseline action-review rate</span></div>
  <div><b>{candidate["actionable_rate"]:.0%}</b><span>Candidate action-review rate</span></div>
  <div><b>{int(comparison["actionable_count_change"]):+d}</b><span>Action-review count change</span></div>
</div>
<p class="note">Changed symbols: {html.escape(changed)}. Selectivity improvement alone does not promote a model; forward outcomes must mature.</p>
</section>"""
    coverage_html = ""
    if fundamental_coverage:
        coverage_html = f"""
<section class="panel"><h2>Fundamental Coverage</h2>
<div class="experiment">
  <div><b>{fundamental_coverage["quality_coverage_rate"]:.0%}</b><span>Quality coverage</span></div>
  <div><b>{fundamental_coverage["valuation_coverage_rate"]:.0%}</b><span>Valuation coverage</span></div>
  <div><b>{len(fundamental_coverage["v3_buy_ready_symbols"])}</b><span>V3 buy-ready names</span></div>
</div>
<p class="note">Revisions coverage: {fundamental_coverage["revisions_coverage_rate"]:.0%}. V3 treats unavailable revisions as neutral; quality and valuation remain required.</p>
</section>"""
    kline_evidence_rows = "".join(
        f"<tr><td>{html.escape(row['regime'])}</td>"
        f"<td>{html.escape(row['horizon'])}</td>"
        f"<td>{_percent(row['positive_rate'])}</td>"
        f"<td>{int(row['observations'])}</td>"
        f"<td>{_percent(row['mean_return'])}</td></tr>"
        for row in sorted(
            kline_scorecard,
            key=lambda row: (-float(row["mean_return"]), -int(row["observations"])),
        )
    ) or '<tr><td colspan="5">No matured K-line regime outcomes yet.</td></tr>'
    wave_evidence_rows = "".join(
        f"<tr><td>{html.escape(row['regime'])}</td>"
        f"<td>{html.escape(row['horizon'])}</td>"
        f"<td>{_percent(row['positive_rate'])}</td>"
        f"<td>{int(row['observations'])}</td>"
        f"<td>{_percent(row['mean_return'])}</td></tr>"
        for row in sorted(
            wave_scorecard,
            key=lambda row: (-float(row["mean_return"]), -int(row["observations"])),
        )
    ) or '<tr><td colspan="5">No matured structural-wave outcomes yet.</td></tr>'
    wave_experiment_rows = "".join(
        f"<tr><td>{html.escape(row['regime'])}</td>"
        f"<td>{html.escape(row['horizon'])}</td>"
        f"<td>{html.escape(_directional_stance(row))}</td>"
        f"<td>{_percent(row['positive_rate'])}</td>"
        f"<td>{_rate_interval(row.get('symbol_positive_return_rate'), row.get('symbol_positive_return_ci_low'), row.get('symbol_positive_return_ci_high'))}</td>"
        f"<td>{_rate_interval(row.get('beat_benchmark_rate'), row.get('beat_benchmark_ci_low'), row.get('beat_benchmark_ci_high'))}</td>"
        f"<td>{_rate_interval(row.get('symbol_positive_excess_rate'), row.get('symbol_positive_excess_ci_low'), row.get('symbol_positive_excess_ci_high'))}</td>"
        f"<td>{_percent(row['median_return'])}</td>"
        f"<td>{_percent(row['mean_max_gain'])}</td>"
        f"<td>{_percent(row['mean_max_loss'])}</td>"
        f"<td>{_optional_percent(row.get('directional_leave_one_out_rate'))}</td>"
        f"<td>{int(row.get('benchmark_symbols', 0))} symbols · {int(row['observations'])} observations · top share {_optional_percent(row.get('top_symbol_observation_share'))}</td></tr>"
        for row in sorted(
            wave_experiment_scorecard,
            key=lambda row: (
                -(
                    float(row["beat_benchmark_ci_low"])
                    if row.get("beat_benchmark_ci_low") is not None
                    else -1
                ),
                -int(row["observations"]),
                -float(row["positive_rate"]),
            ),
        )
    ) or '<tr><td colspan="12">No historical wave experiment outcomes available.</td></tr>'
    conditional_wave_rows = "".join(
        f"<tr><td>{html.escape(_historical_stance(row))}</td>"
        f"<td>{html.escape(_directional_stance(row))}</td>"
        f"<td>{html.escape(row['regime'])}</td>"
        f"<td>{html.escape(row['horizon'])}</td>"
        f"<td>{html.escape(row['wave_age_bucket'])}</td>"
        f"<td>{html.escape(row['wave_magnitude_bucket'])}</td>"
        f"<td>{_rate_interval(row.get('beat_benchmark_rate'), row.get('beat_benchmark_ci_low'), row.get('beat_benchmark_ci_high'))}</td>"
        f"<td>{_rate_interval(row.get('symbol_positive_excess_rate'), row.get('symbol_positive_excess_ci_low'), row.get('symbol_positive_excess_ci_high'))}</td>"
        f"<td>{_optional_percent(row.get('directional_leave_one_out_rate'))}</td>"
        f"<td>{int(row.get('benchmark_symbols', 0))} symbols · {int(row['observations'])} observations</td></tr>"
        for row in sorted(
            wave_conditional_scorecard,
            key=lambda row: (
                {"FAVORABLE": 0, "CAUTION": 1, "INCONCLUSIVE": 2}.get(
                    row.get("evidence_classification"), 3
                ),
                -int(row.get("observations", 0)),
                row.get("regime", ""),
            ),
        )
    ) or '<tr><td colspan="10">No conditional wave evidence available.</td></tr>'
    direction_validation_rows = "".join(
        f"<tr><td>{html.escape(row['forecast_version'])}</td>"
        f"<td>{html.escape(row['direction'])}</td>"
        f"<td>{html.escape(row['horizon'])}</td>"
        f"<td>{int(row['forecast_episodes'])}</td>"
        f"<td>{int(row['observations'])}</td>"
        f"<td>{int(row['pending'])}</td>"
        f"<td>{_optional_percent(row.get('mean_probability'))}</td>"
        f"<td>{_optional_percent(row.get('directional_success_rate'))}</td>"
        f"<td>{_optional_number(row.get('brier_score'))}</td></tr>"
        for row in direction_forecast_scorecard
    ) or '<tr><td colspan="9">Displayed forecasts are now recorded; no scorecard rows yet.</td></tr>'
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>
:root {{ --bg:#000; --panel:#0b0b0b; --panel-raised:#121212; --muted:#8c8c8c; --text:#f5f5f5;
--line:#252525; --red:#ff5a5f; --amber:#f5b642; --blue:#a6a6a6; --green:#00c805; --green-dim:#003b12; }}
* {{ box-sizing:border-box }} body {{ margin:0; background:var(--bg);
color:var(--text); font:15px/1.45 Inter,ui-sans-serif,system-ui,-apple-system,sans-serif }}
main {{ max-width:1240px; margin:auto; padding:34px 24px 80px }}
h1 {{ margin:0; font-size:40px; font-weight:750; letter-spacing:-2px }} h1::after {{ color:var(--green); content:"."; }}
.sub {{ color:var(--muted); margin:5px 0 28px }}
.grid {{ display:grid; grid-template-columns:repeat(5,1fr); gap:12px; margin-bottom:24px }}
.stat,.panel,.holding-row {{ background:var(--panel); border:1px solid var(--line); border-radius:10px }}
.stat {{ padding:18px }} .stat b {{ display:block; font-size:28px }} .stat span {{ color:var(--muted) }}
.warning {{ color:var(--amber) }} .panel {{ padding:20px; margin:18px 0 }} h2 {{ margin:0 0 12px; font-size:19px }}
.tabs {{ border-bottom:1px solid var(--line); display:flex; gap:24px; margin:22px 0 22px }} .tab-button {{ background:transparent; border:0; border-bottom:2px solid transparent; color:var(--muted); cursor:pointer; font:inherit; font-weight:650; margin-bottom:-1px; padding:10px 1px }}
.tab-button:hover {{ color:var(--text) }} .tab-button.active {{ border-bottom-color:var(--green); color:var(--green) }} .tab-view {{ display:none }} .tab-view.active {{ display:block }}
.portfolio-board {{ margin:12px 0 24px }}
.board-intro {{ display:flex; align-items:end; justify-content:space-between; gap:18px; margin-top:12px }}
.board-intro h2 {{ margin:0; font-size:25px }} .board-intro p {{ color:var(--muted); margin:0 }}
.decision-board {{ align-items:start; display:grid; gap:12px; grid-template-columns:repeat(3,minmax(0,1fr)); margin-top:16px }}
.signal-column {{ background:var(--panel); border:1px solid var(--line); border-radius:10px; min-width:0; overflow:hidden }}
.signal-column header,.signal-column summary {{ align-items:center; display:flex; justify-content:space-between; list-style:none; padding:14px 15px }}
.signal-column summary {{ cursor:pointer }} .signal-column summary::-webkit-details-marker {{ display:none }}
.signal-column header small,.signal-column summary small {{ color:var(--muted); display:block; font-size:10px; letter-spacing:.4px; text-transform:uppercase }}
.signal-column h3 {{ font-size:20px; margin:1px 0 0 }} .signal-column header>b,.signal-column summary>b {{ align-items:center; border-radius:999px; display:flex; font-size:13px; height:28px; justify-content:center; min-width:28px; padding:0 8px }}
.buy-column header {{ border-bottom:1px solid #064b19 }} .buy-column h3,.buy-column header>b {{ color:var(--green) }} .buy-column header>b {{ background:var(--green-dim) }}
.sell-column header {{ border-bottom:1px solid #562125 }} .sell-column h3,.sell-column header>b {{ color:var(--red) }} .sell-column header>b {{ background:#321214 }}
.wait-column summary {{ border-bottom:1px solid transparent }} .wait-column[open] summary {{ border-bottom-color:#55481b }} .wait-column h3,.wait-column summary>b {{ color:var(--amber) }} .wait-column summary>b {{ background:#2b240f }}
.signal-stack {{ display:grid; gap:7px; padding:8px }} .empty-state {{ color:var(--muted); margin:0; padding:14px 8px }}
.holding-row {{ border-left:3px solid var(--line); color:var(--text); cursor:pointer; display:grid; font:inherit; grid-template-columns:90px minmax(180px,1.5fr) minmax(260px,1.6fr); gap:14px; align-items:center; padding:13px 16px; text-align:left; transition:background .15s,border-color .15s,transform .15s; width:100% }}
.holding-row.signal-sell {{ border-left-color:var(--red) }} .holding-row.signal-buy {{ border-left-color:var(--green) }} .holding-row.signal-wait {{ border-left-color:var(--amber) }}
.holding-row:hover,.holding-row:focus-visible {{ background:var(--panel-raised); border-color:#3b3b3b; outline:none; transform:translateY(-1px) }} .holding-row span {{ min-width:0 }} .holding-row small {{ color:var(--muted); display:block; font-size:11px; letter-spacing:.3px }}
.holding-row b {{ display:block; white-space:nowrap }} .ticker strong {{ display:block; font-size:21px }} .ticker small {{ margin-top:1px }}
.board-basics {{ display:grid; grid-template-columns:repeat(3,1fr); gap:12px }}
.signal-column .holding-row {{ grid-template-columns:56px 1fr; padding:11px }}
.signal-column .ticker strong {{ font-size:17px }} .signal-column .decision-signal {{ padding:7px 9px }}
.signal-column .decision-signal strong {{ font-size:13px }} .signal-column .decision-signal b {{ font-size:18px }}
.signal-column .board-basics {{ grid-column:1 / -1; gap:6px }} .signal-column .board-basics small {{ font-size:9px }} .signal-column .board-basics b {{ font-size:12px }}
.decision-signal {{ align-items:baseline; border:1px solid transparent; border-radius:7px; display:grid; grid-template-columns:auto 1fr; gap:0 10px; padding:9px 12px }}
.decision-signal strong {{ font-size:16px; letter-spacing:.8px }} .decision-signal b {{ font-size:22px; text-align:right }}
.decision-signal small {{ grid-column:1 / -1; opacity:.72 }} .decision-signal.buy {{ background:var(--green-dim); border-color:#007a26; color:var(--green) }}
.decision-signal.sell {{ background:#321214; border-color:#702a2e; color:var(--red) }} .decision-signal.hold {{ background:#202020; border-color:#3b3b3b; color:#c8c8c8 }}
.decision-signal.wait {{ background:#2b240f; border-color:#65551e; color:var(--amber) }}
.decision-signal .price-target {{ border-top:1px solid currentColor; font-weight:750; margin-top:5px; opacity:1; padding-top:5px }}
.outlook,.board-action {{ border-radius:999px; display:inline-block; font-size:11px; font-weight:800; letter-spacing:.5px; padding:6px 9px; text-align:center }}
.outlook.positive,.outlook.favorable {{ background:var(--green-dim); color:var(--green) }} .outlook.caution {{ background:#321214; color:var(--red) }}
.outlook.watch {{ background:#2b240f; color:var(--amber) }} .outlook.unknown {{ background:#202020; color:#c8c8c8 }}
.health-summary {{ align-items:center; display:flex; gap:10px }} .health-status {{ border-radius:999px; display:inline-block; font-size:10px; font-weight:800; letter-spacing:.4px; padding:5px 8px }}
.health-status.pass,.health-status.ready {{ background:var(--green-dim); color:var(--green) }} .health-status.fail,.health-status.blocked {{ background:#321214; color:var(--red) }} .health-status.pending {{ background:#2b240f; color:var(--amber) }} .health-status.degraded {{ background:#35240c; color:#ffb84d }}
.health-status.fresh {{ background:var(--green-dim); color:var(--green) }} .health-status.stale,.health-status.missing {{ background:#321214; color:var(--red) }}
.health-status.good {{ background:var(--green-dim); color:var(--green) }} .health-status.review {{ background:#2b240f; color:var(--amber) }} .health-status.poor {{ background:#321214; color:var(--red) }}
.board-action {{ background:#1b1b1b; color:var(--muted) }} .positive b {{ color:var(--green) }} .negative b {{ color:var(--red) }}
.drawer-backdrop {{ background:rgba(0,0,0,.78); display:none; inset:0; position:fixed; z-index:20 }} .drawer-backdrop.open {{ display:block }}
.drawer {{ background:#050505; border-left:1px solid var(--line); bottom:0; box-shadow:-24px 0 60px rgba(0,0,0,.75); max-width:720px; overflow:auto; padding:22px; position:fixed; right:0; top:0; transform:translateX(105%); transition:transform .2s ease; width:min(94vw,720px); z-index:30 }}
.drawer.open {{ transform:translateX(0) }} .drawer-close {{ background:#171717; border:1px solid var(--line); border-radius:999px; color:var(--text); cursor:pointer; display:block; font:inherit; margin-left:auto; padding:7px 12px; position:sticky; top:0; z-index:2 }}
.drawer-heading {{ align-items:center; display:flex; justify-content:space-between; gap:12px; margin:34px 0 18px }} .drawer-heading h2 {{ display:inline; font-size:32px; margin:0 10px 0 0 }}
.holding-detail {{ overflow-wrap:anywhere; padding:0 }} .detail-title {{ display:grid; grid-template-columns:repeat(2,1fr); gap:10px }}
.evidence-graphics {{ --tone:var(--amber); background:#0b0b0b; border:1px solid var(--line); border-radius:10px; margin:0 0 12px; padding:14px }}
.evidence-graphics.buy {{ --tone:var(--green) }} .evidence-graphics.sell {{ --tone:var(--red) }}
.evidence-hero {{ align-items:center; display:grid; gap:16px; grid-template-columns:118px 1fr }}
.probability-ring {{ align-items:center; background:radial-gradient(circle,#0b0b0b 57%,transparent 59%),conic-gradient(var(--tone) var(--probability),#262626 0); border-radius:50%; display:flex; flex-direction:column; height:112px; justify-content:center; width:112px }}
.probability-ring b {{ color:var(--tone); font-size:27px }} .probability-ring span {{ color:var(--muted); font-size:10px; text-transform:uppercase }}
.why-copy small {{ color:var(--tone); font-size:10px; font-weight:750; letter-spacing:.6px }} .why-copy h3 {{ font-size:19px; line-height:1.2; margin:4px 0 7px }} .why-copy p {{ color:var(--muted); font-size:12px; margin:0 }}
.evidence-bars {{ display:grid; gap:10px; margin-top:15px }} .evidence-bar>div:first-child {{ display:flex; justify-content:space-between }}
.evidence-bar span,.evidence-bar small {{ color:var(--muted); font-size:11px }} .evidence-bar b {{ color:var(--text); font-size:12px }}
.bar-track {{ background:#242424; border-radius:999px; height:7px; margin:4px 0; overflow:hidden }} .bar-track i {{ background:var(--tone); border-radius:999px; display:block; height:100% }}
.evidence-bar.relative .bar-track i {{ background:#aaa }} .evidence-bar.relative b {{ color:#ddd }}
.price-plan {{ align-items:center; background:#0b0b0b; border:1px solid var(--line); border-left:4px solid var(--amber); border-radius:10px; display:grid; gap:8px 16px; grid-template-columns:1fr auto auto; margin:0 0 12px; padding:13px 15px }}
.price-plan.buy {{ border-left-color:var(--green) }} .price-plan.sell {{ border-left-color:var(--red) }}
.price-plan small {{ color:var(--muted); display:block; font-size:10px; font-weight:750; letter-spacing:.5px; text-transform:uppercase }}
.price-plan h3 {{ font-size:25px; margin:2px 0 0 }} .price-plan-mid {{ text-align:right }} .price-plan-mid b {{ display:block; font-size:18px }}
.price-plan.unavailable {{ display:block }} .info-tip {{ align-items:center; border:1px solid #555; border-radius:50%; color:var(--muted); cursor:help; display:flex; font-size:11px; font-weight:800; height:20px; justify-content:center; position:relative; width:20px }}
.info-tip::after {{ background:#222; border:1px solid #555; border-radius:6px; bottom:29px; color:#ddd; content:attr(data-tip); display:none; font-size:11px; font-weight:500; line-height:1.35; padding:8px; position:absolute; right:-6px; text-transform:none; width:240px; z-index:5 }}
.info-tip:hover::after,.info-tip:focus::after {{ display:block }} .info-tip:focus {{ border-color:#aaa; outline:none }}
.kline-chart-card {{ background:#0b0b0b; border:1px solid var(--line); border-radius:10px; margin:0 0 12px; padding:13px }}
.chart-heading {{ align-items:center; display:flex; justify-content:space-between; margin-bottom:7px }} .chart-heading small {{ color:var(--muted); font-size:10px; text-transform:uppercase }} .chart-heading h3 {{ font-size:17px; margin:1px 0 0 }}
.chart-signal {{ border-radius:999px; font-size:12px; font-weight:750; padding:6px 9px }} .chart-signal.buy {{ background:var(--green-dim); color:var(--green) }} .chart-signal.sell {{ background:#321214; color:var(--red) }} .chart-signal.wait {{ background:#2b240f; color:var(--amber) }}
.kline-chart {{ display:block; height:auto; overflow:visible; width:100% }} .chart-grid {{ stroke:#242424; stroke-width:1 }} .axis-label {{ fill:#777; font-size:8px }} .date-label {{ text-anchor:middle }}
.support-zone {{ fill:rgba(0,200,5,.10) }} .resistance-zone {{ fill:rgba(255,90,95,.10) }} .zone-label {{ fill:#999; font-size:8px; text-transform:uppercase }}
.target-zone.buy {{ fill:rgba(0,200,5,.22); stroke:var(--green); stroke-width:1 }} .target-zone.sell {{ fill:rgba(255,90,95,.22); stroke:var(--red); stroke-width:1 }}
.target-mid {{ stroke-width:1.7; stroke-dasharray:4 3 }} .target-mid.buy {{ stroke:var(--green) }} .target-mid.sell {{ stroke:var(--red) }}
.target-label-bg.buy {{ fill:#006b22 }} .target-label-bg.sell {{ fill:#8b252a }} .target-label {{ fill:#fff; font-size:8px; font-weight:800 }}
.up-candle {{ fill:var(--green); stroke:var(--green); stroke-width:1 }} .down-candle {{ fill:var(--red); stroke:var(--red); stroke-width:1 }} .volume {{ opacity:.22; stroke:none }}
.active-wave {{ fill:none; stroke-width:2.2; stroke-dasharray:5 3 }} .active-wave.buy,.pivot-point.buy {{ stroke:var(--green); fill:var(--green) }} .active-wave.sell,.pivot-point.sell {{ stroke:var(--red); fill:var(--red) }} .active-wave.wait,.pivot-point.wait {{ stroke:var(--amber); fill:var(--amber) }}
.volume-divider {{ stroke:#333; stroke-width:1 }} .chart-legend {{ color:var(--muted); display:flex; flex-wrap:wrap; font-size:10px; gap:12px; margin-top:3px }} .chart-legend span::before {{ background:#777; border-radius:2px; content:""; display:inline-block; height:7px; margin-right:4px; width:7px }}
.chart-legend .support-key::before {{ background:var(--green) }} .chart-legend .resistance-key::before {{ background:var(--red) }} .chart-legend .wave-key::before {{ background:var(--amber) }}
.chart-unavailable {{ background:#111; border-radius:7px; color:var(--muted); margin-bottom:12px; padding:18px }}
.advanced-details {{ border-top:1px solid var(--line); margin-top:12px; padding-top:8px }} .advanced-details summary {{ color:var(--muted); cursor:pointer; font-weight:650; padding:8px 0 }} .advanced-details[open] summary {{ color:var(--text) }}
.detail-title div {{ background:#111; border-radius:7px; padding:10px }} .detail-title span {{ color:var(--muted); display:block; font-size:11px; margin-top:3px }}
.metrics {{ display:grid; grid-template-columns:repeat(4,1fr); gap:7px; margin:14px 0; color:var(--muted) }}
.drawer .detail-title {{ grid-template-columns:1fr }} .drawer .metrics {{ grid-template-columns:repeat(2,1fr) }}
.metrics b {{ color:var(--text) }} ul {{ margin:8px 0 0; padding-left:20px; color:#d0d0d0 }}
.kline {{ color:var(--muted); font-size:13px; margin:8px 0 }} .kline b {{ color:var(--text) }}
.wave {{ background:#111; border-radius:7px; color:var(--muted); font-size:13px; margin:10px 0; padding:10px }} .wave b {{ color:var(--text) }}
.wave-history {{ color:var(--muted); font-size:12px; margin:7px 0 }} .wave-history b {{ color:var(--text) }}
.view {{ margin-top:8px; font-weight:700 }} .evidence {{ color:var(--muted); font-size:13px }}
.experiment {{ display:grid; grid-template-columns:repeat(3,1fr); gap:12px }}
.experiment div {{ background:#111; border-radius:7px; padding:14px }} .experiment b {{ display:block; font-size:24px }}
.experiment span {{ color:var(--muted); font-size:13px }}
table {{ width:100%; border-collapse:collapse }} th,td {{ text-align:left; padding:9px; border-bottom:1px solid var(--line) }} th {{ color:var(--green); font-size:12px; letter-spacing:.25px }}
.note {{ color:var(--muted); font-size:13px }} @media(max-width:900px) {{
  .grid,.experiment,.detail-title,.metrics {{ grid-template-columns:1fr 1fr }}
  .decision-board {{ grid-template-columns:1fr 1fr }} .wait-column {{ grid-column:1 / -1 }}
  .holding-row {{ grid-template-columns:80px 1fr; gap:10px }}
  .board-action {{ display:none }} .board-basics {{ grid-column:1 / -1; margin-top:3px }}
}} @media(max-width:600px) {{
  main {{ padding:24px 12px 60px }} .grid,.experiment,.detail-title,.metrics {{ grid-template-columns:1fr }}
  .decision-board {{ grid-template-columns:1fr }} .wait-column {{ grid-column:auto }}
  .board-intro {{ align-items:start; flex-direction:column }} .holding-row {{ grid-template-columns:70px 1fr }}
  .board-basics {{ gap:8px }} .drawer {{ max-width:none; padding:14px; width:100vw }} .evidence-hero {{ grid-template-columns:92px 1fr }} .probability-ring {{ height:88px; width:88px }} .probability-ring b {{ font-size:22px }}
}}
</style>
</head>
<body><main>
<h1>{html.escape(title)}</h1>
<p class="sub">Read-only decision support · {html.escape(model_label)} · generated {html.escape(generated)}</p>
<nav class="tabs" role="tablist" aria-label="Dashboard sections">
  <button type="button" class="tab-button active" data-tab-target="portfolio" role="tab" aria-selected="true">Portfolio</button>
  <button type="button" class="tab-button" data-tab-target="research" role="tab" aria-selected="false">Research</button>
  <button type="button" class="tab-button" data-tab-target="health" role="tab" aria-selected="false">Health &amp; Risk</button>
</nav>
<section id="tab-portfolio" class="tab-view active" role="tabpanel">
<div class="board-intro"><div><h2>Priority Board</h2><p>Robust directional events first · highest probability at the top · click any row for details</p></div>
<p>WAIT is folded by default. Portfolio actions remain in the detail panel.</p></div>
<section class="portfolio-board">{prioritized_board}</section>
</section>
<section id="tab-research" class="tab-view" role="tabpanel" hidden>
<section class="panel"><h2>Displayed Direction Forecast Validation</h2>
<table><thead><tr><th>Version</th><th>Direction</th><th>Horizon</th><th>Episodes</th><th>Matured</th><th>Pending</th><th>Displayed rate</th><th>Directional success</th><th>Brier score</th></tr></thead>
<tbody>{direction_validation_rows}</tbody></table>
<p class="note">Every displayed BUY, SELL, and WAIT is retained in an immutable ledger. Daily repeats are de-duplicated into episodes. WAIT is audited for coverage but has no invented directional success or Brier score.</p></section>
<section class="panel"><h2>All-Decision Forward Evidence</h2>
<table><thead><tr><th>Decision</th><th>Horizon</th><th>Matured sample</th><th>Positive return</th><th>Mean excess return</th><th>Directional success</th></tr></thead>
<tbody>{decision_evidence_rows}</tbody></table>
<p class="note">Includes HOLD and ordinary REVIEW decisions from the append-only daily ledger. HOLD is evaluated as remaining long; REVIEW preserves raw and excess outcomes without inventing directional success; DATA REVIEW is excluded from investment-performance claims.</p></section>
<section class="panel"><h2>Current Wave Analog Ranking</h2>
<table><thead><tr><th>Symbol</th><th>Direction gate</th><th>Relative evidence</th><th>Current wave</th><th>Horizon</th><th>Beat SPY (95% CI)</th><th>Cross-stock breadth (95% CI)</th><th>Median return</th><th>Mean upside / downside</th><th>Leave-one-symbol-out</th><th>Evidence · sample</th></tr></thead>
<tbody>{current_wave_rows}</tbody></table>
<p class="note">Ranks current holdings by the conservative lower bound of the best-supported historical wave analog. “Favorable” or “caution” requires pooled and per-symbol breadth intervals to agree, at least 10 observations across eight symbols, and no symbol above 25% of the sample. This is a research-priority view, not a buy/sell instruction.</p></section>
<section class="panel"><h2>Historical Wave Experiment</h2>
<table><thead><tr><th>Wave regime</th><th>Horizon</th><th>Direction gate</th><th>Positive</th><th>Absolute breadth (95% CI)</th><th>Beat SPY (95% CI)</th><th>Relative breadth (95% CI)</th><th>Median return</th><th>Mean max upside</th><th>Mean max downside</th><th>Leave-one-symbol-out</th><th>Evidence · sample</th></tr></thead>
<tbody>{wave_experiment_rows}</tbody></table>
<p class="note">Cross-stock breadth is the share of contributing symbols with positive mean excess return. Each symbol uses causal snapshots and non-overlapping windows within each horizon. Small samples remain visible. This is exploratory in-sample evidence, not a promoted prediction model.</p></section>
<section class="panel"><h2>Conditional Wave Precision Audit</h2>
<table><thead><tr><th>Relative evidence</th><th>Direction gate</th><th>Wave regime</th><th>Horizon</th><th>Wave age</th><th>Move magnitude</th><th>Beat SPY (95% CI)</th><th>Cross-stock breadth (95% CI)</th><th>Leave-one-symbol-out</th><th>Evidence · sample</th></tr></thead>
<tbody>{conditional_wave_rows}</tbody></table>
<p class="note">Age buckets are predeclared as early (≤10 sessions), mature (11–25), and extended (&gt;25). Move magnitude is normalized by each signal's reversal threshold: developing (&lt;1.5×), established (1.5–3×), and extended (&gt;3×). A conditional view can replace its broad regime analog only when the same strict pooled, cross-stock, and concentration gates pass; otherwise the dashboard explicitly refuses the extra precision.</p></section>
<section class="panel"><h2>Live Structural Wave Evidence</h2>
<table><thead><tr><th>Wave regime</th><th>Horizon</th><th>Positive rate</th><th>Matured sample</th><th>Mean return</th></tr></thead>
<tbody>{wave_evidence_rows}</tbody></table>
<p class="note">Wave regimes use confirmed pivots and are evaluated over 21/63/126 sessions. Exact tops and bottoms cannot be known in advance.</p></section>
<section class="panel"><h2>Supporting K-line Evidence</h2>
<table><thead><tr><th>Regime</th><th>Horizon</th><th>Positive rate</th><th>Matured sample</th><th>Mean return</th></tr></thead>
<tbody>{kline_evidence_rows}</tbody></table>
<p class="note">Daily K-line regimes are supporting observations, not day-trading instructions.</p></section>
<section class="panel"><h2>Signal Evidence Ranked by Win Rate</h2>
<table><thead><tr><th>Signal</th><th>Horizon</th><th>Directional win rate</th><th>Matured sample</th><th>Mean directional return</th></tr></thead>
<tbody>{evidence_rows}</tbody></table>
<p class="note">Win rate is ranked only from matured forward outcomes. Small samples are shown, never hidden.</p></section>
</section>
<section id="tab-health" class="tab-view" role="tabpanel" hidden>
{model_health_panel}
{price_health_panel}
<section class="grid">
  <div class="stat"><b>{diagnostic["symbols"]}</b><span>Holdings monitored</span></div>
  <div class="stat"><b>{actions.get("TRIM_REVIEW", 0)}</b><span>Trim reviews</span></div>
  <div class="stat"><b>{actions.get("REVIEW", 0)}</b><span>Reviews</span></div>
  <div class="stat"><b>{actions.get("DATA_REVIEW", 0)}</b><span>Data reviews</span></div>
  <div class="stat"><b class="warning">{diagnostic["actionable_rate"]:.0%}</b><span>Action-review rate</span></div>
</section>
<section class="panel"><h2>Model Health</h2>
<p>The current model flags <b>{diagnostic["actionable_rate"]:.0%}</b> of monitored holdings for action review.
{"This remains an alert-fatigue warning and requires outcome validation before promotion." if diagnostic["alert_fatigue_risk"] else "Current alert burden is within the configured diagnostic threshold."}</p>
<p><b>{diagnostic["data_review_rate"]:.0%}</b> of holdings require data review.
{"Missing data is a major confidence bottleneck for buy/add decisions." if diagnostic["data_quality_burden"] else "Current data-review burden is within the diagnostic threshold."}</p>
<p>Structural wave evidence targets multi-week to multi-month decisions. Daily K-line evidence is supporting context only and is available for <b>{kline_ready} of {diagnostic["symbols"]}</b> monitored holdings.</p>
<p class="note">Signals are prompts for research, not predictions or trade instructions. No orders are placed.</p></section>
{comparison_html}
{coverage_html}
<section class="panel"><h2>Portfolio Risk Alerts</h2><ul>{risk_items}</ul></section>
</section>
</main>
<div class="drawer-backdrop" data-close-drawer></div>
<aside id="holding-drawer" class="drawer" aria-hidden="true" aria-label="Holding details">
  <button type="button" class="drawer-close" data-close-drawer>Close</button>
  {''.join(detail_panels)}
</aside>
<script>
const tabButtons = [...document.querySelectorAll("[data-tab-target]")];
const tabViews = [...document.querySelectorAll(".tab-view")];
tabButtons.forEach((button) => button.addEventListener("click", () => {{
  const target = button.dataset.tabTarget;
  tabButtons.forEach((item) => {{
    const active = item === button;
    item.classList.toggle("active", active);
    item.setAttribute("aria-selected", String(active));
  }});
  tabViews.forEach((view) => {{
    const active = view.id === `tab-${{target}}`;
    view.classList.toggle("active", active);
    view.hidden = !active;
  }});
}}));

const drawer = document.getElementById("holding-drawer");
const backdrop = document.querySelector(".drawer-backdrop");
const detailPanels = [...document.querySelectorAll(".holding-detail")];
const closeDrawer = () => {{
  drawer.classList.remove("open");
  drawer.setAttribute("aria-hidden", "true");
  backdrop.classList.remove("open");
  detailPanels.forEach((panel) => panel.hidden = true);
}};
document.querySelectorAll("[data-detail-target]").forEach((button) => button.addEventListener("click", () => {{
  detailPanels.forEach((panel) => panel.hidden = panel.id !== button.dataset.detailTarget);
  drawer.classList.add("open");
  drawer.setAttribute("aria-hidden", "false");
  backdrop.classList.add("open");
  drawer.scrollTop = 0;
}}));
document.querySelectorAll("[data-close-drawer]").forEach((button) => button.addEventListener("click", closeDrawer));
document.addEventListener("keydown", (event) => {{
  if (event.key === "Escape") closeDrawer();
}});
</script>
</body></html>"""


def write_dashboard(content: str, path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content)
