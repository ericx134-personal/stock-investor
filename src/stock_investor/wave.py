from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import median

from .data import Price
from .io import atomic_write_text


WAVE_FEATURE_VERSION = "wave-v1"
WAVE_EXPERIMENT_VERSION = "wave-walk-forward-v1"
WAVE_CONDITIONAL_VERSION = "wave-conditional-v2"
WAVE_DIRECTION_FORECAST_VERSION = "wave-direction-v4"
PRICE_ZONE_REPLAY_VERSION = "price-zone-replay-v1"
DIRECTION_RATE_COMPARISON_VERSION = "direction-rate-comparison-v1"
WAVE_TIME_DECAY_VERSION = "wave-time-decay-v1"
WAVE_EXPANDING_VALIDATION_VERSION = "wave-expanding-validation-v1"
WAVE_OUTCOME_WINDOWS = (21, 63, 126)
PRICE_ZONE_REPLAY_HORIZON = 5
TIME_DECAY_HALF_LIFE_DAYS = 365
MIN_WAVE_HISTORY = 126
MIN_REVERSAL = 0.08
MIN_ROBUST_OBSERVATIONS = 10
MIN_ROBUST_SYMBOLS = 8
MAX_ROBUST_SYMBOL_SHARE = 0.25
PROBABILITY_SHRINKAGE_PRIOR_OBSERVATIONS = 20
PROBABILITY_SHRINKAGE_PRIOR_RATE = 0.5


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
        or row.get("relative_leave_one_out_stable") is False
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
        or row.get("directional_leave_one_out_stable") is False
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


def shrink_direction_probability(
    raw_probability: float | None,
    observations: int | None,
    *,
    prior_observations: int = PROBABILITY_SHRINKAGE_PRIOR_OBSERVATIONS,
    prior_rate: float = PROBABILITY_SHRINKAGE_PRIOR_RATE,
) -> float | None:
    if raw_probability is None or observations is None or observations < 0:
        return None
    if prior_observations < 0 or not 0 <= prior_rate <= 1:
        return None
    if not 0 <= float(raw_probability) <= 1:
        return None
    denominator = observations + prior_observations
    if denominator <= 0:
        return float(raw_probability)
    return (
        float(raw_probability) * observations + prior_rate * prior_observations
    ) / denominator


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


def _bar_low(price: Price) -> float:
    return float(price.low if price.low is not None else price.close)


def _bar_high(price: Price) -> float:
    return float(price.high if price.high is not None else price.close)


def _zone_intersects(price: Price, low: float, high: float) -> bool:
    return _bar_low(price) <= high and _bar_high(price) >= low


def _first_offset(values: list[bool]) -> int | None:
    return next((index + 1 for index, value in enumerate(values) if value), None)


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


