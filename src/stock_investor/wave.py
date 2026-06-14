from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

from .data import Price


WAVE_FEATURE_VERSION = "wave-v1"
WAVE_EXPERIMENT_VERSION = "wave-walk-forward-v1"
WAVE_CONDITIONAL_VERSION = "wave-conditional-v1"
WAVE_DIRECTION_FORECAST_VERSION = "wave-direction-v1"
WAVE_OUTCOME_WINDOWS = (21, 63, 126)
MIN_WAVE_HISTORY = 126
MIN_REVERSAL = 0.08
MIN_ROBUST_OBSERVATIONS = 10
MIN_ROBUST_SYMBOLS = 8
MAX_ROBUST_SYMBOL_SHARE = 0.25


@dataclass(frozen=True)
class WaveSignals:
    symbol: str
    latest_date: str
    latest_close: float
    direction: str
    regime: str
    reversal_threshold: float
    pivot_count: int
    last_pivot_type: str | None
    last_pivot_date: str | None
    last_pivot_price: float | None
    wave_age_sessions: int | None
    active_wave_return: float | None
    support: float | None
    resistance: float | None
    support_zone_low: float | None
    support_zone_high: float | None
    resistance_zone_low: float | None
    resistance_zone_high: float | None
    distance_to_support: float | None
    distance_to_resistance: float | None
    structural_range_position: float | None


