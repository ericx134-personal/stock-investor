from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path

from .dashboard import build_dashboard, write_dashboard
from .data import load_positions, load_prices
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
from .monitor import (
    run_monitor,
    write_alert_history,
    write_decision_history,
    write_monitor_snapshot,
)
from .risk import analyze_portfolio_risk, load_risk_policy, write_portfolio_risk_history
from .robinhood import load_robinhood_cash
from .thesis import load_theses
from .wave import (
    append_directional_forecast_history,
    append_wave_history,
    build_directional_forecasts,
    build_wave_conditional_scorecard,
    build_wave_scorecard,
    build_wave_walk_forward_outcomes,
    build_wave_walk_forward_scorecard,
    calculate_waves,
    evaluate_wave_history,
    load_wave_history,
    load_directional_forecast_history,
    write_wave_snapshot,
)


def _write_json(payload: object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


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
        "direction_forecasts": output_dir / "wave-direction-forecasts.jsonl",
        "direction_forecast_outcomes": output_dir / "wave-direction-forecast-outcomes.json",
        "direction_forecast_scorecard": output_dir / "wave-direction-forecast-scorecard.json",
        "comparison": output_dir / f"model-v1-{slug.removeprefix('model-')}-comparison.json",
        "dashboard": output_dir / f"dashboard-{slug.removeprefix('model-')}.html",
        "manifest": output_dir / "refresh-manifest.json",
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
    price_adjustment: str | None = None,
) -> dict:
    """Refresh all read-only decision-support artifacts, writing the manifest last."""
    started_at = datetime.now(timezone.utc)
    output_dir = Path(output_dir)
    paths = _artifact_paths(output_dir, model_version)
    positions = load_positions(positions_path)
    held_symbols = {position.symbol for position in positions if position.shares > 0}
    prices = load_prices(prices_path)
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
    _write_json(wave_experiment_outcomes, paths["wave_experiment_outcomes"])
    _write_json(wave_experiment_scorecard, paths["wave_experiment_scorecard"])
    _write_json(wave_conditional_scorecard, paths["wave_conditional_scorecard"])
    direction_forecasts = build_directional_forecasts(
        waves,
        held_symbols,
        wave_experiment_scorecard,
        wave_conditional_scorecard,
        prices,
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
    _write_json(
        direction_forecast_outcomes, paths["direction_forecast_outcomes"]
    )
    _write_json(
        direction_forecast_scorecard, paths["direction_forecast_scorecard"]
    )

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
            direction_forecast_scorecard_path=paths["direction_forecast_scorecard"],
            model_health_path=paths["model_health"],
            price_health_path=paths["price_health"],
            prices_path=prices_path,
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
    manifest = {
        "status": model_health["overall_status"],
        "model_health": model_health,
        "read_only": True,
        "model_version": model_version,
        "started_at": started_at.isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "latest_price_date": latest_price_date.isoformat() if latest_price_date else None,
        "position_count": len(positions),
        "held_position_count": len(held_symbols),
        "missing_price_symbols": missing_prices,
        "price_health_status_counts": price_health["status_counts"],
        "price_source": price_health["source"],
        "symbols_with_missing_sessions": price_health["symbols_with_missing_sessions"],
        "symbols_with_suspicious_ohlcv": price_health["symbols_with_suspicious_ohlcv"],
        "symbols_with_suspicious_close_gaps": price_health["symbols_with_suspicious_close_gaps"],
        "symbols_with_possible_splits": price_health["symbols_with_possible_splits"],
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