def _zone_replay_record(
    wave: WaveSignals,
    zone_label: str,
    low: float | None,
    high: float | None,
    forward: list[Price],
) -> dict | None:
    if low is None or high is None or low <= 0 or high <= 0 or not forward:
        return None
    low, high = sorted((float(low), float(high)))
    current = float(wave.latest_close)
    zone_type = zone_label
    if zone_label == "SELL" and current > high:
        zone_type = "BREAKOUT_RETEST"
    elif zone_label == "BUY" and current < low:
        zone_type = "BREAKDOWN_RETEST"
    touches = [_zone_intersects(item, low, high) for item in forward]
    touch_offset = _first_offset(touches)
    if zone_label == "BUY":
        invalidations = [float(item.close) < low for item in forward]
        favorable = max(_bar_high(item) / current - 1 for item in forward)
        adverse = min(_bar_low(item) / current - 1 for item in forward)
    else:
        invalidations = [float(item.close) > high for item in forward]
        favorable = max(1 - _bar_low(item) / current for item in forward)
        adverse = min(1 - _bar_high(item) / current for item in forward)
    invalidation_offset = _first_offset(invalidations)
    final_return = float(forward[-1].close) / current - 1
    if zone_type == "BREAKOUT_RETEST":
        outcome = (
            "RETEST_HELD"
            if touch_offset is not None and float(forward[-1].close) >= high
            else "NO_RETEST"
            if touch_offset is None
            else "RETEST_FAILED"
        )
    elif zone_type == "BREAKDOWN_RETEST":
        outcome = (
            "RETEST_HELD"
            if touch_offset is not None and float(forward[-1].close) <= low
            else "NO_RETEST"
            if touch_offset is None
            else "RETEST_FAILED"
        )
    elif invalidation_offset is not None and (
        touch_offset is None or invalidation_offset < touch_offset
    ):
        outcome = "INVALIDATED_BEFORE_TOUCH"
    elif touch_offset is not None:
        outcome = "TOUCHED"
    else:
        outcome = "MISSED"
    return {
        "replay_version": PRICE_ZONE_REPLAY_VERSION,
        "symbol": wave.symbol,
        "signal_date": wave.latest_date,
        "entry_close": current,
        "zone_label": zone_label,
        "zone_type": zone_type,
        "zone_low": low,
        "zone_high": high,
        "zone_midpoint": (low + high) / 2,
        "horizon_sessions": len(forward),
        "touch_offset_sessions": touch_offset,
        "invalidation_offset_sessions": invalidation_offset,
        "outcome": outcome,
        "forward_return": final_return,
        "max_favorable_excursion": favorable,
        "max_adverse_excursion": adverse,
        "wave_regime": wave.regime,
        "wave_direction": wave.direction,
        "wave_age_sessions": wave.wave_age_sessions,
        "active_wave_return": wave.active_wave_return,
    }


def build_price_zone_replay(
    prices: dict[str, list[Price]],
    *,
    horizon_sessions: int = PRICE_ZONE_REPLAY_HORIZON,
    min_history: int = MIN_WAVE_HISTORY,
) -> list[dict]:
    """Replay structural price zones using only bars available at each signal date."""
    if horizon_sessions <= 0:
        raise ValueError("horizon_sessions must be positive")
    records = []
    for symbol, history in sorted(prices.items()):
        if len(history) <= min_history + horizon_sessions:
            continue
        for index in range(min_history - 1, len(history) - horizon_sessions):
            try:
                wave = calculate_wave(symbol, history[: index + 1])
            except ValueError:
                continue
            forward = history[index + 1 : index + 1 + horizon_sessions]
            for zone_label, low, high in (
                ("BUY", wave.support_zone_low, wave.support_zone_high),
                ("SELL", wave.resistance_zone_low, wave.resistance_zone_high),
            ):
                record = _zone_replay_record(wave, zone_label, low, high, forward)
                if record:
                    records.append(record)
    return records


def build_price_zone_replay_scorecard(records: list[dict]) -> list[dict]:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for record in records:
        groups[(str(record["zone_type"]), str(record["wave_regime"]))].append(record)
    rows = []
    for (zone_type, regime), values in sorted(groups.items()):
        observations = len(values)
        touched = sum(1 for item in values if item["touch_offset_sessions"] is not None)
        invalidated = sum(
            1 for item in values if item["outcome"] == "INVALIDATED_BEFORE_TOUCH"
        )
        retest_held = sum(1 for item in values if item["outcome"] == "RETEST_HELD")
        rows.append(
            {
                "replay_version": PRICE_ZONE_REPLAY_VERSION,
                "zone_type": zone_type,
                "wave_regime": regime,
                "observations": observations,
                "touch_rate": touched / observations if observations else None,
                "invalidation_rate": (
                    invalidated / observations if observations else None
                ),
                "retest_hold_rate": retest_held / observations if observations else None,
                "mean_forward_return": (
                    sum(float(item["forward_return"]) for item in values) / observations
                    if observations
                    else None
                ),
                "mean_max_favorable_excursion": (
                    sum(float(item["max_favorable_excursion"]) for item in values)
                    / observations
                    if observations
                    else None
                ),
                "mean_max_adverse_excursion": (
                    sum(float(item["max_adverse_excursion"]) for item in values)
                    / observations
                    if observations
                    else None
                ),
            }
        )
    return rows