def _wilson_interval(successes: int, observations: int) -> tuple[float | None, float | None]:
    if not observations:
        return None, None
    z = 1.96
    rate = successes / observations
    denominator = 1 + z * z / observations
    center = (rate + z * z / (2 * observations)) / denominator
    margin = (
        z
        * (
            rate * (1 - rate) / observations
            + z * z / (4 * observations * observations)
        )
        ** 0.5
        / denominator
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def classify_wave_walk_forward_evidence(row: dict) -> str:
    if (
        int(row.get("observations", 0)) < MIN_ROBUST_OBSERVATIONS
        or int(row.get("benchmark_symbols", row.get("symbols", 0)))
        < MIN_ROBUST_SYMBOLS
        or float(row.get("top_symbol_observation_share") or 1)
        > MAX_ROBUST_SYMBOL_SHARE
    ):
        return "INCONCLUSIVE"
    pooled_low = row.get("beat_benchmark_ci_low")
    pooled_high = row.get("beat_benchmark_ci_high")
    breadth_low = row.get("symbol_positive_excess_ci_low")
    breadth_high = row.get("symbol_positive_excess_ci_high")
    if (
        pooled_low is not None
        and breadth_low is not None
        and float(pooled_low) > 0.5
        and float(breadth_low) > 0.5
    ):
        return "FAVORABLE"
    if (
        pooled_high is not None
        and breadth_high is not None
        and float(pooled_high) < 0.5
        and float(breadth_high) < 0.5
    ):
        return "CAUTION"
    return "INCONCLUSIVE"


def classify_wave_directional_evidence(row: dict) -> str:
    """Classify absolute direction only when pooled and cross-stock evidence agree."""
    if (
        int(row.get("observations", 0)) < MIN_ROBUST_OBSERVATIONS
        or int(row.get("directional_symbols", row.get("symbols", 0)))
        < MIN_ROBUST_SYMBOLS
        or float(row.get("top_symbol_return_observation_share") or 1)
        > MAX_ROBUST_SYMBOL_SHARE
    ):
        return "WAIT"
    pooled_low = row.get("positive_rate_ci_low")
    pooled_high = row.get("positive_rate_ci_high")
    breadth_low = row.get("symbol_positive_return_ci_low")
    breadth_high = row.get("symbol_positive_return_ci_high")
    if (
        pooled_low is not None
        and breadth_low is not None
        and float(pooled_low) > 0.5
        and float(breadth_low) > 0.5
    ):
        return "BUY"
    if (
        pooled_high is not None
        and breadth_high is not None
        and float(pooled_high) < 0.5
        and float(breadth_high) < 0.5
    ):
        return "SELL"
    return "WAIT"


def wave_age_bucket(wave_age_sessions: int | None) -> str | None:
    if wave_age_sessions is None:
        return None
    if wave_age_sessions <= 10:
        return "EARLY"
    if wave_age_sessions <= 25:
        return "MATURE"
    return "EXTENDED"


def wave_magnitude_bucket(
    active_wave_return: float | None, reversal_threshold: float | None
) -> tuple[float | None, str | None]:
    if active_wave_return is None or not reversal_threshold or reversal_threshold <= 0:
        return None, None
    multiple = abs(active_wave_return) / reversal_threshold
    if multiple < 1.5:
        return multiple, "DEVELOPING"
    if multiple <= 3:
        return multiple, "ESTABLISHED"
    return multiple, "EXTENDED"


def _atr_threshold(history: list[Price]) -> float:
    recent = history[-21:]
    ranges = []
    for previous, current in zip(recent[:-1], recent[1:]):
        if current.high is None or current.low is None:
            continue
        ranges.append(
            max(
                float(current.high) - float(current.low),
                abs(float(current.high) - previous.close),
                abs(float(current.low) - previous.close),
            )
            / current.close
        )
    return max(MIN_REVERSAL, 2 * sum(ranges) / len(ranges)) if ranges else MIN_REVERSAL


def _confirmed_pivots(history: list[Price], threshold: float) -> list[tuple[int, str, float]]:
    """Causal percent-reversal pivots; a pivot exists only after confirmation."""
    if not history:
        return []
    direction = 0
    extreme_index = 0
    extreme_price = history[0].close
    low_index = high_index = 0
    low_price = high_price = history[0].close
    pivots: list[tuple[int, str, float]] = []
    for index, item in enumerate(history[1:], start=1):
        price = item.close
        if direction == 0:
            if price < low_price:
                low_index, low_price = index, price
            if price > high_price:
                high_index, high_price = index, price
            if high_price / low_price - 1 >= threshold and low_index < high_index:
                pivots.append((low_index, "LOW", low_price))
                direction = 1
                extreme_index, extreme_price = high_index, high_price
            elif high_price / low_price - 1 >= threshold and high_index < low_index:
                pivots.append((high_index, "HIGH", high_price))
                direction = -1
                extreme_index, extreme_price = low_index, low_price
        elif direction == 1:
            if price >= extreme_price:
                extreme_index, extreme_price = index, price
            elif price / extreme_price - 1 <= -threshold:
                pivots.append((extreme_index, "HIGH", extreme_price))
                direction = -1
                extreme_index, extreme_price = index, price
        else:
            if price <= extreme_price:
                extreme_index, extreme_price = index, price
            elif price / extreme_price - 1 >= threshold:
                pivots.append((extreme_index, "LOW", extreme_price))
                direction = 1
                extreme_index, extreme_price = index, price
    return pivots


def calculate_wave(symbol: str, history: list[Price]) -> WaveSignals:
    if len(history) < MIN_WAVE_HISTORY:
        raise ValueError(
            f"need at least {MIN_WAVE_HISTORY} daily prices, received {len(history)}"
        )
    recent = history[-252:]
    threshold = _atr_threshold(recent)
    pivots = _confirmed_pivots(recent, threshold)
    latest = recent[-1]
    last = pivots[-1] if pivots else None
    last_low = next((pivot for pivot in reversed(pivots) if pivot[1] == "LOW"), None)
    last_high = next((pivot for pivot in reversed(pivots) if pivot[1] == "HIGH"), None)
    support = last_low[2] if last_low else None
    resistance = last_high[2] if last_high else None
    range_position = (
        (latest.close - support) / (resistance - support)
        if support is not None and resistance is not None and resistance > support
        else None
    )
    direction = (
        "ADVANCING"
        if last and last[1] == "LOW"
        else "DECLINING" if last and last[1] == "HIGH" else "UNCONFIRMED"
    )
    distance_support = latest.close / support - 1 if support else None
    distance_resistance = latest.close / resistance - 1 if resistance else None
    zone_width = min(0.08, threshold / 2)
    if direction == "ADVANCING" and distance_resistance is not None and distance_resistance >= zone_width:
        regime = "Advancing above structural resistance"
    elif direction == "ADVANCING" and distance_resistance is not None and distance_resistance >= -zone_width:
        regime = "Advancing near structural resistance"
    elif direction == "ADVANCING":
        regime = "Advancing wave"
    elif direction == "DECLINING" and distance_support is not None and distance_support <= -zone_width:
        regime = "Declining below structural support"
    elif direction == "DECLINING" and distance_support is not None and distance_support <= zone_width:
        regime = "Declining near structural support"
    elif direction == "DECLINING":
        regime = "Declining wave"
    else:
        regime = "Wave unconfirmed"
    return WaveSignals(
        symbol=symbol,
        latest_date=latest.date.isoformat(),
        latest_close=latest.close,
        direction=direction,
        regime=regime,
        reversal_threshold=threshold,
        pivot_count=len(pivots),
        last_pivot_type=last[1] if last else None,
        last_pivot_date=recent[last[0]].date.isoformat() if last else None,
        last_pivot_price=last[2] if last else None,
        wave_age_sessions=len(recent) - 1 - last[0] if last else None,
        active_wave_return=latest.close / last[2] - 1 if last else None,
        support=support,
        resistance=resistance,
        support_zone_low=support * (1 - zone_width) if support else None,
        support_zone_high=support * (1 + zone_width) if support else None,
        resistance_zone_low=resistance * (1 - zone_width) if resistance else None,
        resistance_zone_high=resistance * (1 + zone_width) if resistance else None,
        distance_to_support=distance_support,
        distance_to_resistance=distance_resistance,
        structural_range_position=range_position,
    )


def calculate_waves(prices: dict[str, list[Price]]) -> dict[str, WaveSignals]:
    waves = {}
    for symbol, history in prices.items():
        try:
            waves[symbol] = calculate_wave(symbol, history)
        except ValueError:
            continue
    return waves


def write_wave_snapshot(waves: dict[str, WaveSignals], path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "feature_version": WAVE_FEATURE_VERSION,
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "waves": {symbol: asdict(wave) for symbol, wave in sorted(waves.items())},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def append_wave_history(waves: dict[str, WaveSignals], path: str | Path) -> int:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    existing = set()
    if output.exists():
        existing = {
            json.loads(line).get("event_key")
            for line in output.read_text().splitlines()
            if line.strip()
        }
    timestamp = datetime.now(timezone.utc).isoformat()
    written = 0
    with output.open("a") as handle:
        for symbol, wave in sorted(waves.items()):
            event_key = f"{WAVE_FEATURE_VERSION}|{symbol}|{wave.latest_date}"
            if event_key in existing:
                continue
            record = {
                "event_key": event_key,
                "feature_version": WAVE_FEATURE_VERSION,
                "symbol": symbol,
                "signal_date": wave.latest_date,
                "entry_close": wave.latest_close,
                "regime": wave.regime,
                "features": asdict(wave),
                "observed_at": timestamp,
            }
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            existing.add(event_key)
            written += 1
    return written


def load_wave_history(path: str | Path) -> list[dict]:
    source = Path(path)
    if not source.exists():
        return []
    return [json.loads(line) for line in source.read_text().splitlines() if line.strip()]


def evaluate_wave_history(records: list[dict], prices: dict[str, list[Price]]) -> list[dict]:
    outcomes = []
    for record in records:
        future = [
            item
            for item in prices.get(record["symbol"], [])
            if item.date.isoformat() > record["signal_date"]
        ]
        returns = {
            f"{window}d": (
                future[window - 1].close / float(record["entry_close"]) - 1
                if len(future) >= window
                else None
            )
            for window in WAVE_OUTCOME_WINDOWS
        }
        outcomes.append(
            {
                **record,
                "returns": returns,
                "status": (
                    "MATURED"
                    if returns[f"{WAVE_OUTCOME_WINDOWS[-1]}d"] is not None
                    else "PENDING"
                ),
            }
        )
    return outcomes


def build_wave_scorecard(outcomes: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for outcome in outcomes:
        for horizon, value in outcome["returns"].items():
            if value is not None:
                groups[(outcome["feature_version"], outcome["regime"], horizon)].append(value)
    return [
        {
            "feature_version": version,
            "regime": regime,
            "horizon": horizon,
            "observations": len(values),
            "mean_return": sum(values) / len(values),
            "positive_rate": sum(value > 0 for value in values) / len(values),
        }
        for (version, regime, horizon), values in sorted(groups.items())
    ]


def build_wave_walk_forward_outcomes(
    prices: dict[str, list[Price]],
    benchmark_symbol: str | None = "SPY",
) -> list[dict]:
    """Replay causal wave snapshots with non-overlapping windows per horizon."""
    benchmark = {
        item.date: item.close
        for item in prices.get(benchmark_symbol, [])
    } if benchmark_symbol else {}
    outcomes = []
    for symbol, history in sorted(prices.items()):
        if symbol == benchmark_symbol:
            continue
        for horizon in WAVE_OUTCOME_WINDOWS:
            for signal_index in range(
                MIN_WAVE_HISTORY - 1,
                len(history) - horizon,
                horizon,
            ):
                signal = calculate_wave(symbol, history[: signal_index + 1])
                forward = history[signal_index + 1 : signal_index + 1 + horizon]
                entry_close = signal.latest_close
                end = forward[-1]
                forward_return = end.close / entry_close - 1
                benchmark_return = (
                    benchmark[end.date] / benchmark[history[signal_index].date] - 1
                    if end.date in benchmark and history[signal_index].date in benchmark
                    else None
                )
                active_wave_multiple, magnitude_bucket = wave_magnitude_bucket(
                    signal.active_wave_return, signal.reversal_threshold
                )
                outcomes.append(
                    {
                        "experiment_version": WAVE_EXPERIMENT_VERSION,
                        "feature_version": WAVE_FEATURE_VERSION,
                        "symbol": symbol,
                        "signal_date": signal.latest_date,
                        "end_date": end.date.isoformat(),
                        "horizon": f"{horizon}d",
                        "entry_close": entry_close,
                        "regime": signal.regime,
                        "direction": signal.direction,
                        "wave_age_sessions": signal.wave_age_sessions,
                        "wave_age_bucket": wave_age_bucket(signal.wave_age_sessions),
                        "active_wave_return": signal.active_wave_return,
                        "active_wave_multiple": active_wave_multiple,
                        "wave_magnitude_bucket": magnitude_bucket,
                        "reversal_threshold": signal.reversal_threshold,
                        "forward_return": forward_return,
                        "benchmark_return": benchmark_return,
                        "excess_return": (
                            forward_return - benchmark_return
                            if benchmark_return is not None
                            else None
                        ),
                        "max_gain": max(item.close / entry_close - 1 for item in forward),
                        "max_loss": min(item.close / entry_close - 1 for item in forward),
                        "non_overlapping_within_symbol_horizon": True,
                    }
                )
    return outcomes


def _walk_forward_scorecard_row(values: list[dict], dimensions: dict) -> dict:
    returns = [float(item["forward_return"]) for item in values]
    excess = [
        float(item["excess_return"])
        for item in values
        if item.get("excess_return") is not None
    ]
    max_gains = [float(item["max_gain"]) for item in values]
    max_losses = [float(item["max_loss"]) for item in values]
    positive_count = sum(value > 0 for value in returns)
    beat_count = sum(value > 0 for value in excess)
    positive_interval = _wilson_interval(positive_count, len(returns))
    beat_interval = _wilson_interval(beat_count, len(excess))
    symbol_groups = defaultdict(list)
    symbol_return_groups = defaultdict(list)
    for item in values:
        symbol_return_groups[item["symbol"]].append(float(item["forward_return"]))
        if item.get("excess_return") is not None:
            symbol_groups[item["symbol"]].append(float(item["excess_return"]))
    symbol_mean_return = {
        symbol: sum(symbol_values) / len(symbol_values)
        for symbol, symbol_values in symbol_return_groups.items()
    }
    symbol_mean_excess = {
        symbol: sum(symbol_values) / len(symbol_values)
        for symbol, symbol_values in symbol_groups.items()
    }
    positive_excess_symbols = sum(value > 0 for value in symbol_mean_excess.values())
    positive_return_symbols = sum(value > 0 for value in symbol_mean_return.values())
    symbol_return_breadth_interval = _wilson_interval(
        positive_return_symbols, len(symbol_mean_return)
    )
    symbol_breadth_interval = _wilson_interval(
        positive_excess_symbols, len(symbol_mean_excess)
    )
    max_symbol_observations = max(
        (len(symbol_values) for symbol_values in symbol_groups.values()),
        default=0,
    )
    max_symbol_return_observations = max(
        (len(symbol_values) for symbol_values in symbol_return_groups.values()),
        default=0,
    )
    row = {
        "experiment_version": WAVE_EXPERIMENT_VERSION,
        "feature_version": WAVE_FEATURE_VERSION,
        **dimensions,
        "observations": len(values),
        "symbols": len({item["symbol"] for item in values}),
        "directional_symbols": len(symbol_mean_return),
        "symbols_with_positive_mean_return": positive_return_symbols,
        "symbol_positive_return_rate": (
            positive_return_symbols / len(symbol_mean_return)
            if symbol_mean_return
            else None
        ),
        "symbol_positive_return_ci_low": symbol_return_breadth_interval[0],
        "symbol_positive_return_ci_high": symbol_return_breadth_interval[1],
        "top_symbol_return_observation_share": (
            max_symbol_return_observations / len(returns) if returns else None
        ),
        "benchmark_symbols": len(symbol_mean_excess),
        "symbols_with_positive_mean_excess": positive_excess_symbols,
        "symbol_positive_excess_rate": (
            positive_excess_symbols / len(symbol_mean_excess)
            if symbol_mean_excess
            else None
        ),
        "symbol_positive_excess_ci_low": symbol_breadth_interval[0],
        "symbol_positive_excess_ci_high": symbol_breadth_interval[1],
        "max_symbol_observations": max_symbol_observations,
        "top_symbol_observation_share": (
            max_symbol_observations / len(excess) if excess else None
        ),
        "positive_rate": positive_count / len(returns),
        "positive_rate_ci_low": positive_interval[0],
        "positive_rate_ci_high": positive_interval[1],
        "beat_benchmark_rate": beat_count / len(excess) if excess else None,
        "beat_benchmark_ci_low": beat_interval[0],
        "beat_benchmark_ci_high": beat_interval[1],
        "mean_return": sum(returns) / len(returns),
        "median_return": median(returns),
        "mean_excess_return": sum(excess) / len(excess) if excess else None,
        "median_excess_return": median(excess) if excess else None,
        "mean_max_gain": sum(max_gains) / len(max_gains),
        "mean_max_loss": sum(max_losses) / len(max_losses),
    }
    row["evidence_classification"] = classify_wave_walk_forward_evidence(row)
    row["directional_evidence_classification"] = classify_wave_directional_evidence(row)
    return row


def build_wave_walk_forward_scorecard(outcomes: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for outcome in outcomes:
        groups[(outcome["regime"], outcome["horizon"])].append(outcome)
    return [
        _walk_forward_scorecard_row(
            values,
            {"regime": regime, "horizon": horizon},
        )
        for (regime, horizon), values in sorted(groups.items())
    ]


def build_wave_conditional_scorecard(outcomes: list[dict]) -> list[dict]:
    """Audit predeclared age/magnitude cells; strict gates refuse thin precision."""
    groups = defaultdict(list)
    for outcome in outcomes:
        age_bucket = outcome.get("wave_age_bucket") or wave_age_bucket(
            outcome.get("wave_age_sessions")
        )
        _, magnitude_bucket = wave_magnitude_bucket(
            outcome.get("active_wave_return"), outcome.get("reversal_threshold")
        )
        magnitude_bucket = outcome.get("wave_magnitude_bucket") or magnitude_bucket
        if age_bucket and magnitude_bucket:
            groups[
                (outcome["regime"], outcome["horizon"], age_bucket, magnitude_bucket)
            ].append(outcome)
    return [
        _walk_forward_scorecard_row(
            values,
            {
                "conditional_version": WAVE_CONDITIONAL_VERSION,
                "regime": regime,
                "horizon": horizon,
                "wave_age_bucket": age_bucket,
                "wave_magnitude_bucket": magnitude_bucket,
            },
        )
        for (regime, horizon, age_bucket, magnitude_bucket), values in sorted(
            groups.items()
        )
    ]


def _wave_value(wave: WaveSignals | dict, key: str) -> object:
    return getattr(wave, key) if isinstance(wave, WaveSignals) else wave.get(key)


def select_live_wave_evidence(
    wave: WaveSignals | dict,
    broad_scorecard: list[dict],
    conditional_scorecard: list[dict],
) -> tuple[dict | None, str]:
    """Select the same evidence layer used by the live directional board."""
    broad_lookup = {
        (row.get("regime"), row.get("horizon")): row for row in broad_scorecard
    }
    regime = _wave_value(wave, "regime")
    candidates = [
        broad_lookup.get((regime, horizon)) for horizon in ("63d", "126d", "21d")
    ]
    broad = next(
        (
            row
            for row in candidates
            if row and int(row.get("observations", 0)) >= MIN_ROBUST_OBSERVATIONS
        ),
        None,
    ) or next((row for row in candidates if row), None)
    if not broad:
        return None, "NONE"
    _, magnitude_bucket = wave_magnitude_bucket(
        _wave_value(wave, "active_wave_return"),
        _wave_value(wave, "reversal_threshold"),
    )
    conditional_lookup = {
        (
            row.get("regime"),
            row.get("horizon"),
            row.get("wave_age_bucket"),
            row.get("wave_magnitude_bucket"),
        ): row
        for row in conditional_scorecard
    }
    conditional = conditional_lookup.get(
        (
            regime,
            broad.get("horizon"),
            wave_age_bucket(_wave_value(wave, "wave_age_sessions")),
            magnitude_bucket,
        )
    )
    if conditional and (
        classify_wave_directional_evidence(conditional) != "WAIT"
        or classify_wave_walk_forward_evidence(conditional) != "INCONCLUSIVE"
    ):
        return conditional, "CONDITIONAL"
    return broad, "BROAD"


def build_directional_forecasts(
    waves: dict[str, WaveSignals],
    held_symbols: set[str],
    broad_scorecard: list[dict],
    conditional_scorecard: list[dict],
    prices: dict[str, list[Price]] | None = None,
) -> list[dict]:
    forecasts = []
    for symbol in sorted(held_symbols):
        wave = waves.get(symbol)
        if not wave:
            history = (prices or {}).get(symbol, [])
            if not history:
                continue
            latest = history[-1]
            forecasts.append(
                {
                    "forecast_id": (
                        f"{WAVE_DIRECTION_FORECAST_VERSION}|{symbol}|"
                        f"{latest.date.isoformat()}"
                    ),
                    "forecast_version": WAVE_DIRECTION_FORECAST_VERSION,
                    "symbol": symbol,
                    "signal_date": latest.date.isoformat(),
                    "entry_close": latest.close,
                    "direction": "WAIT",
                    "probability": None,
                    "horizon": None,
                    "regime": "Wave evidence unavailable",
                    "evidence_source": "NONE",
                    "observations": 0,
                    "directional_symbols": 0,
                    "wave_age_bucket": None,
                    "wave_magnitude_bucket": None,
                }
            )
            continue
        evidence, evidence_source = select_live_wave_evidence(
            wave, broad_scorecard, conditional_scorecard
        )
        direction = (
            classify_wave_directional_evidence(evidence) if evidence else "WAIT"
        )
        positive_rate = evidence.get("positive_rate") if evidence else None
        probability = (
            float(positive_rate)
            if direction == "BUY" and positive_rate is not None
            else (
                1 - float(positive_rate)
                if direction == "SELL" and positive_rate is not None
                else None
            )
        )
        forecast_id = (
            f"{WAVE_DIRECTION_FORECAST_VERSION}|{symbol}|{wave.latest_date}"
        )
        forecasts.append(
            {
                "forecast_id": forecast_id,
                "forecast_version": WAVE_DIRECTION_FORECAST_VERSION,
                "symbol": symbol,
                "signal_date": wave.latest_date,
                "entry_close": wave.latest_close,
                "direction": direction,
                "probability": probability,
                "horizon": evidence.get("horizon") if evidence else None,
                "regime": wave.regime,
                "evidence_source": evidence_source,
                "observations": int(evidence.get("observations", 0)) if evidence else 0,
                "directional_symbols": (
                    int(evidence.get("directional_symbols", 0)) if evidence else 0
                ),
                "wave_age_bucket": wave_age_bucket(wave.wave_age_sessions),
                "wave_magnitude_bucket": wave_magnitude_bucket(
                    wave.active_wave_return, wave.reversal_threshold
                )[1],
            }
        )
    return forecasts


def append_directional_forecast_history(
    forecasts: list[dict], path: str | Path
) -> int:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    existing = set()
    if output.exists():
        existing = {
            json.loads(line).get("forecast_id")
            for line in output.read_text().splitlines()
            if line.strip()
        }
    observed_at = datetime.now(timezone.utc).isoformat()
    written = 0
    with output.open("a") as handle:
        for forecast in forecasts:
            if forecast["forecast_id"] in existing:
                continue
            handle.write(
                json.dumps(
                    {**forecast, "observed_at": observed_at}, sort_keys=True
                )
                + "\n"
            )
            existing.add(forecast["forecast_id"])
            written += 1
    return written


def load_directional_forecast_history(path: str | Path) -> list[dict]:
    source = Path(path)
    if not source.exists():
        return []
    return [
        json.loads(line)
        for line in source.read_text().splitlines()
        if line.strip()
    ]
