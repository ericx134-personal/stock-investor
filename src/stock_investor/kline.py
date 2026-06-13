from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .data import Price
from .monitor import MonitorResult


KLINE_FEATURE_VERSION = "kline-v1"
KLINE_OUTCOME_WINDOWS = (21, 63, 126)


def classify_kline(technicals: dict | object) -> str:
    """Describe recent K-line position without claiming a trade prediction."""
    getter = (
        technicals.get
        if isinstance(technicals, dict)
        else lambda name, default=None: getattr(technicals, name, default)
    )
    if not getter("ohlcv_available", False):
        return "K-line evidence unavailable"
    breakout = getter("breakout_20")
    position = getter("close_position_20")
    if breakout is not None and breakout >= 0:
        return "20-day breakout"
    if breakout is not None and breakout >= -0.03 and position is not None and position >= 0.8:
        return "Near 20-day breakout"
    if position is not None and position >= 0.67:
        return "Upper recent range"
    if position is not None and position <= 0.20:
        return "Lower recent range"
    return "Middle recent range"


def append_kline_history(results: list[MonitorResult], path: str | Path) -> int:
    """Persist model-independent K-line features for later forward validation."""
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
        for result in results:
            technicals = result.technicals
            if not technicals or not technicals.ohlcv_available:
                continue
            event_key = "|".join(
                (KLINE_FEATURE_VERSION, result.symbol, technicals.latest_date)
            )
            if event_key in existing:
                continue
            record = {
                "event_key": event_key,
                "feature_version": KLINE_FEATURE_VERSION,
                "symbol": result.symbol,
                "signal_date": technicals.latest_date,
                "entry_close": technicals.latest_close,
                "regime": classify_kline(technicals),
                "features": {
                    "atr_20_percent": technicals.atr_20_percent,
                    "volume_ratio_20": technicals.volume_ratio_20,
                    "breakout_20": technicals.breakout_20,
                    "close_position_20": technicals.close_position_20,
                    "latest_gap": technicals.latest_gap,
                    "latest_candle_body": technicals.latest_candle_body,
                    "latest_bar_complete": technicals.latest_bar_complete,
                },
                "observed_at": timestamp,
            }
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            existing.add(event_key)
            written += 1
    return written


def load_kline_history(path: str | Path) -> list[dict]:
    source = Path(path)
    if not source.exists():
        return []
    return [
        json.loads(line) for line in source.read_text().splitlines() if line.strip()
    ]


def evaluate_kline_history(
    records: list[dict], prices: dict[str, list[Price]]
) -> list[dict]:
    """Measure raw forward returns by observed chart regime."""
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
            for window in KLINE_OUTCOME_WINDOWS
        }
        outcomes.append(
            {
                **record,
                "returns": returns,
                "latest_evaluated_date": (
                    future[-1].date.isoformat() if future else None
                ),
                "status": (
                    "MATURED"
                    if returns[f"{KLINE_OUTCOME_WINDOWS[-1]}d"] is not None
                    else "PENDING"
                ),
            }
        )
    return outcomes


def build_kline_scorecard(outcomes: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for outcome in outcomes:
        for horizon, value in outcome["returns"].items():
            if value is not None:
                groups[(outcome["feature_version"], outcome["regime"], horizon)].append(
                    value
                )
    rows = []
    for (version, regime, horizon), values in sorted(groups.items()):
        rows.append(
            {
                "feature_version": version,
                "regime": regime,
                "horizon": horizon,
                "observations": len(values),
                "mean_return": sum(values) / len(values),
                "positive_rate": sum(value > 0 for value in values) / len(values),
            }
        )
    return rows