def write_wave_snapshot(waves: dict[str, WaveSignals], path: str | Path) -> None:
    atomic_write_text(
        json.dumps(
            {
                "feature_version": WAVE_FEATURE_VERSION,
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "waves": {symbol: asdict(wave) for symbol, wave in sorted(waves.items())},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        path,
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


def _walk_forward_scorecard_row(
    values: list[dict], dimensions: dict, include_leave_one_out: bool = True
) -> dict:
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
    if include_leave_one_out:
        directional_classification = row["directional_evidence_classification"]
        relative_classification = row["evidence_classification"]
        leave_one_out_rows = []
        for symbol in sorted({item["symbol"] for item in values}):
            remaining = [item for item in values if item["symbol"] != symbol]
            leave_one_out_rows.append(
                _walk_forward_scorecard_row(remaining, dimensions, False)
                if remaining
                else {
                    "directional_evidence_classification": "WAIT",
                    "evidence_classification": "INCONCLUSIVE",
                }
            )
        directional_matches = sum(
            item["directional_evidence_classification"] == directional_classification
            for item in leave_one_out_rows
        )
        relative_matches = sum(
            item["evidence_classification"] == relative_classification
            for item in leave_one_out_rows
        )
        row.update(
            {
                "directional_pre_leave_one_out_classification": (
                    directional_classification
                ),
                "relative_pre_leave_one_out_classification": relative_classification,
                "leave_one_out_symbols": len(leave_one_out_rows),
                "directional_leave_one_out_matches": directional_matches,
                "directional_leave_one_out_rate": (
                    directional_matches / len(leave_one_out_rows)
                    if leave_one_out_rows
                    else None
                ),
                "directional_leave_one_out_stable": (
                    directional_matches == len(leave_one_out_rows)
                    if leave_one_out_rows
                    else False
                ),
                "relative_leave_one_out_matches": relative_matches,
                "relative_leave_one_out_rate": (
                    relative_matches / len(leave_one_out_rows)
                    if leave_one_out_rows
                    else None
                ),
                "relative_leave_one_out_stable": (
                    relative_matches == len(leave_one_out_rows)
                    if leave_one_out_rows
                    else False
                ),
            }
        )
        row["evidence_classification"] = classify_wave_walk_forward_evidence(row)
        row["directional_evidence_classification"] = (
            classify_wave_directional_evidence(row)
        )
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


def _direction_rate_values(row: dict, direction: str) -> tuple[float | None, float | None]:
    positive_rate = row.get("positive_rate")
    ci_low = row.get("positive_rate_ci_low")
    ci_high = row.get("positive_rate_ci_high")
    if positive_rate is None:
        return None, None
    if direction == "BUY":
        return float(positive_rate), float(ci_low) if ci_low is not None else None
    if direction == "SELL":
        return (
            1 - float(positive_rate),
            1 - float(ci_high) if ci_high is not None else None,
        )
    return None, None


def build_direction_rate_comparison_scorecard(
    broad_scorecard: list[dict],
    conditional_scorecard: list[dict],
) -> list[dict]:
    """Compare raw, Wilson-lower, and shrunk displayed directional rates."""
    rows = []
    for source, scorecard in (
        ("BROAD", broad_scorecard),
        ("CONDITIONAL", conditional_scorecard),
    ):
        for row in scorecard:
            direction = classify_wave_directional_evidence(row)
            if direction == "WAIT":
                continue
            observations = int(row.get("observations", 0))
            raw_probability, wilson_lower_probability = _direction_rate_values(
                row, direction
            )
            shrunk_probability = shrink_direction_probability(
                raw_probability, observations
            )
            rows.append(
                {
                    "comparison_version": DIRECTION_RATE_COMPARISON_VERSION,
                    "source": source,
                    "direction": direction,
                    "horizon": row.get("horizon"),
                    "regime": row.get("regime"),
                    "wave_age_bucket": row.get("wave_age_bucket"),
                    "wave_magnitude_bucket": row.get("wave_magnitude_bucket"),
                    "observations": observations,
                    "directional_symbols": int(row.get("directional_symbols", 0)),
                    "top_symbol_return_observation_share": row.get(
                        "top_symbol_return_observation_share"
                    ),
                    "directional_leave_one_out_stable": row.get(
                        "directional_leave_one_out_stable"
                    ),
                    "raw_probability": raw_probability,
                    "wilson_lower_probability": wilson_lower_probability,
                    "shrunk_probability": shrunk_probability,
                    "shrunk_minus_raw": (
                        shrunk_probability - raw_probability
                        if shrunk_probability is not None
                        and raw_probability is not None
                        else None
                    ),
                    "wilson_lower_minus_raw": (
                        wilson_lower_probability - raw_probability
                        if wilson_lower_probability is not None
                        and raw_probability is not None
                        else None
                    ),
                    "display_policy": "SHRUNK_RATE",
                    "failure_gate": "Do not promote raw rates; Wilson lower bound remains the conservative audit floor.",
                }
            )
    return sorted(
        rows,
        key=lambda item: (
            item["direction"],
            -float(item.get("shrunk_probability") or 0),
            -int(item.get("observations", 0)),
            item.get("source", ""),
            item.get("regime", ""),
        ),
    )


def _time_decay_weight(signal_date: str, latest_date: date, half_life_days: int) -> float:
    if half_life_days <= 0:
        raise ValueError("half_life_days must be positive")
    age_days = max(0, (latest_date - date.fromisoformat(signal_date)).days)
    return 0.5 ** (age_days / half_life_days)


def _weighted_mean(values: list[tuple[float, float]]) -> float | None:
    total_weight = sum(weight for _, weight in values)
    if total_weight <= 0:
        return None
    return sum(value * weight for value, weight in values) / total_weight


def build_wave_time_decay_scorecard(
    outcomes: list[dict],
    *,
    half_life_days: int = TIME_DECAY_HALF_LIFE_DAYS,
) -> list[dict]:
    """Score broad wave regimes with exponentially decayed historical evidence."""
    if half_life_days <= 0:
        raise ValueError("half_life_days must be positive")
    groups = defaultdict(list)
    for outcome in outcomes:
        groups[(outcome["regime"], outcome["horizon"])].append(outcome)
    rows = []
    for (regime, horizon), values in sorted(groups.items()):
        latest = max(date.fromisoformat(item["signal_date"]) for item in values)
        weighted_returns = []
        weighted_positive = []
        weighted_excess = []
        weights_by_symbol = defaultdict(float)
        for item in values:
            weight = _time_decay_weight(item["signal_date"], latest, half_life_days)
            forward_return = float(item["forward_return"])
            weighted_returns.append((forward_return, weight))
            weighted_positive.append((1.0 if forward_return > 0 else 0.0, weight))
            weights_by_symbol[item["symbol"]] += weight
            if item.get("excess_return") is not None:
                weighted_excess.append((float(item["excess_return"]), weight))
        total_weight = sum(weight for _, weight in weighted_returns)
        top_symbol_weight = max(weights_by_symbol.values(), default=0.0)
        rows.append(
            {
                "decay_version": WAVE_TIME_DECAY_VERSION,
                "experiment_version": WAVE_EXPERIMENT_VERSION,
                "feature_version": WAVE_FEATURE_VERSION,
                "regime": regime,
                "horizon": horizon,
                "half_life_days": half_life_days,
                "observations": len(values),
                "weighted_observations": total_weight,
                "symbols": len(weights_by_symbol),
                "top_symbol_weight_share": (
                    top_symbol_weight / total_weight if total_weight else None
                ),
                "latest_signal_date": latest.isoformat(),
                "oldest_signal_date": min(item["signal_date"] for item in values),
                "weighted_positive_rate": _weighted_mean(weighted_positive),
                "weighted_mean_return": _weighted_mean(weighted_returns),
                "weighted_mean_excess_return": _weighted_mean(weighted_excess),
                "status": "EXPERIMENTAL",
                "failure_gate": "Do not replace equal-weight evidence until sealed forward outcomes improve calibration.",
            }
        )
    return rows


def build_wave_expanding_window_validation(
    outcomes: list[dict],
    *,
    min_train_observations: int = MIN_ROBUST_OBSERVATIONS,
    buy_threshold: float = 0.55,
    sell_threshold: float = 0.45,
) -> list[dict]:
    """Validate a simple prior-only direction rule with expanding windows."""
    groups = defaultdict(list)
    for outcome in outcomes:
        groups[(outcome["regime"], outcome["horizon"])].append(outcome)
    records = []
    for (regime, horizon), values in sorted(groups.items()):
        ordered = sorted(values, key=lambda item: (item["signal_date"], item["symbol"]))
        for index, outcome in enumerate(ordered):
            prior = ordered[:index]
            if len(prior) < min_train_observations:
                continue
            prior_positive_rate = sum(
                float(item["forward_return"]) > 0 for item in prior
            ) / len(prior)
            predicted = (
                "BUY"
                if prior_positive_rate >= buy_threshold
                else "SELL"
                if prior_positive_rate <= sell_threshold
                else "WAIT"
            )
            actual = "BUY" if float(outcome["forward_return"]) > 0 else "SELL"
            records.append(
                {
                    "validation_version": WAVE_EXPANDING_VALIDATION_VERSION,
                    "regime": regime,
                    "horizon": horizon,
                    "symbol": outcome["symbol"],
                    "signal_date": outcome["signal_date"],
                    "training_observations": len(prior),
                    "prior_positive_rate": prior_positive_rate,
                    "predicted_direction": predicted,
                    "actual_direction": actual,
                    "correct": predicted == actual if predicted != "WAIT" else None,
                    "forward_return": outcome["forward_return"],
                }
            )
    return records


def build_wave_expanding_window_scorecard(records: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for record in records:
        groups[(record["predicted_direction"], record["horizon"])].append(record)
    rows = []
    for (direction, horizon), values in sorted(groups.items()):
        directional = [item for item in values if item["correct"] is not None]
        correct = sum(1 for item in directional if item["correct"])
        rows.append(
            {
                "validation_version": WAVE_EXPANDING_VALIDATION_VERSION,
                "predicted_direction": direction,
                "horizon": horizon,
                "observations": len(values),
                "directional_observations": len(directional),
                "directional_success_rate": (
                    correct / len(directional) if directional else None
                ),
                "mean_forward_return": (
                    sum(float(item["forward_return"]) for item in values) / len(values)
                    if values
                    else None
                ),
                "status": "RESEARCH_ONLY",
            }
        )
    return rows


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
    blocked_reasons: dict[str, str] | None = None,
) -> list[dict]:
    forecasts = []
    for symbol in sorted(held_symbols):
        wave = waves.get(symbol)
        blocked_reason = (blocked_reasons or {}).get(symbol)
        if blocked_reason:
            wave = None
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
                    "raw_probability": None,
                    "probability_shrinkage_prior_observations": (
                        PROBABILITY_SHRINKAGE_PRIOR_OBSERVATIONS
                    ),
                    "horizon": None,
                    "regime": blocked_reason or "Wave evidence unavailable",
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
        raw_probability = (
            float(positive_rate)
            if direction == "BUY" and positive_rate is not None
            else (
                1 - float(positive_rate)
                if direction == "SELL" and positive_rate is not None
                else None
            )
        )
        observations = int(evidence.get("observations", 0)) if evidence else 0
        probability = shrink_direction_probability(raw_probability, observations)
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
                "raw_probability": raw_probability,
                "probability_shrinkage_prior_observations": (
                    PROBABILITY_SHRINKAGE_PRIOR_OBSERVATIONS
                ),
                "horizon": evidence.get("horizon") if evidence else None,
                "regime": wave.regime,
                "evidence_source": evidence_source,
                "observations": observations,
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
