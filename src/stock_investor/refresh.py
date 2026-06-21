from __future__ import annotations

import json
import hashlib
import os
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path

from .brief import build_portfolio_learning_review, write_brief
from .dashboard import build_dashboard, write_dashboard
from .data import Position, load_positions, load_prices
from .diagnostics import (
    analyze_alert_burden,
    analyze_fundamental_coverage,
    build_price_health_report,
    build_model_health_summary,
    compare_monitor_files,
    infer_price_source,
)
from .evaluation import (
    build_directional_forecast_scorecard,
    build_directional_classification_metrics,
    build_directional_error_cohorts,
    build_forecast_calibration_scorecard,
    build_forecast_calibration_curves,
    build_scorecard,
    evaluate_alerts,
    evaluate_decisions,
    evaluate_directional_forecasts,
    load_alert_records,
    write_outcomes,
    write_scorecard,
)
from .feedback import load_latest_feedback
from .fundamentals import load_fundamentals
from .kline import (
    append_kline_history,
    build_kline_scorecard,
    evaluate_kline_history,
    load_kline_history,
)
from .io import atomic_write_text
from .monitor import (
    run_monitor,
    write_alert_history,
    write_decision_history,
    write_monitor_snapshot,
)
from .risk import analyze_portfolio_risk, load_risk_policy, write_portfolio_risk_history
from .robinhood import load_robinhood_cash
from .research import (
    build_false_discovery_warnings,
    build_multiple_testing_ledger,
    load_evaluation_periods,
)
from .thesis import load_theses
from .wave import (
    append_directional_forecast_history,
    append_wave_history,
    build_direction_rate_comparison_scorecard,
    build_directional_forecasts,
    build_price_zone_replay,
    build_price_zone_replay_scorecard,
    build_wave_conditional_scorecard,
    build_wave_scorecard,
    build_wave_expanding_window_scorecard,
    build_wave_expanding_window_validation,
    build_wave_market_regime_stability_scorecard,
    build_wave_time_decay_scorecard,
    build_wave_time_period_stability_scorecard,
    build_wave_walk_forward_outcomes,
    build_wave_walk_forward_scorecard,
    calculate_waves,
    evaluate_wave_history,
    load_wave_history,
    load_directional_forecast_history,
    write_wave_snapshot,
)


def _write_json(payload: object, path: Path) -> None:
    atomic_write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", path)


