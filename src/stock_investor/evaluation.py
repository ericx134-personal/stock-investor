from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .data import Price
from .feedback import AlertFeedback


OUTCOME_WINDOWS = (21, 63, 126)
ALERT_ACTIONS = {"BUY_CANDIDATE", "ADD_CANDIDATE", "TRIM_REVIEW"}
INVESTMENT_DECISION_ACTIONS = ALERT_ACTIONS | {"HOLD", "REVIEW"}
FORECAST_DIRECTIONS = {"BUY", "SELL", "WAIT"}


@dataclass(frozen=True)
class AlertOutcome:
    alert_id: str
    model_version: str
    symbol: str
    action: str
    signal_date: str
    entry_close: float
    status: str
    returns: dict[str, float | None]
    benchmark_returns: dict[str, float | None]
    excess_returns: dict[str, float | None]
    directional_returns: dict[str, float | None]
    max_adverse_excursion: float | None
    max_favorable_excursion: float | None
    latest_evaluated_date: str | None
    feedback_label: str | None
    feedback_response: str | None
    feedback_note: str | None


@dataclass(frozen=True)
class ScorecardRow:
    model_version: str
    action: str
    horizon: str
    observations: int
    mean_return: float | None
    median_return: float | None
    positive_rate: float | None
    mean_excess_return: float | None
    mean_directional_return: float | None
    directional_success_rate: float | None
    feedback_observations: int
    helpful_rate: float | None
    acted_rate: float | None


