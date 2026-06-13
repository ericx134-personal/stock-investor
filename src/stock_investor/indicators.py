from __future__ import annotations

from dataclasses import dataclass

from .data import Price


MIN_HISTORY = 252


@dataclass(frozen=True)
class TechnicalSignals:
    latest_close: float
    latest_date: str
    trend: float
    momentum: float
    drawdown_from_high: float
    sma_200: float
    return_12_to_1: float
    ohlcv_available: bool
    latest_bar_complete: bool
    atr_20_percent: float | None
    volume_ratio_20: float | None
    breakout_20: float | None
    close_position_20: float | None
    latest_gap: float | None
    latest_candle_body: float | None


def _kline_signals(history: list[Price]) -> dict[str, float | bool | None]:
    latest = history[-1]
    completed = [
        item
        for item in history[:-1]
        if item.open is not None
        and item.high is not None
        and item.low is not None
        and item.volume is not None
    ]
    if len(completed) < 21:
        completed = [
            item
            for item in history
            if item.open is not None
            and item.high is not None
            and item.low is not None
            and item.volume is not None
        ]
    if len(completed) < 21:
        latest_complete = all(
            value is not None
            for value in (latest.open, latest.high, latest.low, latest.volume)
        )
        return {
            "ohlcv_available": False,
            "latest_bar_complete": latest_complete,
            "atr_20_percent": None,
            "volume_ratio_20": None,
            "breakout_20": None,
            "close_position_20": None,
            "latest_gap": None,
            "latest_candle_body": None,
        }
    recent_completed = completed[-21:]
    if any(
        item.open is None
        or item.high is None
        or item.low is None
        or item.volume is None
        for item in recent_completed
    ):
        raise ValueError("completed K-line bars unexpectedly contain missing OHLCV")
    latest_complete = all(
        value is not None
        for value in (latest.open, latest.high, latest.low, latest.volume)
    )
    previous = history[-2]
    true_ranges = [
        max(
            float(item.high) - float(item.low),
            abs(float(item.high) - prior.close),
            abs(float(item.low) - prior.close),
        )
        for prior, item in zip(recent_completed[:-1], recent_completed[1:])
    ]
    prior_20 = recent_completed[-20:]
    prior_high = max(float(item.high) for item in prior_20)
    prior_low = min(float(item.low) for item in prior_20)
    range_width = prior_high - prior_low
    average_volume = sum(float(item.volume) for item in prior_20) / len(prior_20)
    return {
        "ohlcv_available": True,
        "latest_bar_complete": latest_complete,
        "atr_20_percent": sum(true_ranges) / len(true_ranges) / latest.close,
        "volume_ratio_20": (
            float(latest.volume) / average_volume
            if latest.volume is not None and average_volume > 0
            else None
        ),
        "breakout_20": latest.close / prior_high - 1,
        "close_position_20": (
            (latest.close - prior_low) / range_width if range_width > 0 else None
        ),
        "latest_gap": (
            float(latest.open) / previous.close - 1
            if latest.open is not None
            else None
        ),
        "latest_candle_body": (
            (latest.close - float(latest.open)) / float(latest.open)
            if latest.open is not None and float(latest.open) > 0
            else None
        ),
    }


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def calculate_technicals(history: list[Price]) -> TechnicalSignals:
    """Calculate explainable daily technical signals from adjusted closes."""
    if len(history) < MIN_HISTORY:
        raise ValueError(
            f"need at least {MIN_HISTORY} daily prices, received {len(history)}"
        )

    closes = [item.close for item in history]
    latest = history[-1]
    sma_200 = sum(closes[-200:]) / 200
    prior_sma_200 = sum(closes[-221:-21]) / 200

    distance = latest.close / sma_200 - 1
    slope = sma_200 / prior_sma_200 - 1
    trend = _clamp((distance / 0.20) * 0.7 + (slope / 0.10) * 0.3)

    return_12_to_1 = closes[-22] / closes[-252] - 1
    momentum = _clamp(return_12_to_1 / 0.40)
    drawdown = latest.close / max(closes) - 1
    kline = _kline_signals(history)

    return TechnicalSignals(
        latest_close=latest.close,
        latest_date=latest.date.isoformat(),
        trend=trend,
        momentum=momentum,
        drawdown_from_high=drawdown,
        sma_200=sma_200,
        return_12_to_1=return_12_to_1,
        **kline,
    )