def _file_fingerprint(path: str | Path) -> dict:
    source = Path(path)
    content = source.read_bytes()
    return {
        "path": str(source),
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def validate_production_refresh(
    output_dir: str | Path,
    *,
    account_summary_path: str | Path | None,
    price_source: str | None,
    price_adjustment: str | None,
) -> None:
    output = Path(output_dir)
    if "private" not in {part.lower() for part in output.parts}:
        raise ValueError("production-safe refresh output must be under a private directory")
    if not account_summary_path:
        raise ValueError("production-safe refresh requires an account summary")
    if not price_source:
        raise ValueError("production-safe refresh requires a declared price source")
    if not price_adjustment:
        raise ValueError("production-safe refresh requires declared adjustment semantics")


@contextmanager
def refresh_lock(output_dir: str | Path):
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    lock_path = output / ".refresh.lock"
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise RuntimeError(f"refresh already running: {lock_path}") from error
    try:
        with os.fdopen(descriptor, "w") as handle:
            handle.write(f"pid={os.getpid()}\n")
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def _artifact_paths(output_dir: Path, model_version: str) -> dict[str, Path]:
    slug = model_version.replace("decision-support-", "model-")
    return {
        "alerts": output_dir / f"{slug}-alerts.jsonl",
        "snapshot": output_dir / f"{slug}-snapshot.json",
        "decisions": output_dir / f"{slug}-decisions.jsonl",
        "decision_outcomes": output_dir / f"{slug}-decision-outcomes.json",
        "decision_scorecard": output_dir / f"{slug}-decision-scorecard.json",
        "risk": output_dir / f"{slug}-risk.jsonl",
        "outcomes": output_dir / f"{slug}-outcomes.json",
        "scorecard": output_dir / f"{slug}-scorecard.json",
        "diagnostic": output_dir / f"{slug}-diagnostic.json",
        "model_health": output_dir / "model-health.json",
        "price_health": output_dir / "price-health.json",
        "input_integrity": output_dir / "input-integrity.json",
        "refresh_history": output_dir / "refresh-history.jsonl",
        "coverage": output_dir / "fundamental-coverage.json",
        "kline_history": output_dir / "kline-history.jsonl",
        "kline_outcomes": output_dir / "kline-outcomes.json",
        "kline_scorecard": output_dir / "kline-scorecard.json",
        "wave_snapshot": output_dir / "wave-snapshot.json",
        "wave_history": output_dir / "wave-history.jsonl",
        "wave_outcomes": output_dir / "wave-outcomes.json",
        "wave_scorecard": output_dir / "wave-scorecard.json",
        "wave_experiment_outcomes": output_dir / "wave-experiment-outcomes.json",
        "wave_experiment_scorecard": output_dir / "wave-experiment-scorecard.json",
        "wave_conditional_scorecard": output_dir / "wave-conditional-scorecard.json",
        "wave_time_decay_scorecard": output_dir / "wave-time-decay-scorecard.json",
        "wave_time_period_stability_scorecard": output_dir / "wave-time-period-stability-scorecard.json",
        "wave_market_regime_stability_scorecard": output_dir / "wave-market-regime-stability-scorecard.json",
        "wave_expanding_validation": output_dir / "wave-expanding-validation.json",
        "wave_expanding_validation_scorecard": output_dir / "wave-expanding-validation-scorecard.json",
        "price_zone_replay": output_dir / "price-zone-replay.json",
        "price_zone_replay_scorecard": output_dir / "price-zone-replay-scorecard.json",
        "direction_rate_comparison": output_dir / "direction-rate-comparison.json",
        "direction_forecasts": output_dir / "wave-direction-forecasts.jsonl",
        "direction_forecast_outcomes": output_dir / "wave-direction-forecast-outcomes.json",
        "direction_forecast_scorecard": output_dir / "wave-direction-forecast-scorecard.json",
        "forecast_calibration_scorecard": output_dir / "forecast-calibration-scorecard.json",
        "forecast_calibration_curves": output_dir / "forecast-calibration-curves.json",
        "direction_classification_metrics": output_dir / "direction-classification-metrics.json",
        "direction_error_cohorts": output_dir / "direction-error-cohorts.json",
        "first_observed_forecasts": output_dir / "first-observed-forecasts.json",
        "forecast_action_segments": output_dir / "forecast-action-segments.json",
        "portfolio_learning_review": output_dir / "portfolio-learning-review.md",
        "multiple_testing_ledger": output_dir / "multiple-testing-ledger.json",
        "false_discovery_warnings": output_dir / "false-discovery-warnings.json",
        "comparison": output_dir / f"model-v1-{slug.removeprefix('model-')}-comparison.json",
        "dashboard": output_dir / f"dashboard-{slug.removeprefix('model-')}.html",
        "manifest": output_dir / "refresh-manifest.json",
    }


def _forecast_key(record: dict) -> tuple:
    return (
        record.get("forecast_id"),
        record.get("forecast_version"),
        record.get("symbol"),
        record.get("signal_date"),
        record.get("horizon"),
        record.get("direction"),
    )


def _forecast_summary(record: dict | None) -> dict | None:
    if not record:
        return None
    return {
        key: record.get(key)
        for key in (
            "forecast_id",
            "forecast_version",
            "direction",
            "probability",
            "signal_date",
            "observed_at",
            "entry_close",
            "horizon",
            "regime",
            "evidence_source",
            "observations",
            "directional_symbols",
            "wave_age_bucket",
            "wave_magnitude_bucket",
        )
        if key in record
    }


def _forecast_outcome_summary(record: dict | None) -> dict | None:
    if not record:
        return None
    return {
        key: record.get(key)
        for key in (
            "status",
            "latest_evaluated_date",
            "returns",
            "benchmark_returns",
            "excess_returns",
            "directional_returns",
            "max_adverse_excursion",
            "max_favorable_excursion",
        )
        if key in record
    }


def build_first_observed_forecast_tracking(
    held_symbols: set[str],
    direction_forecast_records: list[dict],
    current_direction_forecasts: list[dict],
    direction_forecast_outcomes: list[dict],
) -> dict:
    """Track every current holding against its earliest persisted direction forecast."""
    first_by_symbol: dict[str, dict] = {}
    for record in sorted(
        direction_forecast_records,
        key=lambda item: (
            item.get("signal_date", ""),
            item.get("observed_at", ""),
            item.get("forecast_version", ""),
            item.get("forecast_id", ""),
        ),
    ):
        symbol = record.get("symbol")
        if symbol in held_symbols and symbol not in first_by_symbol:
            first_by_symbol[symbol] = record
    latest_by_symbol = {
        record.get("symbol"): record
        for record in sorted(
            current_direction_forecasts,
            key=lambda item: (
                item.get("signal_date", ""),
                item.get("observed_at", ""),
                item.get("forecast_version", ""),
                item.get("forecast_id", ""),
            ),
        )
        if record.get("symbol") in held_symbols
    }
    outcome_by_key = {_forecast_key(record): record for record in direction_forecast_outcomes}
    holdings = []
    for symbol in sorted(held_symbols):
        first = first_by_symbol.get(symbol)
        current = latest_by_symbol.get(symbol)
        changed = (
            bool(first and current)
            and (
                first.get("direction") != current.get("direction")
                or first.get("horizon") != current.get("horizon")
                or first.get("forecast_version") != current.get("forecast_version")
            )
        )
        holdings.append(
            {
                "symbol": symbol,
                "status": "TRACKED" if first else "MISSING",
                "first_forecast": _forecast_summary(first),
                "current_forecast": _forecast_summary(current),
                "changed_since_first": changed,
                "first_outcome": _forecast_outcome_summary(
                    outcome_by_key.get(_forecast_key(first)) if first else None
                ),
            }
        )
    tracked = [row for row in holdings if row["status"] == "TRACKED"]
    return {
        "schema_version": "first-observed-forecasts-v1",
        "held_symbol_count": len(held_symbols),
        "tracked_count": len(tracked),
        "missing_count": len(held_symbols) - len(tracked),
        "changed_since_first_count": sum(
            1 for row in tracked if row["changed_since_first"]
        ),
        "first_direction_counts": dict(
            sorted(
                Counter(
                    (row["first_forecast"] or {}).get("direction", "UNKNOWN")
                    for row in tracked
                ).items()
            )
        ),
        "first_outcome_status_counts": dict(
            sorted(
                Counter(
                    (row["first_outcome"] or {}).get("status", "PENDING")
                    for row in tracked
                ).items()
            )
        ),
        "holdings": holdings,
    }


FORECAST_ACTION_SEGMENTS = {
    "ACTED_ON_PROXY": {
        "label": "Acted-on proxy",
        "basis": "Symbol is currently held with shares greater than zero.",
    },
    "WATCHED_PROXY": {
        "label": "Watched proxy",
        "basis": "Symbol is currently listed with zero shares.",
    },
    "IGNORED_OR_EXITED_PROXY": {
        "label": "Ignored/exited proxy",
        "basis": "Symbol appears in the forecast ledger but not in current positions.",
    },
}


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _forecast_action_segment(symbol: str, positions_by_symbol: dict[str, Position]) -> str:
    position = positions_by_symbol.get(symbol)
    if position and position.shares > 0:
        return "ACTED_ON_PROXY"
    if position:
        return "WATCHED_PROXY"
    return "IGNORED_OR_EXITED_PROXY"


def build_forecast_action_segments(
    positions: list[Position],
    direction_forecast_outcomes: list[dict],
) -> dict:
    """Compare forecast outcomes by current portfolio/watchlist proxy segment."""
    positions_by_symbol = {position.symbol: position for position in positions}
    score_groups: dict[tuple[str, str, str, str], list[dict]] = {}
    episode_rows = []
    for outcome in direction_forecast_outcomes:
        symbol = str(outcome.get("symbol") or "")
        segment = _forecast_action_segment(symbol, positions_by_symbol)
        detail = FORECAST_ACTION_SEGMENTS[segment]
        episode_rows.append(
            {
                "forecast_id": outcome.get("forecast_id"),
                "forecast_version": outcome.get("forecast_version"),
                "symbol": symbol,
                "segment": segment,
                "segment_label": detail["label"],
                "segment_basis": detail["basis"],
                "direction": outcome.get("direction"),
                "probability": outcome.get("probability"),
                "signal_date": outcome.get("signal_date"),
                "status": outcome.get("status"),
                "latest_evaluated_date": outcome.get("latest_evaluated_date"),
            }
        )
        for horizon in (outcome.get("returns") or {}):
            score_groups.setdefault(
                (
                    segment,
                    str(outcome.get("forecast_version") or ""),
                    str(outcome.get("direction") or ""),
                    horizon,
                ),
                [],
            ).append(outcome)
    scorecard = []
    for (segment, version, direction, horizon), group in sorted(score_groups.items()):
        matured = [
            item
            for item in group
            if (item.get("returns") or {}).get(horizon) is not None
        ]
        returns = [float((item.get("returns") or {})[horizon]) for item in matured]
        excess = [
            float((item.get("excess_returns") or {})[horizon])
            for item in matured
            if (item.get("excess_returns") or {}).get(horizon) is not None
        ]
        directional = [
            float((item.get("directional_returns") or {})[horizon])
            for item in matured
            if (item.get("directional_returns") or {}).get(horizon) is not None
        ]
        scorecard.append(
            {
                "segment": segment,
                "segment_label": FORECAST_ACTION_SEGMENTS[segment]["label"],
                "segment_basis": FORECAST_ACTION_SEGMENTS[segment]["basis"],
                "forecast_version": version,
                "direction": direction,
                "horizon": horizon,
                "forecast_episodes": len(group),
                "matured_observations": len(matured),
                "pending": len(group) - len(matured),
                "directional_observations": len(directional),
                "mean_return": _mean(returns),
                "mean_excess_return": _mean(excess),
                "mean_directional_return": _mean(directional),
                "directional_success_rate": (
                    sum(value > 0 for value in directional) / len(directional)
                    if directional
                    else None
                ),
                "symbols": sorted({str(item.get("symbol") or "") for item in group}),
            }
        )
    return {
        "schema_version": "forecast-action-segments-v1",
        "methodology_note": (
            "Segments are current-state observational proxies only. They do not "
            "prove that a forecast caused a trade, watchlist decision, or ignored "
            "opportunity."
        ),
        "segment_definitions": FORECAST_ACTION_SEGMENTS,
        "current_position_segment_counts": dict(
            sorted(
                Counter(
                    _forecast_action_segment(position.symbol, positions_by_symbol)
                    for position in positions
                ).items()
            )
        ),
        "episode_segment_counts": dict(
            sorted(Counter(row["segment"] for row in episode_rows).items())
        ),
        "scorecard": scorecard,
        "episodes": episode_rows,
    }


def run_refresh(
    positions_path: str | Path,
    prices_path: str | Path,
    output_dir: str | Path,
    model_version: str,
    *,
    account_summary_path: str | Path | None = None,
    cash_balance: float = 0.0,
    fundamentals_path: str | Path | None = None,
    risk_policy_path: str | Path | None = None,
    theses_path: str | Path | None = None,
    feedback_path: str | Path | None = None,
    baseline_snapshot_path: str | Path | None = None,
    benchmark_symbol: str | None = "SPY",
    episode_sessions: int = 21,
    price_source: str | None = None,
    latest_quotes_path: str | Path | None = None,
    price_adjustment: str | None = None,
) -> dict:
    """Refresh all read-only decision-support artifacts, writing the manifest last."""
    started_at = datetime.now(timezone.utc)
    output_dir = Path(output_dir)
    paths = _artifact_paths(output_dir, model_version)
    positions = load_positions(positions_path)
    held_symbols = {position.symbol for position in positions if position.shares > 0}
    prices = load_prices(prices_path)
    input_integrity = {
        "schema_version": "input-integrity-v1",
        "positions": _file_fingerprint(positions_path),
        "prices": _file_fingerprint(prices_path),
    }
    _write_json(input_integrity, paths["input_integrity"])
    price_health = build_price_health_report(
        prices,
        held_symbols,
        as_of=date.today(),
        source=infer_price_source(prices_path, price_source, price_adjustment),
        expected_sessions={
            item.date for item in prices.get(benchmark_symbol or "", [])
        },
        expected_session_source=benchmark_symbol,
    )
    _write_json(price_health, paths["price_health"])
    blocked_forecast_reasons = {
        row["symbol"]: f'Data quality gate blocked direction: {row["status"]} / {row["data_quality_status"]}'
        for row in price_health["symbols"]
        if row["status"] != "FRESH" or row["data_quality_status"] == "POOR"
    }
    fundamentals = (
        load_fundamentals(fundamentals_path)
        if fundamentals_path and Path(fundamentals_path).exists()
        else {}
    )
    risk_policy = (
        load_risk_policy(risk_policy_path)
        if risk_policy_path and Path(risk_policy_path).exists()
        else None
    )
    theses = (
        load_theses(theses_path)
        if theses_path and Path(theses_path).exists()
        else None
    )
    feedback = (
        load_latest_feedback(feedback_path)
        if feedback_path and Path(feedback_path).exists()
        else {}
    )
    cash = (
        load_robinhood_cash(account_summary_path)
        if account_summary_path
        else cash_balance
    )
    portfolio_risk = analyze_portfolio_risk(
        positions, prices, cash, risk_policy
    ) if risk_policy else analyze_portfolio_risk(positions, prices, cash)
    results = run_monitor(
        positions,
        prices,
        cash,
        fundamentals,
        portfolio_risk,
        theses,
        model_version,
    )
    write_alert_history(results, paths["alerts"], model_version)
    write_decision_history(results, paths["decisions"], model_version)
    write_monitor_snapshot(results, paths["snapshot"], model_version)
    write_portfolio_risk_history(portfolio_risk, paths["risk"])
    append_kline_history(results, paths["kline_history"])
    kline_outcomes = evaluate_kline_history(
        load_kline_history(paths["kline_history"]), prices
    )
    kline_scorecard = build_kline_scorecard(kline_outcomes)
    _write_json(kline_outcomes, paths["kline_outcomes"])
    _write_json(kline_scorecard, paths["kline_scorecard"])
    waves = calculate_waves(prices)
    write_wave_snapshot(waves, paths["wave_snapshot"])
    append_wave_history(waves, paths["wave_history"])
    wave_outcomes = evaluate_wave_history(load_wave_history(paths["wave_history"]), prices)
    wave_scorecard = build_wave_scorecard(wave_outcomes)
    _write_json(wave_outcomes, paths["wave_outcomes"])
    _write_json(wave_scorecard, paths["wave_scorecard"])
    experiment_prices = {
        symbol: history
        for symbol, history in prices.items()
        if symbol in held_symbols or symbol == benchmark_symbol
    }
    wave_experiment_outcomes = build_wave_walk_forward_outcomes(
        experiment_prices, benchmark_symbol
    )
    wave_experiment_scorecard = build_wave_walk_forward_scorecard(
        wave_experiment_outcomes
    )
    wave_conditional_scorecard = build_wave_conditional_scorecard(
        wave_experiment_outcomes
    )
    wave_time_decay_scorecard = build_wave_time_decay_scorecard(
        wave_experiment_outcomes
    )
    evaluation_periods = load_evaluation_periods(
        Path(__file__).resolve().parents[2] / "models" / "evaluation-periods-v1.json"
    )
    wave_time_period_stability_scorecard = (
        build_wave_time_period_stability_scorecard(
            wave_experiment_outcomes,
            evaluation_periods,
        )
    )
    wave_market_regime_stability_scorecard = (
        build_wave_market_regime_stability_scorecard(
            wave_experiment_outcomes,
            prices.get(benchmark_symbol or "", []),
        )
    )
    wave_expanding_validation = build_wave_expanding_window_validation(
        wave_experiment_outcomes
    )
    wave_expanding_validation_scorecard = build_wave_expanding_window_scorecard(
        wave_expanding_validation
    )
    _write_json(wave_experiment_outcomes, paths["wave_experiment_outcomes"])
    _write_json(wave_experiment_scorecard, paths["wave_experiment_scorecard"])
    _write_json(wave_conditional_scorecard, paths["wave_conditional_scorecard"])
    _write_json(wave_time_decay_scorecard, paths["wave_time_decay_scorecard"])
    _write_json(
        wave_time_period_stability_scorecard,
        paths["wave_time_period_stability_scorecard"],
    )
    _write_json(
        wave_market_regime_stability_scorecard,
        paths["wave_market_regime_stability_scorecard"],
    )
    _write_json(wave_expanding_validation, paths["wave_expanding_validation"])
    _write_json(
        wave_expanding_validation_scorecard,
        paths["wave_expanding_validation_scorecard"],
    )
    direction_rate_comparison = build_direction_rate_comparison_scorecard(
        wave_experiment_scorecard,
        wave_conditional_scorecard,
    )
    _write_json(direction_rate_comparison, paths["direction_rate_comparison"])
    price_zone_replay = build_price_zone_replay(experiment_prices)
    price_zone_replay_scorecard = build_price_zone_replay_scorecard(
        price_zone_replay
    )
    _write_json(price_zone_replay, paths["price_zone_replay"])
    _write_json(price_zone_replay_scorecard, paths["price_zone_replay_scorecard"])
    direction_forecasts = build_directional_forecasts(
        waves,
        held_symbols,
        wave_experiment_scorecard,
        wave_conditional_scorecard,
        prices,
        blocked_forecast_reasons,
    )
    append_directional_forecast_history(
        direction_forecasts, paths["direction_forecasts"]
    )
    direction_forecast_records = load_directional_forecast_history(
        paths["direction_forecasts"]
    )
    direction_forecast_outcomes = evaluate_directional_forecasts(
        direction_forecast_records, prices, benchmark_symbol, episode_sessions
    )
    direction_forecast_scorecard = build_directional_forecast_scorecard(
        direction_forecast_outcomes
    )
    forecast_calibration_scorecard = build_forecast_calibration_scorecard(
        direction_forecast_outcomes
    )
    forecast_calibration_curves = build_forecast_calibration_curves(
        forecast_calibration_scorecard
    )
    direction_classification_metrics = build_directional_classification_metrics(
        direction_forecast_outcomes
    )
    direction_error_cohorts = build_directional_error_cohorts(
        direction_forecast_outcomes
    )
    first_observed_forecasts = build_first_observed_forecast_tracking(
        held_symbols,
        direction_forecast_records,
        direction_forecasts,
        direction_forecast_outcomes,
    )
    forecast_action_segments = build_forecast_action_segments(
        positions,
        direction_forecast_outcomes,
    )
    _write_json(
        direction_forecast_outcomes, paths["direction_forecast_outcomes"]
    )
    _write_json(
        direction_forecast_scorecard, paths["direction_forecast_scorecard"]
    )
    _write_json(
        forecast_calibration_scorecard, paths["forecast_calibration_scorecard"]
    )
    _write_json(
        forecast_calibration_curves, paths["forecast_calibration_curves"]
    )
    _write_json(
        direction_classification_metrics, paths["direction_classification_metrics"]
    )
    _write_json(direction_error_cohorts, paths["direction_error_cohorts"])
    _write_json(first_observed_forecasts, paths["first_observed_forecasts"])
    _write_json(forecast_action_segments, paths["forecast_action_segments"])

    alert_records = load_alert_records(paths["alerts"])
    outcomes = evaluate_alerts(
        alert_records,
        prices,
        benchmark_symbol,
        episode_sessions,
        feedback,
    )
    scorecard = build_scorecard(outcomes)
    write_outcomes(outcomes, paths["outcomes"])
    write_scorecard(scorecard, paths["scorecard"])
    decision_records = load_alert_records(paths["decisions"])
    decision_outcomes = evaluate_decisions(
        decision_records, prices, benchmark_symbol, episode_sessions
    )
    decision_scorecard = build_scorecard(decision_outcomes)
    write_outcomes(decision_outcomes, paths["decision_outcomes"])
    write_scorecard(decision_scorecard, paths["decision_scorecard"])
    multiple_testing_ledger = build_multiple_testing_ledger(
        {
            "scorecard": len(scorecard),
            "decision_scorecard": len(decision_scorecard),
            "kline_scorecard": len(kline_scorecard),
            "wave_scorecard": len(wave_scorecard),
            "wave_experiment_scorecard": len(wave_experiment_scorecard),
            "wave_conditional_scorecard": len(wave_conditional_scorecard),
            "direction_forecast_scorecard": len(direction_forecast_scorecard),
            "forecast_calibration_scorecard": len(forecast_calibration_scorecard),
            "direction_classification_metrics": len(direction_classification_metrics),
            "direction_error_cohorts": len(direction_error_cohorts),
            "forecast_action_segments": len(forecast_action_segments["scorecard"]),
            "price_zone_replay_scorecard": len(price_zone_replay_scorecard),
            "direction_rate_comparison": len(direction_rate_comparison),
            "wave_time_decay_scorecard": len(wave_time_decay_scorecard),
            "wave_time_period_stability_scorecard": len(
                wave_time_period_stability_scorecard
            ),
            "wave_market_regime_stability_scorecard": len(
                wave_market_regime_stability_scorecard
            ),
            "wave_expanding_validation_scorecard": len(
                wave_expanding_validation_scorecard
            ),
        }
    )
    _write_json(multiple_testing_ledger, paths["multiple_testing_ledger"])
    false_discovery_warnings = build_false_discovery_warnings(
        multiple_testing_ledger
    )
    _write_json(false_discovery_warnings, paths["false_discovery_warnings"])

    records = [
        {
            **asdict(result),
            "model_version": model_version,
        }
        for result in results
    ]
    diagnostic = analyze_alert_burden(records)
    coverage = analyze_fundamental_coverage(positions, fundamentals)
    _write_json(diagnostic, paths["diagnostic"])
    _write_json(coverage, paths["coverage"])
    latest_price_date = max(
        (history[-1].date for history in prices.values() if history), default=None
    )
    missing_prices = sorted(symbol for symbol in held_symbols if not prices.get(symbol))
    kline_ready = sum(
        bool(result.technicals and result.technicals.ohlcv_available)
        for result in results
    )
    wave_ready = sum(symbol in waves for symbol in held_symbols)
    model_health = build_model_health_summary(
        read_only=True,
        price_coverage_rate=(
            (len(held_symbols) - len(missing_prices)) / len(held_symbols)
            if held_symbols
            else 1.0
        ),
        prices_fresh=price_health["all_held_symbols_fresh"],
        kline_coverage_rate=kline_ready / len(results) if results else 0.0,
        wave_coverage_rate=wave_ready / len(held_symbols) if held_symbols else 0.0,
        diagnostic=diagnostic,
        fundamental_coverage_rate=(
            len(coverage["v3_buy_ready_symbols"]) / len(positions)
            if positions
            else 0.0
        ),
        direction_forecast_scorecard=direction_forecast_scorecard,
    )
    _write_json(model_health, paths["model_health"])
    write_brief(
        build_portfolio_learning_review(
            model_health=model_health,
            price_health=price_health,
            first_observed_forecasts=first_observed_forecasts,
            forecast_action_segments=forecast_action_segments,
            direction_forecast_scorecard=direction_forecast_scorecard,
            forecast_calibration_curves=forecast_calibration_curves,
            direction_error_cohorts=direction_error_cohorts,
            now=datetime.now(timezone.utc),
        ),
        paths["portfolio_learning_review"],
    )

    comparison_path = None
    if baseline_snapshot_path and Path(baseline_snapshot_path).exists():
        comparison = compare_monitor_files(baseline_snapshot_path, paths["snapshot"])
        _write_json(comparison, paths["comparison"])
        comparison_path = paths["comparison"]

    write_dashboard(
        build_dashboard(
            paths["snapshot"],
            paths["risk"],
            paths["scorecard"],
            decision_scorecard_path=paths["decision_scorecard"],
            comparison_path=comparison_path,
            fundamental_coverage_path=paths["coverage"],
            kline_scorecard_path=paths["kline_scorecard"],
            wave_snapshot_path=paths["wave_snapshot"],
            wave_scorecard_path=paths["wave_scorecard"],
            wave_experiment_scorecard_path=paths["wave_experiment_scorecard"],
            wave_conditional_scorecard_path=paths["wave_conditional_scorecard"],
            wave_time_decay_scorecard_path=paths["wave_time_decay_scorecard"],
            direction_rate_comparison_path=paths["direction_rate_comparison"],
            direction_forecasts_path=paths["direction_forecasts"],
            direction_forecast_outcomes_path=paths["direction_forecast_outcomes"],
            direction_forecast_scorecard_path=paths["direction_forecast_scorecard"],
            forecast_calibration_curves_path=paths["forecast_calibration_curves"],
            direction_classification_metrics_path=paths["direction_classification_metrics"],
            direction_error_cohorts_path=paths["direction_error_cohorts"],
            first_observed_forecasts_path=paths["first_observed_forecasts"],
            forecast_action_segments_path=paths["forecast_action_segments"],
            portfolio_learning_review_path=paths["portfolio_learning_review"],
            multiple_testing_ledger_path=paths["multiple_testing_ledger"],
            false_discovery_warnings_path=paths["false_discovery_warnings"],
            model_health_path=paths["model_health"],
            price_health_path=paths["price_health"],
            prices_path=prices_path,
            latest_quotes_path=latest_quotes_path,
            account_summary_path=account_summary_path,
        ),
        paths["dashboard"],
    )

    warnings = []
    if latest_price_date and (date.today() - latest_price_date).days > 7:
        warnings.append(
            f"Latest available price date {latest_price_date.isoformat()} is more than 7 days old."
        )
    if missing_prices:
        warnings.append(f"Missing price history for {len(missing_prices)} held symbols.")
    if not fundamentals:
        warnings.append("No SEC fundamental snapshots are available.")
    if benchmark_symbol and not prices.get(benchmark_symbol):
        warnings.append(f"Benchmark {benchmark_symbol} price history is unavailable.")
    matured = sum(
        row.observations for row in scorecard if row.observations > 0
    )
    matured_decisions = sum(
        row.observations for row in decision_scorecard if row.observations > 0
    )
    if not matured:
        warnings.append("No forward outcome horizon has matured yet.")

    actions = Counter(result.alert.action for result in results)
    completed_at = datetime.now(timezone.utc)
    artifact_sizes = {
        name: path.stat().st_size
        for name, path in paths.items()
        if name not in {"manifest", "refresh_history"} and path.exists()
    }
    refresh_record = {
        "schema_version": "refresh-run-v1",
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "duration_seconds": (completed_at - started_at).total_seconds(),
        "status": model_health["overall_status"],
        "model_version": model_version,
        "input_integrity": input_integrity,
        "artifact_bytes": artifact_sizes,
        "total_artifact_bytes": sum(artifact_sizes.values()),
    }
    with paths["refresh_history"].open("a") as handle:
        handle.write(json.dumps(refresh_record, sort_keys=True) + "\n")
    manifest = {
        "status": model_health["overall_status"],
        "model_health": model_health,
        "read_only": True,
        "model_version": model_version,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "duration_seconds": refresh_record["duration_seconds"],
        "artifact_bytes": artifact_sizes,
        "total_artifact_bytes": refresh_record["total_artifact_bytes"],
        "latest_price_date": latest_price_date.isoformat() if latest_price_date else None,
        "position_count": len(positions),
        "held_position_count": len(held_symbols),
        "missing_price_symbols": missing_prices,
        "price_health_status_counts": price_health["status_counts"],
        "price_source": price_health["source"],
        "input_integrity": input_integrity,
        "symbols_with_missing_sessions": price_health["symbols_with_missing_sessions"],
        "symbols_with_suspicious_ohlcv": price_health["symbols_with_suspicious_ohlcv"],
        "symbols_with_suspicious_close_gaps": price_health["symbols_with_suspicious_close_gaps"],
        "symbols_with_possible_splits": price_health["symbols_with_possible_splits"],
        "symbols_with_symbol_lifecycle_risk": price_health[
            "symbols_with_symbol_lifecycle_risk"
        ],
        "data_quality_status_counts": price_health["data_quality_status_counts"],
        "action_counts": dict(sorted(actions.items())),
        "actionable_rate": diagnostic["actionable_rate"],
        "data_review_rate": diagnostic["data_review_rate"],
        "kline_coverage_rate": kline_ready / len(results) if results else 0.0,
        "kline_ready_count": kline_ready,
        "matured_scorecard_observations": matured,
        "decision_ledger_records": len(decision_records),
        "matured_decision_observations": matured_decisions,
        "matured_kline_observations": sum(
            row["observations"] for row in kline_scorecard
        ),
        "wave_ready_count": wave_ready,
        "matured_wave_observations": sum(
            row["observations"] for row in wave_scorecard
        ),
        "historical_wave_observations": len(wave_experiment_outcomes),
        "historical_wave_scorecard_rows": len(wave_experiment_scorecard),
        "conditional_wave_scorecard_rows": len(wave_conditional_scorecard),
        "wave_time_decay_scorecard_rows": len(wave_time_decay_scorecard),
        "wave_time_period_stability_scorecard_rows": len(
            wave_time_period_stability_scorecard
        ),
        "wave_market_regime_stability_scorecard_rows": len(
            wave_market_regime_stability_scorecard
        ),
        "wave_expanding_validation_count": len(wave_expanding_validation),
        "wave_expanding_validation_scorecard_rows": len(
            wave_expanding_validation_scorecard
        ),
        "direction_rate_comparison_rows": len(direction_rate_comparison),
        "historical_directional_leave_one_out_downgrades": sum(
            row.get("directional_pre_leave_one_out_classification")
            != row.get("directional_evidence_classification")
            for row in wave_experiment_scorecard
        ),
        "conditional_directional_leave_one_out_downgrades": sum(
            row.get("directional_pre_leave_one_out_classification")
            != row.get("directional_evidence_classification")
            for row in wave_conditional_scorecard
        ),
        "direction_forecast_records": len(direction_forecast_records),
        "direction_forecast_episode_count": len(direction_forecast_outcomes),
        "current_direction_forecast_counts": dict(
            sorted(Counter(row["direction"] for row in direction_forecasts).items())
        ),
        "matured_direction_forecast_observations": sum(
            row["observations"] for row in direction_forecast_scorecard
        ),
        "forecast_calibration_status_counts": dict(
            sorted(Counter(row["status"] for row in forecast_calibration_scorecard).items())
        ),
        "forecast_calibration_curve_status_counts": dict(
            sorted(Counter(row["status"] for row in forecast_calibration_curves).items())
        ),
        "direction_classification_status_counts": dict(
            sorted(Counter(row["status"] for row in direction_classification_metrics).items())
        ),
        "direction_error_cohort_count": len(direction_error_cohorts),
        "first_observed_forecast_tracked_count": first_observed_forecasts[
            "tracked_count"
        ],
        "first_observed_forecast_missing_count": first_observed_forecasts[
            "missing_count"
        ],
        "first_observed_forecast_changed_count": first_observed_forecasts[
            "changed_since_first_count"
        ],
        "forecast_action_segment_scorecard_rows": len(
            forecast_action_segments["scorecard"]
        ),
        "forecast_action_segment_episode_counts": forecast_action_segments[
            "episode_segment_counts"
        ],
        "multiple_testing_total_hypotheses": multiple_testing_ledger[
            "total_hypothesis_count"
        ],
        "false_discovery_warning_count": len(false_discovery_warnings),
        "price_zone_replay_count": len(price_zone_replay),
        "price_zone_replay_scorecard_rows": len(price_zone_replay_scorecard),
        "historical_wave_evidence_counts": dict(
            sorted(
                Counter(
                    row["evidence_classification"]
                    for row in wave_experiment_scorecard
                ).items()
            )
        ),
        "historical_wave_directional_counts": dict(
            sorted(
                Counter(
                    row["directional_evidence_classification"]
                    for row in wave_experiment_scorecard
                ).items()
            )
        ),
        "conditional_wave_evidence_counts": dict(
            sorted(
                Counter(
                    row["evidence_classification"]
                    for row in wave_conditional_scorecard
                ).items()
            )
        ),
        "conditional_wave_directional_counts": dict(
            sorted(
                Counter(
                    row["directional_evidence_classification"]
                    for row in wave_conditional_scorecard
                ).items()
            )
        ),
        "fundamental_coverage": {
            "quality": coverage["quality_coverage_rate"],
            "valuation": coverage["valuation_coverage_rate"],
            "revisions": coverage["revisions_coverage_rate"],
            "v3_buy_ready_count": len(coverage["v3_buy_ready_symbols"]),
        },
        "warnings": warnings,
        "artifacts": {
            name: str(path)
            for name, path in paths.items()
            if name != "manifest" and path.exists()
        },
    }
    _write_json(manifest, paths["manifest"])
    return manifest
