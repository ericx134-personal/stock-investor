from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from .data import Price
from .indicators import MIN_HISTORY, calculate_technicals
from .io import atomic_write_text
from .model import MODEL_VERSION


@dataclass(frozen=True)
class BacktestResult:
    symbol: str
    evaluation_type: str
    start_date: str
    end_date: str
    pre_test_sessions: int
    test_sessions: int
    strategy_return: float
    buy_and_hold_return: float
    max_drawdown: float
    trades: int
    exposure: float


def _max_drawdown(equity_curve: list[float]) -> float:
    peak = equity_curve[0]
    worst = 0.0
    for equity in equity_curve:
        peak = max(peak, equity)
        worst = min(worst, equity / peak - 1)
    return worst


def backtest_trend_momentum(
    symbol: str,
    history: list[Price],
    rebalance_days: int = 21,
    transaction_cost_bps: float = 10,
) -> BacktestResult:
    """Walk-forward long/cash test of a simple trend-momentum rule.

    A decision made after a day's close affects only later returns. The rule
    uses a small no-trade band to reduce turnover rather than optimizing entry
    and exit thresholds against the supplied history.
    """
    if len(history) <= MIN_HISTORY:
        raise ValueError(f"need more than {MIN_HISTORY} daily prices for a backtest")
    if rebalance_days <= 0 or transaction_cost_bps < 0:
        raise ValueError("rebalance_days must be positive and costs cannot be negative")

    return _run_trend_momentum(
        symbol,
        history,
        MIN_HISTORY,
        len(history) - 1,
        rebalance_days,
        transaction_cost_bps,
        "FULL_HISTORY_WALK_FORWARD",
    )


def backtest_trend_momentum_oos(
    symbol: str,
    history: list[Price],
    test_start: date,
    test_end: date | None = None,
    rebalance_days: int = 21,
    transaction_cost_bps: float = 10,
) -> BacktestResult:
    """Evaluate a predeclared holdout period without counting pre-test returns."""
    if test_end and test_end < test_start:
        raise ValueError("test_end cannot be before test_start")
    start_candidates = [
        index for index, price in enumerate(history) if price.date >= test_start
    ]
    end_candidates = [
        index
        for index, price in enumerate(history)
        if test_end is None or price.date <= test_end
    ]
    if not start_candidates or not end_candidates:
        raise ValueError("test period does not overlap available price history")
    start_index = start_candidates[0]
    end_index = end_candidates[-1]
    if start_index > end_index:
        raise ValueError("test period does not contain any price sessions")
    if start_index < MIN_HISTORY:
        raise ValueError(
            f"need at least {MIN_HISTORY} pre-test daily prices before test_start"
        )
    return _run_trend_momentum(
        symbol,
        history,
        start_index,
        end_index,
        rebalance_days,
        transaction_cost_bps,
        "DEDICATED_OUT_OF_SAMPLE",
    )


def _run_trend_momentum(
    symbol: str,
    history: list[Price],
    start_index: int,
    end_index: int,
    rebalance_days: int,
    transaction_cost_bps: float,
    evaluation_type: str,
) -> BacktestResult:
    if len(history) <= MIN_HISTORY:
        raise ValueError(f"need more than {MIN_HISTORY} daily prices for a backtest")
    if rebalance_days <= 0 or transaction_cost_bps < 0:
        raise ValueError("rebalance_days must be positive and costs cannot be negative")
    if end_index < start_index:
        raise ValueError("evaluation period must contain at least one session")

    position = 0
    trades = 0
    invested_days = 0
    equity = 1.0
    equity_curve = [equity]
    cost_rate = transaction_cost_bps / 10_000

    for index in range(start_index, end_index + 1):
        if (index - start_index) % rebalance_days != 0:
            target = position
        else:
            signals = calculate_technicals(history[:index])
            combined = signals.trend * 0.55 + signals.momentum * 0.45
            target = position
            if combined >= 0.10:
                target = 1
            elif combined <= -0.10:
                target = 0
        if target != position:
            equity *= 1 - cost_rate
            trades += 1
            position = target

        daily_return = history[index].close / history[index - 1].close - 1
        if position:
            equity *= 1 + daily_return
            invested_days += 1
        equity_curve.append(equity)

    buy_and_hold = history[end_index].close / history[start_index - 1].close - 1
    test_days = end_index - start_index + 1
    return BacktestResult(
        symbol=symbol,
        evaluation_type=evaluation_type,
        start_date=history[start_index].date.isoformat(),
        end_date=history[end_index].date.isoformat(),
        pre_test_sessions=start_index,
        test_sessions=test_days,
        strategy_return=equity - 1,
        buy_and_hold_return=buy_and_hold,
        max_drawdown=_max_drawdown(equity_curve),
        trades=trades,
        exposure=invested_days / test_days if test_days else 0.0,
    )


def write_oos_report(
    results: list[BacktestResult],
    path: str | Path,
    requested_test_start: date,
    requested_test_end: date | None,
    rebalance_days: int,
    transaction_cost_bps: float,
) -> None:
    output = Path(path)
    if output.exists():
        raise FileExistsError(
            f"refusing to overwrite sealed out-of-sample report: {output}"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "model_version": MODEL_VERSION,
        "evaluation_type": "DEDICATED_OUT_OF_SAMPLE",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requested_test_start": requested_test_start.isoformat(),
        "requested_test_end": (
            requested_test_end.isoformat() if requested_test_end else None
        ),
        "rebalance_days": rebalance_days,
        "transaction_cost_bps": transaction_cost_bps,
        "results": [asdict(result) for result in results],
    }
    atomic_write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", output)