def load_alert_records(path: str | Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def _future_prices(history: list[Price], signal_date: str) -> list[Price]:
    return [price for price in history if price.date.isoformat() > signal_date]


def _forward_return(entry_close: float, future: list[Price], sessions: int) -> float | None:
    if len(future) < sessions:
        return None
    return future[sessions - 1].close / entry_close - 1


def evaluate_alert_record(
    record: dict,
    prices: dict[str, list[Price]],
    benchmark_symbol: str | None = None,
    feedback: AlertFeedback | None = None,
) -> AlertOutcome:
    symbol = record["symbol"]
    signal_date = record["signal_date"]
    if record["entry_close"] is None:
        raise ValueError("alert record has no entry close")
    entry_close = float(record["entry_close"])
    future = _future_prices(prices.get(symbol, []), signal_date)
    returns = {
        f"{window}d": _forward_return(entry_close, future, window)
        for window in OUTCOME_WINDOWS
    }

    benchmark_returns = {f"{window}d": None for window in OUTCOME_WINDOWS}
    if benchmark_symbol and prices.get(benchmark_symbol):
        benchmark_history = prices[benchmark_symbol]
        entry_candidates = [
            price for price in benchmark_history if price.date.isoformat() <= signal_date
        ]
        if entry_candidates:
            benchmark_entry = entry_candidates[-1].close
            benchmark_future = _future_prices(benchmark_history, signal_date)
            benchmark_returns = {
                f"{window}d": _forward_return(
                    benchmark_entry, benchmark_future, window
                )
                for window in OUTCOME_WINDOWS
            }
    excess = {
        horizon: (
            value - benchmark_returns[horizon]
            if value is not None and benchmark_returns[horizon] is not None
            else None
        )
        for horizon, value in returns.items()
    }
    action = record["alert"]["action"]
    direction = (
        1
        if action in {"BUY_CANDIDATE", "ADD_CANDIDATE", "HOLD"}
        else -1 if action == "TRIM_REVIEW" else None
    )
    directional = {
        horizon: value * direction if value is not None and direction is not None else None
        for horizon, value in returns.items()
    }

    excursion_window = future[: OUTCOME_WINDOWS[-1]]
    excursions = [price.close / entry_close - 1 for price in excursion_window]
    return AlertOutcome(
        alert_id=record.get("alert_id") or record["decision_id"],
        model_version=record["model_version"],
        symbol=symbol,
        action=action,
        signal_date=signal_date,
        entry_close=entry_close,
        status="MATURED" if returns[f"{OUTCOME_WINDOWS[-1]}d"] is not None else "PENDING",
        returns=returns,
        benchmark_returns=benchmark_returns,
        excess_returns=excess,
        directional_returns=directional,
        max_adverse_excursion=min(excursions) if excursions else None,
        max_favorable_excursion=max(excursions) if excursions else None,
        latest_evaluated_date=future[-1].date.isoformat() if future else None,
        feedback_label=feedback.label if feedback else None,
        feedback_response=feedback.response if feedback else None,
        feedback_note=feedback.note if feedback else None,
    )


def evaluate_alerts(
    records: list[dict],
    prices: dict[str, list[Price]],
    benchmark_symbol: str | None = None,
    minimum_episode_sessions: int = 21,
    feedback: dict[str, AlertFeedback] | None = None,
) -> list[AlertOutcome]:
    if minimum_episode_sessions < 0:
        raise ValueError("minimum_episode_sessions cannot be negative")
    outcomes = []
    last_episode_index: dict[tuple[str, str, str], int] = {}
    sorted_records = sorted(records, key=lambda record: record.get("signal_date", ""))
    for record in sorted_records:
        if not all(
            key in record
            for key in ("alert_id", "model_version", "signal_date", "entry_close")
        ):
            continue
        if record.get("entry_close") is None:
            continue
        if record.get("alert", {}).get("action") not in ALERT_ACTIONS:
            continue
        symbol = record["symbol"]
        history = prices.get(symbol, [])
        signal_date = record["signal_date"]
        signal_indexes = [
            index
            for index, price in enumerate(history)
            if price.date.isoformat() <= signal_date
        ]
        if not signal_indexes:
            continue
        signal_index = signal_indexes[-1]
        key = (
            record["model_version"],
            symbol,
            record["alert"]["action"],
        )
        previous = last_episode_index.get(key)
        if previous is not None and signal_index - previous < minimum_episode_sessions:
            continue
        last_episode_index[key] = signal_index
        outcomes.append(
            evaluate_alert_record(
                record,
                prices,
                benchmark_symbol,
                (feedback or {}).get(record["alert_id"]),
            )
        )
    return outcomes


def evaluate_decisions(
    records: list[dict],
    prices: dict[str, list[Price]],
    benchmark_symbol: str | None = None,
    minimum_episode_sessions: int = 21,
) -> list[AlertOutcome]:
    """Evaluate all investment decisions; data-review states are not predictions."""
    if minimum_episode_sessions < 0:
        raise ValueError("minimum_episode_sessions cannot be negative")
    outcomes = []
    last_episode_index: dict[tuple[str, str, str], int] = {}
    for record in sorted(records, key=lambda item: item.get("signal_date", "")):
        if not all(
            key in record
            for key in ("decision_id", "model_version", "signal_date", "entry_close")
        ):
            continue
        action = record.get("alert", {}).get("action")
        if record.get("entry_close") is None or action not in INVESTMENT_DECISION_ACTIONS:
            continue
        symbol = record["symbol"]
        history = prices.get(symbol, [])
        signal_indexes = [
            index
            for index, price in enumerate(history)
            if price.date.isoformat() <= record["signal_date"]
        ]
        if not signal_indexes:
            continue
        signal_index = signal_indexes[-1]
        key = (record["model_version"], symbol, action)
        previous = last_episode_index.get(key)
        if previous is not None and signal_index - previous < minimum_episode_sessions:
            continue
        last_episode_index[key] = signal_index
        outcomes.append(evaluate_alert_record(record, prices, benchmark_symbol))
    return outcomes


def evaluate_directional_forecasts(
    records: list[dict],
    prices: dict[str, list[Price]],
    benchmark_symbol: str | None = None,
    minimum_episode_sessions: int = 21,
) -> list[dict]:
    """Evaluate displayed BUY/SELL/WAIT forecasts without inflating daily repeats."""
    if minimum_episode_sessions < 0:
        raise ValueError("minimum_episode_sessions cannot be negative")
    benchmark_history = prices.get(benchmark_symbol, []) if benchmark_symbol else []
    outcomes = []
    last_episode_index: dict[tuple[str, str, str], int] = {}
    for record in sorted(records, key=lambda item: item.get("signal_date", "")):
        if not all(
            key in record
            for key in (
                "forecast_id",
                "forecast_version",
                "symbol",
                "signal_date",
                "entry_close",
                "direction",
            )
        ):
            continue
        direction = record["direction"]
        if direction not in FORECAST_DIRECTIONS or record.get("entry_close") is None:
            continue
        history = prices.get(record["symbol"], [])
        signal_indexes = [
            index
            for index, price in enumerate(history)
            if price.date.isoformat() <= record["signal_date"]
        ]
        if not signal_indexes:
            continue
        signal_index = signal_indexes[-1]
        episode_key = (record["forecast_version"], record["symbol"], direction)
        previous = last_episode_index.get(episode_key)
        if previous is not None and signal_index - previous < minimum_episode_sessions:
            continue
        last_episode_index[episode_key] = signal_index
        entry_close = float(record["entry_close"])
        future = _future_prices(history, record["signal_date"])
        returns = {
            f"{window}d": _forward_return(entry_close, future, window)
            for window in OUTCOME_WINDOWS
        }
        benchmark_entry_candidates = [
            price
            for price in benchmark_history
            if price.date.isoformat() <= record["signal_date"]
        ]
        benchmark_future = _future_prices(benchmark_history, record["signal_date"])
        benchmark_entry = (
            benchmark_entry_candidates[-1].close
            if benchmark_entry_candidates
            else None
        )
        benchmark_returns = {
            f"{window}d": (
                _forward_return(benchmark_entry, benchmark_future, window)
                if benchmark_entry is not None
                else None
            )
            for window in OUTCOME_WINDOWS
        }
        excess_returns = {
            horizon: (
                value - benchmark_returns[horizon]
                if value is not None and benchmark_returns[horizon] is not None
                else None
            )
            for horizon, value in returns.items()
        }
        sign = 1 if direction == "BUY" else -1 if direction == "SELL" else None
        directional_returns = {
            horizon: value * sign if value is not None and sign is not None else None
            for horizon, value in returns.items()
        }
        excursion_window = future[: OUTCOME_WINDOWS[-1]]
        excursions = [price.close / entry_close - 1 for price in excursion_window]
        outcomes.append(
            {
                **record,
                "status": (
                    "MATURED"
                    if returns[f"{OUTCOME_WINDOWS[-1]}d"] is not None
                    else "PENDING"
                ),
                "returns": returns,
                "benchmark_returns": benchmark_returns,
                "excess_returns": excess_returns,
                "directional_returns": directional_returns,
                "max_adverse_excursion": min(excursions) if excursions else None,
                "max_favorable_excursion": max(excursions) if excursions else None,
                "latest_evaluated_date": (
                    future[-1].date.isoformat() if future else None
                ),
            }
        )
    return outcomes


def build_directional_forecast_scorecard(outcomes: list[dict]) -> list[dict]:
    groups: dict[tuple[str, str, str], list[dict]] = {}
    for outcome in outcomes:
        for horizon in outcome["returns"]:
            groups.setdefault(
                (outcome["forecast_version"], outcome["direction"], horizon), []
            ).append(outcome)
    rows = []
    for (version, direction, horizon), group in sorted(groups.items()):
        matured = [item for item in group if item["returns"][horizon] is not None]
        returns = [float(item["returns"][horizon]) for item in matured]
        excess = [
            float(item["excess_returns"][horizon])
            for item in matured
            if item["excess_returns"][horizon] is not None
        ]
        directional = [
            float(item["directional_returns"][horizon])
            for item in matured
            if item["directional_returns"][horizon] is not None
        ]
        probability_pairs = [
            (float(item["probability"]), item["directional_returns"][horizon] > 0)
            for item in matured
            if item.get("probability") is not None
            and item["directional_returns"][horizon] is not None
        ]
        displayed_probabilities = [
            float(item["probability"])
            for item in group
            if item.get("probability") is not None
        ]
        rows.append(
            {
                "forecast_version": version,
                "direction": direction,
                "horizon": horizon,
                "forecast_episodes": len(group),
                "observations": len(matured),
                "pending": len(group) - len(matured),
                "mean_probability": (
                    sum(displayed_probabilities) / len(displayed_probabilities)
                    if displayed_probabilities
                    else None
                ),
                "directional_success_rate": (
                    sum(value > 0 for value in directional) / len(directional)
                    if directional
                    else None
                ),
                "brier_score": (
                    sum(
                        (probability - float(success)) ** 2
                        for probability, success in probability_pairs
                    )
                    / len(probability_pairs)
                    if probability_pairs
                    else None
                ),
                "mean_return": sum(returns) / len(returns) if returns else None,
                "positive_rate": (
                    sum(value > 0 for value in returns) / len(returns)
                    if returns
                    else None
                ),
                "mean_excess_return": sum(excess) / len(excess) if excess else None,
                "mean_directional_return": (
                    sum(directional) / len(directional) if directional else None
                ),
            }
        )
    return rows


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2


def build_scorecard(outcomes: list[AlertOutcome]) -> list[ScorecardRow]:
    groups: dict[tuple[str, str, str], list[AlertOutcome]] = {}
    for outcome in outcomes:
        for horizon in outcome.returns:
            groups.setdefault(
                (outcome.model_version, outcome.action, horizon), []
            ).append(outcome)

    rows = []
    for (version, action, horizon), group in sorted(groups.items()):
        returns = [
            outcome.returns[horizon]
            for outcome in group
            if outcome.returns[horizon] is not None
        ]
        excess = [
            outcome.excess_returns[horizon]
            for outcome in group
            if outcome.excess_returns[horizon] is not None
        ]
        directional = [
            outcome.directional_returns[horizon]
            for outcome in group
            if outcome.directional_returns[horizon] is not None
        ]
        rated = [
            outcome for outcome in group if outcome.feedback_label is not None
        ]
        acted = [
            outcome
            for outcome in group
            if outcome.feedback_response is not None
        ]
        rows.append(
            ScorecardRow(
                model_version=version,
                action=action,
                horizon=horizon,
                observations=len(returns),
                mean_return=sum(returns) / len(returns) if returns else None,
                median_return=_median(returns) if returns else None,
                positive_rate=(
                    sum(value > 0 for value in returns) / len(returns)
                    if returns
                    else None
                ),
                mean_excess_return=sum(excess) / len(excess) if excess else None,
                mean_directional_return=(
                    sum(directional) / len(directional) if directional else None
                ),
                directional_success_rate=(
                    sum(value > 0 for value in directional) / len(directional)
                    if directional
                    else None
                ),
                feedback_observations=len(rated),
                helpful_rate=(
                    sum(outcome.feedback_label == "HELPFUL" for outcome in rated)
                    / len(rated)
                    if rated
                    else None
                ),
                acted_rate=(
                    sum(outcome.feedback_response == "ACTED" for outcome in acted)
                    / len(acted)
                    if acted
                    else None
                ),
            )
        )
    return rows


def write_outcomes(outcomes: list[AlertOutcome], path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps([asdict(outcome) for outcome in outcomes], indent=2, sort_keys=True)
        + "\n"
    )


def write_scorecard(rows: list[ScorecardRow], path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps([asdict(row) for row in rows], indent=2, sort_keys=True) + "\n"
    )
