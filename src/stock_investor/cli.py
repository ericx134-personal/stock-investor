from __future__ import annotations

import argparse
import json
import os
from contextlib import nullcontext
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError

from .backtest import (
    backtest_trend_momentum,
    backtest_trend_momentum_oos,
    write_oos_report,
)
from .archive import archive_private_artifacts, verify_private_archive
from .brief import build_brief, write_brief
from .data import load_positions, load_prices
from .dashboard import build_dashboard, write_dashboard
from .diagnostics import (
    assess_refresh_staleness,
    analyze_fundamental_coverage,
    compare_monitor_files,
    diagnose_alert_file,
)
from .evaluation import (
    build_scorecard,
    evaluate_alerts,
    load_alert_records,
    write_outcomes,
    write_scorecard,
)
from .feedback import (
    FEEDBACK_LABELS,
    FEEDBACK_RESPONSES,
    append_feedback,
    load_latest_feedback,
)
from .fundamentals import (
    calculate_fundamentals,
    load_fundamentals,
    write_fundamentals,
)
from .filings import append_filing_alerts, extract_recent_filings, update_filing_state
from .io import atomic_write_text
from .model import MODEL_POLICIES, MODEL_VERSION
from .monitor import run_monitor, write_alert_history, write_monitor_snapshot
from .providers.alpaca import fetch_daily_bars, write_prices_csv
from .providers.robinhood import extract_historicals_from_session, load_historical_response
from .providers.sec import fetch_company_facts, fetch_submissions, fetch_ticker_ciks
from .providers.yahoo import (
    fetch_yahoo_daily_bars,
    fetch_yahoo_latest_quotes,
    merge_price_histories,
)
from .refresh import refresh_lock, run_refresh, validate_production_refresh
from .risk import analyze_portfolio_risk, load_risk_policy, write_portfolio_risk_history
from .robinhood import (
    import_robinhood_snapshot,
    load_robinhood_cash,
    sanitize_robinhood_snapshot,
    write_robinhood_baseline,
    write_robinhood_import,
)
from .scoring import SignalSnapshot, evaluate
from .thesis import load_theses


def _print_alert(symbol: str, action: str, score: float, reasons: tuple[str, ...]) -> None:
    print(f"{symbol}: {action} (score {score:+.2f})")
    for reason in reasons:
        print(f"  - {reason}")


def _cash_balance(explicit_cash: float, account_summary_path: str | None) -> float:
    if explicit_cash and account_summary_path:
        raise SystemExit("use either --cash or --account-summary, not both")
    return (
        load_robinhood_cash(account_summary_path)
        if account_summary_path
        else explicit_cash
    )


def _score_snapshots(path: str, model_version: str) -> int:
    snapshots = json.loads(Path(path).read_text())
    alerts = [
        evaluate(SignalSnapshot(**item), MODEL_POLICIES[model_version])
        for item in snapshots
    ]
    for alert in alerts:
        _print_alert(alert.symbol, alert.action, alert.score, alert.reasons)
    return 0


def _monitor(
    positions_path: str,
    prices_path: str,
    history_path: str | None,
    cash_balance: float,
    fundamentals_path: str | None,
    risk_history_path: str | None,
    risk_policy_path: str | None,
    theses_path: str | None,
    model_version: str,
    snapshot_path: str | None,
) -> int:
    positions = load_positions(positions_path)
    prices = load_prices(prices_path)
    fundamentals = load_fundamentals(fundamentals_path) if fundamentals_path else None
    theses = load_theses(theses_path) if theses_path else None
    risk_policy = load_risk_policy(risk_policy_path) if risk_policy_path else None
    portfolio_risk = analyze_portfolio_risk(
        positions, prices, cash_balance, risk_policy
    ) if risk_policy else analyze_portfolio_risk(positions, prices, cash_balance)
    results = run_monitor(
        positions,
        prices,
        cash_balance,
        fundamentals,
        portfolio_risk,
        theses,
        model_version,
    )
    for result in results:
        close = "missing" if result.latest_close is None else f"${result.latest_close:,.2f}"
        gain = (
            ""
            if result.unrealized_return is None
            else f" | since average cost {result.unrealized_return:+.1%}"
        )
        print(
            f"\n{result.symbol} | close {close} | "
            f"portfolio {result.portfolio_weight:.1%}{gain}"
        )
        _print_alert(
            result.alert.symbol,
            result.alert.action,
            result.alert.score,
            result.alert.reasons,
        )
        if result.technicals:
            print(
                f"  - 200-day average: ${result.technicals.sma_200:,.2f}; "
                f"12-to-1 momentum: {result.technicals.return_12_to_1:+.1%}; "
                f"drawdown: {result.technicals.drawdown_from_high:.1%}"
            )
        if result.fundamentals:
            quality = (
                "missing"
                if result.fundamentals.quality is None
                else f"{result.fundamentals.quality:+.2f}"
            )
            valuation = (
                "missing"
                if result.fundamentals.valuation is None
                else f"{result.fundamentals.valuation:+.2f}"
            )
            print(
                f"  - SEC fundamentals: quality {quality}; valuation {valuation}; filed "
                f"{result.fundamentals.filed_at or 'unknown'}"
            )
        if result.risk:
            volatility = (
                "missing"
                if result.risk.annualized_volatility is None
                else f"{result.risk.annualized_volatility:.1%}"
            )
            suggested = (
                "missing"
                if result.risk.suggested_max_weight is None
                else f"{result.risk.suggested_max_weight:.1%}"
            )
            print(
                f"  - Risk sizing: annualized volatility {volatility}; "
                f"suggested max weight {suggested}"
            )
            for warning in result.risk.warnings:
                print(f"  - Risk data warning: {warning}")
        if result.thesis:
            print(
                f"  - Thesis: {result.thesis.status}; "
                f"broken={result.thesis.broken}; review_due={result.thesis.review_due}"
            )
            for warning in result.thesis.warnings:
                print(f"  - Thesis warning: {warning}")
    if portfolio_risk.alerts:
        print("\nPortfolio risk alerts:")
        for alert in portfolio_risk.alerts:
            print(f"  - [{alert.severity}] {alert.message}")
    else:
        print("\nNo configured portfolio-level risk limit is breached.")
    print(
        f"\nPortfolio gross exposure: {portfolio_risk.gross_exposure:.1%}; "
        f"cash weight: {portfolio_risk.cash_weight:.1%}"
    )
    if portfolio_risk.factor_exposures:
        print("\nPortfolio factor exposures:")
        for name, exposure in sorted(portfolio_risk.factor_exposures.items()):
            print(f"  - {name}: beta {exposure:+.2f}")
    if history_path:
        write_alert_history(results, history_path, model_version)
        print(f"\nAppended actionable alerts to {history_path}")
    if snapshot_path:
        write_monitor_snapshot(results, snapshot_path, model_version)
        print(f"Wrote full {model_version} monitor snapshot to {snapshot_path}")
    if risk_history_path:
        write_portfolio_risk_history(portfolio_risk, risk_history_path)
        print(f"Appended portfolio risk alerts to {risk_history_path}")
    return 0


def _fetch_alpaca(
    positions_path: str,
    output_path: str,
    start: str,
    end: str,
    feed: str,
    extra_symbols: tuple[str, ...] = (),
) -> int:
    key_id = os.environ.get("APCA_API_KEY_ID")
    secret_key = os.environ.get("APCA_API_SECRET_KEY")
    if not key_id or not secret_key:
        raise SystemExit(
            "APCA_API_KEY_ID and APCA_API_SECRET_KEY environment variables are required"
        )
    symbols = [position.symbol for position in load_positions(positions_path)]
    symbols.extend(symbol.upper() for symbol in extra_symbols if symbol)
    prices = fetch_daily_bars(symbols, start, end, key_id, secret_key, feed)
    write_prices_csv(prices, output_path)
    print(f"Wrote {sum(map(len, prices.values()))} adjusted daily bars to {output_path}")
    return 0


def _fetch_yahoo(
    positions_path: str,
    output_path: str,
    start: str,
    end: str,
    extra_symbols: tuple[str, ...] = (),
    merge_existing_path: str | None = None,
) -> int:
    symbols = [position.symbol for position in load_positions(positions_path)]
    symbols.extend(symbol.upper() for symbol in extra_symbols if symbol)
    failures = []
    updates = fetch_yahoo_daily_bars(
        symbols,
        start,
        end,
        on_failure=failures.append,
    )
    prices = (
        merge_price_histories(
            load_prices(merge_existing_path, strict_ohlcv=False),
            updates,
        )
        if merge_existing_path and Path(merge_existing_path).exists()
        else updates
    )
    write_prices_csv(prices, output_path)
    for failure in failures:
        outcome = "retrying" if failure.will_retry else "final"
        print(
            f"Yahoo provider {outcome} failure for {failure.symbol}: "
            f"{failure.failure_class}; attempt {failure.attempt}/{failure.max_attempts}; "
            f"retryable={str(failure.retryable).lower()}; {failure.message}",
            flush=True,
        )
    missing = sorted(set(symbols) - set(updates))
    if missing:
        print(
            "Yahoo missing latest bars for: " + ", ".join(missing),
            flush=True,
        )
    print(f"Wrote {sum(map(len, prices.values()))} Yahoo daily bars to {output_path}")
    return 0


def _fetch_yahoo_quotes(
    positions_path: str,
    output_path: str,
    extra_symbols: tuple[str, ...] = (),
) -> int:
    symbols = [position.symbol for position in load_positions(positions_path)]
    symbols.extend(symbol.upper() for symbol in extra_symbols if symbol)
    failures = []
    quotes = fetch_yahoo_latest_quotes(symbols, on_failure=failures.append)
    atomic_write_text(json.dumps(quotes, indent=2, sort_keys=True) + "\n", output_path)
    for failure in failures:
        outcome = "retrying" if failure.will_retry else "final"
        print(
            f"Yahoo quote {outcome} failure for {failure.symbol}: "
            f"{failure.failure_class}; attempt {failure.attempt}/{failure.max_attempts}; "
            f"retryable={str(failure.retryable).lower()}; {failure.message}",
            flush=True,
        )
    missing = sorted(set(symbols) - set(quotes))
    if missing:
        print("Yahoo missing latest quotes for: " + ", ".join(missing), flush=True)
    print(f"Wrote {len(quotes)} Yahoo latest quotes to {output_path}")
    return 0


def _daily(
    positions_path: str,
    prices_path: str,
    history_path: str,
    start: str,
    end: str,
    feed: str,
    cash_balance: float,
    fundamentals_path: str | None,
    refresh_sec: bool,
    filing_state_path: str | None,
    filing_alerts_path: str | None,
    risk_history_path: str | None,
    risk_policy_path: str | None,
    theses_path: str | None,
    outcomes_path: str | None,
    scorecard_path: str | None,
    benchmark_symbol: str | None,
    episode_sessions: int,
    feedback_path: str | None,
    brief_output_path: str | None,
    brief_period: str,
    model_version: str,
    snapshot_path: str | None,
) -> int:
    extra_symbols = [benchmark_symbol] if benchmark_symbol else []
    if risk_policy_path:
        extra_symbols.extend(load_risk_policy(risk_policy_path).factor_proxies.values())
    _fetch_alpaca(
        positions_path,
        prices_path,
        start,
        end,
        feed,
        tuple(extra_symbols),
    )
    if refresh_sec:
        if not fundamentals_path:
            raise SystemExit("--refresh-sec requires --fundamentals OUTPUT.json")
        _fetch_sec(positions_path, prices_path, fundamentals_path)
    result = _monitor(
        positions_path,
        prices_path,
        history_path,
        cash_balance,
        fundamentals_path,
        risk_history_path,
        risk_policy_path,
        theses_path,
        model_version,
        snapshot_path,
    )
    if filing_state_path:
        _check_filings(positions_path, filing_state_path, filing_alerts_path)
    if outcomes_path:
        _evaluate_alert_history(
            history_path,
            prices_path,
            outcomes_path,
            scorecard_path,
            benchmark_symbol,
            episode_sessions,
            feedback_path,
        )
    if brief_output_path:
        _brief(
            brief_output_path,
            brief_period,
            history_path,
            risk_history_path,
            filing_alerts_path,
            feedback_path,
        )
    return result


def _fetch_sec(positions_path: str, prices_path: str, output_path: str) -> int:
    user_agent = os.environ.get("SEC_USER_AGENT")
    if not user_agent:
        raise SystemExit(
            "SEC_USER_AGENT is required, for example 'stock-investor you@example.com'"
        )
    positions = load_positions(positions_path)
    prices = load_prices(prices_path)
    output = Path(output_path)
    snapshots = load_fundamentals(output) if output.exists() else {}
    refreshed = 0
    skipped = 0
    ticker_ciks = fetch_ticker_ciks(user_agent)
    for position in positions:
        cik = position.cik or ticker_ciks.get(position.symbol)
        if not cik:
            print(f"Skipping {position.symbol}: SEC ticker-to-CIK mapping unavailable")
            skipped += 1
            continue
        history = prices.get(position.symbol, [])
        if not history:
            print(f"Skipping {position.symbol}: no market price")
            skipped += 1
            continue
        time.sleep(0.12)
        try:
            payload = fetch_company_facts(cik, user_agent)
            snapshots[position.symbol] = calculate_fundamentals(
                position.symbol, cik, payload, history[-1].close
            )
            refreshed += 1
        except (HTTPError, URLError, TimeoutError, ValueError) as error:
            skipped += 1
            print(
                f"Skipping {position.symbol}: SEC refresh failed "
                f"({type(error).__name__}: {error})"
            )
    write_fundamentals(snapshots, output)
    print(
        f"Refreshed {refreshed} SEC snapshots; preserved {len(snapshots)} total "
        f"at {output_path}; skipped {skipped}"
    )
    return 0


def _check_filings(
    positions_path: str, state_path: str, alerts_path: str | None
) -> int:
    user_agent = os.environ.get("SEC_USER_AGENT")
    if not user_agent:
        raise SystemExit(
            "SEC_USER_AGENT is required, for example 'stock-investor you@example.com'"
        )
    ticker_ciks = fetch_ticker_ciks(user_agent)
    events = []
    for position in load_positions(positions_path):
        cik = position.cik or ticker_ciks.get(position.symbol)
        if not cik:
            print(f"Skipping {position.symbol}: SEC ticker-to-CIK mapping unavailable")
            continue
        time.sleep(0.12)
        events.extend(
            extract_recent_filings(
                position.symbol, cik, fetch_submissions(cik, user_agent)
            )
        )
    unseen = update_filing_state(events, state_path)
    for event in unseen:
        categories = ", ".join(event.event_categories)
        items = f" | items {', '.join(event.items)}" if event.items else ""
        print(
            f"{event.symbol}: [{event.importance}] NEW {event.form} filed "
            f"{event.filed_at} | {categories}{items} | {event.url}"
        )
    if alerts_path:
        append_filing_alerts(unseen, alerts_path)
    if not unseen:
        print("No new monitored SEC filings.")
    return 0


def _backtest(prices_path: str, costs: float) -> int:
    for symbol, history in load_prices(prices_path).items():
        result = backtest_trend_momentum(
            symbol, history, transaction_cost_bps=costs
        )
        print(
            f"{symbol}: strategy {result.strategy_return:+.1%} | "
            f"buy-and-hold {result.buy_and_hold_return:+.1%} | "
            f"max drawdown {result.max_drawdown:.1%} | "
            f"trades {result.trades} | exposure {result.exposure:.1%}"
        )
    return 0


def _backtest_oos(
    prices_path: str,
    output_path: str,
    test_start: str,
    test_end: str | None,
    costs: float,
    rebalance_days: int,
) -> int:
    start = date.fromisoformat(test_start)
    end = date.fromisoformat(test_end) if test_end else None
    results = [
        backtest_trend_momentum_oos(
            symbol,
            history,
            start,
            end,
            rebalance_days,
            costs,
        )
        for symbol, history in load_prices(prices_path).items()
    ]
    write_oos_report(results, output_path, start, end, rebalance_days, costs)
    for result in results:
        print(
            f"{result.symbol}: OOS {result.start_date} to {result.end_date} | "
            f"strategy {result.strategy_return:+.1%} | "
            f"buy-and-hold {result.buy_and_hold_return:+.1%} | "
            f"max drawdown {result.max_drawdown:.1%} | trades {result.trades}"
        )
    print(f"Wrote sealed out-of-sample report to {output_path}")
    return 0


def _evaluate_alert_history(
    alerts_path: str,
    prices_path: str,
    outcomes_path: str,
    scorecard_path: str | None,
    benchmark_symbol: str | None,
    episode_sessions: int,
    feedback_path: str | None,
) -> int:
    outcomes = evaluate_alerts(
        load_alert_records(alerts_path),
        load_prices(prices_path),
        benchmark_symbol.upper() if benchmark_symbol else None,
        episode_sessions,
        load_latest_feedback(feedback_path) if feedback_path else None,
    )
    write_outcomes(outcomes, outcomes_path)
    print(f"Wrote {len(outcomes)} alert outcomes to {outcomes_path}")
    scorecard = build_scorecard(outcomes)
    if scorecard_path:
        write_scorecard(scorecard, scorecard_path)
        print(f"Wrote {len(scorecard)} scorecard rows to {scorecard_path}")
    for row in scorecard:
        mean = "pending" if row.mean_return is None else f"{row.mean_return:+.1%}"
        directional = (
            "pending"
            if row.mean_directional_return is None
            else f"{row.mean_directional_return:+.1%}"
        )
        success = (
            "pending"
            if row.directional_success_rate is None
            else f"{row.directional_success_rate:.1%}"
        )
        helpful = (
            "unrated"
            if row.helpful_rate is None
            else f"{row.helpful_rate:.1%} ({row.feedback_observations})"
        )
        acted = "unrated" if row.acted_rate is None else f"{row.acted_rate:.1%}"
        print(
            f"{row.model_version} | {row.action} | {row.horizon} | "
            f"n={row.observations} | mean {mean} | directional {directional} | "
            f"success {success} | helpful {helpful} | acted {acted}"
        )
    return 0


def _record_feedback(
    alerts_path: str,
    feedback_path: str,
    alert_id: str,
    label: str,
    response: str,
    note: str,
) -> int:
    feedback = append_feedback(
        alerts_path, feedback_path, alert_id, label, response, note
    )
    print(
        f"Recorded {feedback.label} feedback for {feedback.alert_id} "
        f"with response {feedback.response}"
    )
    return 0


def _list_alerts(alerts_path: str, feedback_path: str | None, limit: int) -> int:
    if limit < 1:
        raise SystemExit("--limit must be at least 1")
    records = [
        record
        for record in load_alert_records(alerts_path)
        if record.get("alert_id")
    ]
    feedback = load_latest_feedback(feedback_path) if feedback_path else {}
    for record in reversed(records[-limit:]):
        alert = record.get("alert", {})
        score = alert.get("score")
        score_text = "missing" if score is None else f"{float(score):+.2f}"
        review = feedback.get(record["alert_id"])
        review_text = (
            "unrated" if review is None else f"{review.label}/{review.response}"
        )
        print(
            f"{record['alert_id']} | {record.get('signal_date', 'unknown')} | "
            f"{record.get('symbol', 'unknown')} | "
            f"{alert.get('action', 'unknown')} | score {score_text} | {review_text}"
        )
    if not records:
        print("No model-versioned alerts are available.")
    return 0


def _brief(
    output_path: str,
    period: str,
    alerts_path: str | None,
    risk_path: str | None,
    filings_path: str | None,
    feedback_path: str | None,
) -> int:
    days = 1 if period == "daily" else 7
    content = build_brief(
        days, alerts_path, risk_path, filings_path, feedback_path
    )
    write_brief(content, output_path)
    print(content, end="")
    print(f"\nWrote {period} brief to {output_path}")
    return 0


def _import_robinhood(
    snapshot_path: str,
    positions_path: str,
    summary_path: str,
    metadata_path: str | None,
    default_max_weight: float,
    baseline_path: str | None,
) -> int:
    positions, summary = import_robinhood_snapshot(
        snapshot_path, metadata_path, default_max_weight
    )
    write_robinhood_import(positions, summary, positions_path, summary_path)
    baseline_written = (
        write_robinhood_baseline(positions, summary, baseline_path)
        if baseline_path
        else False
    )
    print(
        f"Imported {summary.position_count} held symbols across "
        f"{summary.account_count} Robinhood accounts to {positions_path}"
    )
    print(
        f"Sanitized summary: cash ${summary.total_cash:,.2f}; "
        f"buying power ${summary.total_buying_power:,.2f}"
    )
    if summary.skipped_non_equity_positions:
        print(
            f"Skipped {summary.skipped_non_equity_positions} non-equity positions."
        )
    if baseline_path:
        status = "Appended" if baseline_written else "Unchanged"
        print(f"{status} privacy-safe portfolio baseline at {baseline_path}")
    return 0


def _sanitize_robinhood(input_path: str, output_path: str) -> int:
    payload = json.loads(Path(input_path).read_text())
    sanitized = sanitize_robinhood_snapshot(payload)
    atomic_write_text(json.dumps(sanitized, indent=2, sort_keys=True) + "\n", output_path)
    print(f"Wrote privacy-safe Robinhood snapshot to {output_path}")
    return 0


def _import_robinhood_prices(input_path: str, output_path: str) -> int:
    prices = load_historical_response(input_path)
    write_prices_csv(prices, output_path)
    print(
        f"Wrote {sum(map(len, prices.values()))} Robinhood daily bars "
        f"for {len(prices)} symbols to {output_path}"
    )
    return 0


def _extract_robinhood_prices(session_path: str, output_path: str) -> int:
    prices = extract_historicals_from_session(session_path)
    write_prices_csv(prices, output_path)
    print(
        f"Extracted {sum(map(len, prices.values()))} Robinhood daily bars "
        f"for {len(prices)} symbols to {output_path}"
    )
    return 0


def _diagnose_alerts(alerts_path: str, output_path: str | None) -> int:
    report = diagnose_alert_file(alerts_path)
    content = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if output_path:
        atomic_write_text(content, output_path)
        print(f"Wrote alert-burden diagnostic to {output_path}")
    print(content, end="")
    return 0


def _check_refresh(manifest_path: str, max_age_hours: float) -> int:
    report = assess_refresh_staleness(manifest_path, max_age_hours=max_age_hours)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["stale"] else 0


def _archive_private(source_dir: str, archive_dir: str | None, keep_days: int) -> int:
    report = archive_private_artifacts(source_dir, archive_dir, keep_days=keep_days)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _verify_private_archive(path: str) -> int:
    print(json.dumps(verify_private_archive(path), indent=2, sort_keys=True))
    return 0


def _compare_models(
    baseline_path: str, candidate_path: str, output_path: str | None
) -> int:
    report = compare_monitor_files(baseline_path, candidate_path)
    content = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if output_path:
        atomic_write_text(content, output_path)
        print(f"Wrote model-selectivity comparison to {output_path}")
    print(content, end="")
    return 0


def _diagnose_fundamentals(
    positions_path: str, fundamentals_path: str | None, output_path: str | None
) -> int:
    fundamentals = load_fundamentals(fundamentals_path) if fundamentals_path else None
    report = analyze_fundamental_coverage(load_positions(positions_path), fundamentals)
    content = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if output_path:
        atomic_write_text(content, output_path)
        print(f"Wrote fundamental-coverage diagnostic to {output_path}")
    print(content, end="")
    return 0


def _dashboard(
    alerts_path: str,
    output_path: str,
    risk_path: str | None,
    scorecard_path: str | None,
    decision_scorecard_path: str | None,
    comparison_path: str | None,
    fundamental_coverage_path: str | None,
    kline_scorecard_path: str | None,
    wave_snapshot_path: str | None,
    wave_scorecard_path: str | None,
    wave_experiment_scorecard_path: str | None,
    wave_conditional_scorecard_path: str | None,
    direction_forecasts_path: str | None,
    direction_forecast_outcomes_path: str | None,
    direction_forecast_scorecard_path: str | None,
    forecast_calibration_curves_path: str | None,
    direction_classification_metrics_path: str | None,
    direction_error_cohorts_path: str | None,
    model_health_path: str | None,
    price_health_path: str | None,
    prices_path: str | None,
    latest_quotes_path: str | None,
    account_summary_path: str | None,
) -> int:
    write_dashboard(
        build_dashboard(
            alerts_path,
            risk_path,
            scorecard_path,
            decision_scorecard_path=decision_scorecard_path,
            comparison_path=comparison_path,
            fundamental_coverage_path=fundamental_coverage_path,
            kline_scorecard_path=kline_scorecard_path,
            wave_snapshot_path=wave_snapshot_path,
            wave_scorecard_path=wave_scorecard_path,
            wave_experiment_scorecard_path=wave_experiment_scorecard_path,
            wave_conditional_scorecard_path=wave_conditional_scorecard_path,
            direction_forecasts_path=direction_forecasts_path,
            direction_forecast_outcomes_path=direction_forecast_outcomes_path,
            direction_forecast_scorecard_path=direction_forecast_scorecard_path,
            forecast_calibration_curves_path=forecast_calibration_curves_path,
            direction_classification_metrics_path=direction_classification_metrics_path,
            direction_error_cohorts_path=direction_error_cohorts_path,
            model_health_path=model_health_path,
            price_health_path=price_health_path,
            prices_path=prices_path,
            latest_quotes_path=latest_quotes_path,
            account_summary_path=account_summary_path,
        ),
        output_path,
    )
    print(f"Wrote read-only portfolio dashboard to {output_path}")
    return 0


def _refresh(
    positions_path: str,
    prices_path: str,
    output_dir: str,
    model_version: str,
    cash_balance: float,
    account_summary_path: str | None,
    fundamentals_path: str | None,
    risk_policy_path: str | None,
    theses_path: str | None,
    feedback_path: str | None,
    baseline_snapshot_path: str | None,
    benchmark_symbol: str | None,
    episode_sessions: int,
    price_source: str | None,
    latest_quotes_path: str | None,
    price_adjustment: str | None,
    production_safe: bool,
) -> int:
    if cash_balance and account_summary_path:
        raise SystemExit("use either --cash or --account-summary, not both")
    if production_safe:
        validate_production_refresh(
            output_dir,
            account_summary_path=account_summary_path,
            price_source=price_source,
            price_adjustment=price_adjustment,
        )
    lock = refresh_lock(output_dir) if production_safe else nullcontext()
    with lock:
        manifest = run_refresh(
            positions_path,
            prices_path,
            output_dir,
            model_version,
            cash_balance=cash_balance,
            account_summary_path=account_summary_path,
            fundamentals_path=fundamentals_path,
            risk_policy_path=risk_policy_path,
            theses_path=theses_path,
            feedback_path=feedback_path,
            baseline_snapshot_path=baseline_snapshot_path,
            benchmark_symbol=benchmark_symbol,
            episode_sessions=episode_sessions,
            price_source=price_source,
            latest_quotes_path=latest_quotes_path,
            price_adjustment=price_adjustment,
        )
    print(
        f"Refresh {manifest['status']}: {manifest['position_count']} positions; "
        f"latest prices {manifest['latest_price_date'] or 'unavailable'}; "
        f"action-review rate {manifest['actionable_rate']:.0%}"
    )
    for warning in manifest["warnings"]:
        print(f"  - {warning}")
    print(f"Wrote refresh manifest to {Path(output_dir) / 'refresh-manifest.json'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Evidence-based portfolio monitor")
    subparsers = parser.add_subparsers(dest="command", required=True)

    score_parser = subparsers.add_parser("score", help="score normalized snapshots")
    score_parser.add_argument("snapshot")
    score_parser.add_argument(
        "--model-version", choices=tuple(MODEL_POLICIES), default=MODEL_VERSION
    )

    monitor_parser = subparsers.add_parser(
        "monitor", help="calculate signals and monitor a portfolio"
    )
    monitor_parser.add_argument("positions")
    monitor_parser.add_argument("prices")
    monitor_parser.add_argument("--history", help="append actionable alerts to JSONL")
    monitor_parser.add_argument("--cash", type=float, default=0.0)
    monitor_parser.add_argument("--account-summary")
    monitor_parser.add_argument("--fundamentals")
    monitor_parser.add_argument("--risk-history")
    monitor_parser.add_argument("--risk-policy")
    monitor_parser.add_argument("--theses")
    monitor_parser.add_argument(
        "--model-version", choices=tuple(MODEL_POLICIES), default=MODEL_VERSION
    )
    monitor_parser.add_argument("--snapshot", help="write full current monitor state")

    fetch_parser = subparsers.add_parser(
        "fetch-alpaca", help="fetch adjusted daily prices from Alpaca"
    )
    fetch_parser.add_argument("positions")
    fetch_parser.add_argument("output")
    fetch_parser.add_argument(
        "--start", default=(date.today() - timedelta(days=730)).isoformat()
    )
    fetch_parser.add_argument("--end", default=date.today().isoformat())
    fetch_parser.add_argument("--feed", choices=("iex", "sip"), default="iex")
    fetch_parser.add_argument("--extra-symbol", action="append", default=[])

    yahoo_parser = subparsers.add_parser(
        "fetch-yahoo", help="fetch daily prices from Yahoo Finance chart data"
    )
    yahoo_parser.add_argument("positions")
    yahoo_parser.add_argument("output")
    yahoo_parser.add_argument(
        "--start", default=(date.today() - timedelta(days=730)).isoformat()
    )
    yahoo_parser.add_argument(
        "--end", default=(date.today() + timedelta(days=1)).isoformat()
    )
    yahoo_parser.add_argument("--extra-symbol", action="append", default=[])
    yahoo_parser.add_argument("--merge-existing")

    yahoo_quotes_parser = subparsers.add_parser(
        "fetch-yahoo-quotes", help="fetch latest no-credential quotes from Yahoo chart data"
    )
    yahoo_quotes_parser.add_argument("positions")
    yahoo_quotes_parser.add_argument("output")
    yahoo_quotes_parser.add_argument("--extra-symbol", action="append", default=[])

    daily_parser = subparsers.add_parser(
        "daily", help="fetch prices, monitor, and persist actionable alerts"
    )
    daily_parser.add_argument("positions")
    daily_parser.add_argument("prices")
    daily_parser.add_argument("--history", default="data/alerts.jsonl")
    daily_parser.add_argument(
        "--start", default=(date.today() - timedelta(days=730)).isoformat()
    )
    daily_parser.add_argument("--end", default=date.today().isoformat())
    daily_parser.add_argument("--feed", choices=("iex", "sip"), default="iex")
    daily_parser.add_argument("--cash", type=float, default=0.0)
    daily_parser.add_argument("--account-summary")
    daily_parser.add_argument("--fundamentals")
    daily_parser.add_argument("--refresh-sec", action="store_true")
    daily_parser.add_argument("--filing-state")
    daily_parser.add_argument("--filing-alerts")
    daily_parser.add_argument("--risk-history")
    daily_parser.add_argument("--risk-policy")
    daily_parser.add_argument("--theses")
    daily_parser.add_argument("--outcomes")
    daily_parser.add_argument("--scorecard")
    daily_parser.add_argument("--benchmark")
    daily_parser.add_argument("--episode-sessions", type=int, default=21)
    daily_parser.add_argument("--feedback")
    daily_parser.add_argument("--brief-output")
    daily_parser.add_argument(
        "--brief-period", choices=("daily", "weekly"), default="daily"
    )
    daily_parser.add_argument(
        "--model-version", choices=tuple(MODEL_POLICIES), default=MODEL_VERSION
    )
    daily_parser.add_argument("--snapshot", help="write full current monitor state")

    sec_parser = subparsers.add_parser(
        "fetch-sec", help="calculate fundamental scores from SEC Company Facts"
    )
    sec_parser.add_argument("positions")
    sec_parser.add_argument("prices")
    sec_parser.add_argument("output")

    filings_parser = subparsers.add_parser(
        "check-filings", help="alert on newly filed 10-K, 10-Q, and 8-K reports"
    )
    filings_parser.add_argument("positions")
    filings_parser.add_argument("state")
    filings_parser.add_argument("--alerts")

    backtest_parser = subparsers.add_parser(
        "backtest", help="walk-forward test the initial trend-momentum rule"
    )
    backtest_parser.add_argument("prices")
    backtest_parser.add_argument("--cost-bps", type=float, default=10.0)

    oos_parser = subparsers.add_parser(
        "backtest-oos", help="run a predeclared dedicated out-of-sample evaluation"
    )
    oos_parser.add_argument("prices")
    oos_parser.add_argument("output")
    oos_parser.add_argument("--test-start", required=True)
    oos_parser.add_argument("--test-end")
    oos_parser.add_argument("--cost-bps", type=float, default=10.0)
    oos_parser.add_argument("--rebalance-days", type=int, default=21)

    evaluate_parser = subparsers.add_parser(
        "evaluate-alerts", help="measure forward outcomes of recorded alerts"
    )
    evaluate_parser.add_argument("alerts")
    evaluate_parser.add_argument("prices")
    evaluate_parser.add_argument("outcomes")
    evaluate_parser.add_argument("--benchmark")
    evaluate_parser.add_argument("--scorecard")
    evaluate_parser.add_argument("--episode-sessions", type=int, default=21)
    evaluate_parser.add_argument("--feedback")

    feedback_parser = subparsers.add_parser(
        "feedback", help="record append-only feedback for an alert"
    )
    feedback_parser.add_argument("alerts")
    feedback_parser.add_argument("feedback")
    feedback_parser.add_argument("alert_id")
    feedback_parser.add_argument("--label", required=True, choices=FEEDBACK_LABELS)
    feedback_parser.add_argument(
        "--response", choices=FEEDBACK_RESPONSES, default="NO_ACTION"
    )
    feedback_parser.add_argument("--note", default="")

    list_alerts_parser = subparsers.add_parser(
        "list-alerts", help="list recent alerts and their latest feedback"
    )
    list_alerts_parser.add_argument("alerts")
    list_alerts_parser.add_argument("--feedback")
    list_alerts_parser.add_argument("--limit", type=int, default=20)

    brief_parser = subparsers.add_parser(
        "brief", help="write a concise daily or weekly portfolio brief"
    )
    brief_parser.add_argument("output")
    brief_parser.add_argument("--period", choices=("daily", "weekly"), default="daily")
    brief_parser.add_argument("--alerts")
    brief_parser.add_argument("--risk-history")
    brief_parser.add_argument("--filing-alerts")
    brief_parser.add_argument("--feedback")

    robinhood_parser = subparsers.add_parser(
        "import-robinhood",
        help="convert a sanitized read-only Robinhood MCP snapshot",
    )
    robinhood_parser.add_argument("snapshot")
    robinhood_parser.add_argument("positions")
    robinhood_parser.add_argument("summary")
    robinhood_parser.add_argument("--metadata")
    robinhood_parser.add_argument("--default-max-weight", type=float, default=0.10)
    robinhood_parser.add_argument("--baseline-history")

    sanitize_robinhood_parser = subparsers.add_parser(
        "sanitize-robinhood",
        help="whitelist a combined Robinhood read-only snapshot before persistence",
    )
    sanitize_robinhood_parser.add_argument("input")
    sanitize_robinhood_parser.add_argument("output")

    robinhood_prices_parser = subparsers.add_parser(
        "import-robinhood-prices",
        help="convert an exported Robinhood MCP daily historical response",
    )
    robinhood_prices_parser.add_argument("input")
    robinhood_prices_parser.add_argument("output")

    extract_robinhood_prices_parser = subparsers.add_parser(
        "extract-robinhood-prices",
        help="extract structured Robinhood daily histories from a Codex session log",
    )
    extract_robinhood_prices_parser.add_argument("session")
    extract_robinhood_prices_parser.add_argument("output")

    diagnose_alerts_parser = subparsers.add_parser(
        "diagnose-alerts",
        help="measure selectivity and alert-fatigue risk from latest symbol alerts",
    )
    diagnose_alerts_parser.add_argument("alerts")
    diagnose_alerts_parser.add_argument("--output")

    compare_models_parser = subparsers.add_parser(
        "compare-models",
        help="compare alert selectivity from two full monitor snapshots",
    )
    compare_models_parser.add_argument("baseline")
    compare_models_parser.add_argument("candidate")
    compare_models_parser.add_argument("--output")

    diagnose_fundamentals_parser = subparsers.add_parser(
        "diagnose-fundamentals",
        help="measure effective fundamental coverage and buy-readiness gaps",
    )
    diagnose_fundamentals_parser.add_argument("positions")
    diagnose_fundamentals_parser.add_argument("--fundamentals")
    diagnose_fundamentals_parser.add_argument("--output")

    check_refresh_parser = subparsers.add_parser(
        "check-refresh", help="exit non-zero when a refresh manifest is missing or stale"
    )
    check_refresh_parser.add_argument("manifest")
    check_refresh_parser.add_argument("--max-age-hours", type=float, default=36)

    archive_parser = subparsers.add_parser(
        "archive-private",
        help="create a credential-free daily archive and prune expired archives",
    )
    archive_parser.add_argument("source_dir")
    archive_parser.add_argument("--archive-dir")
    archive_parser.add_argument("--keep-days", type=int, default=30)

    verify_archive_parser = subparsers.add_parser(
        "verify-private-archive",
        help="safely restore and validate a private artifact archive",
    )
    verify_archive_parser.add_argument("archive")

    dashboard_parser = subparsers.add_parser(
        "dashboard", help="generate a local read-only portfolio dashboard"
    )
    dashboard_parser.add_argument("alerts")
    dashboard_parser.add_argument("output")
    dashboard_parser.add_argument("--risk-history")
    dashboard_parser.add_argument("--scorecard")
    dashboard_parser.add_argument("--decision-scorecard")
    dashboard_parser.add_argument("--comparison")
    dashboard_parser.add_argument("--fundamental-coverage")
    dashboard_parser.add_argument("--kline-scorecard")
    dashboard_parser.add_argument("--wave-snapshot")
    dashboard_parser.add_argument("--wave-scorecard")
    dashboard_parser.add_argument("--wave-experiment-scorecard")
    dashboard_parser.add_argument("--wave-conditional-scorecard")
    dashboard_parser.add_argument("--direction-forecasts")
    dashboard_parser.add_argument("--direction-forecast-outcomes")
    dashboard_parser.add_argument("--direction-forecast-scorecard")
    dashboard_parser.add_argument("--forecast-calibration-curves")
    dashboard_parser.add_argument("--direction-classification-metrics")
    dashboard_parser.add_argument("--direction-error-cohorts")
    dashboard_parser.add_argument("--model-health")
    dashboard_parser.add_argument("--price-health")
    dashboard_parser.add_argument("--prices")
    dashboard_parser.add_argument("--latest-quotes")
    dashboard_parser.add_argument("--account-summary")

    refresh_parser = subparsers.add_parser(
        "refresh",
        help="run the complete read-only monitoring and evidence refresh pipeline",
    )
    refresh_parser.add_argument("positions")
    refresh_parser.add_argument("prices")
    refresh_parser.add_argument("output_dir")
    refresh_parser.add_argument(
        "--model-version",
        choices=tuple(MODEL_POLICIES),
        default="decision-support-v3",
    )
    refresh_parser.add_argument("--cash", type=float, default=0.0)
    refresh_parser.add_argument("--account-summary")
    refresh_parser.add_argument("--fundamentals")
    refresh_parser.add_argument("--risk-policy")
    refresh_parser.add_argument("--theses")
    refresh_parser.add_argument("--feedback")
    refresh_parser.add_argument("--baseline-snapshot")
    refresh_parser.add_argument("--benchmark", default="SPY")
    refresh_parser.add_argument("--episode-sessions", type=int, default=21)
    refresh_parser.add_argument("--price-source")
    refresh_parser.add_argument("--latest-quotes")
    refresh_parser.add_argument(
        "--price-adjustment",
        choices=("unknown", "none", "split", "all"),
    )
    refresh_parser.add_argument("--production-safe", action="store_true")

    args = parser.parse_args()
    if args.command == "score":
        return _score_snapshots(args.snapshot, args.model_version)
    if args.command == "monitor":
        return _monitor(
            args.positions,
            args.prices,
            args.history,
            _cash_balance(args.cash, args.account_summary),
            args.fundamentals,
            args.risk_history,
            args.risk_policy,
            args.theses,
            args.model_version,
            args.snapshot,
        )
    if args.command == "fetch-alpaca":
        return _fetch_alpaca(
            args.positions,
            args.output,
            args.start,
            args.end,
            args.feed,
            tuple(args.extra_symbol),
        )
    if args.command == "fetch-yahoo":
        return _fetch_yahoo(
            args.positions,
            args.output,
            args.start,
            args.end,
            tuple(args.extra_symbol),
            args.merge_existing,
        )
    if args.command == "fetch-yahoo-quotes":
        return _fetch_yahoo_quotes(
            args.positions,
            args.output,
            tuple(args.extra_symbol or ()),
        )
    if args.command == "daily":
        return _daily(
            args.positions,
            args.prices,
            args.history,
            args.start,
            args.end,
            args.feed,
            _cash_balance(args.cash, args.account_summary),
            args.fundamentals,
            args.refresh_sec,
            args.filing_state,
            args.filing_alerts,
            args.risk_history,
            args.risk_policy,
            args.theses,
            args.outcomes,
            args.scorecard,
            args.benchmark,
            args.episode_sessions,
            args.feedback,
            args.brief_output,
            args.brief_period,
            args.model_version,
            args.snapshot,
        )
    if args.command == "fetch-sec":
        return _fetch_sec(args.positions, args.prices, args.output)
    if args.command == "check-filings":
        return _check_filings(args.positions, args.state, args.alerts)
    if args.command == "backtest":
        return _backtest(args.prices, args.cost_bps)
    if args.command == "backtest-oos":
        return _backtest_oos(
            args.prices,
            args.output,
            args.test_start,
            args.test_end,
            args.cost_bps,
            args.rebalance_days,
        )
    if args.command == "evaluate-alerts":
        return _evaluate_alert_history(
            args.alerts,
            args.prices,
            args.outcomes,
            args.scorecard,
            args.benchmark,
            args.episode_sessions,
            args.feedback,
        )
    if args.command == "feedback":
        return _record_feedback(
            args.alerts,
            args.feedback,
            args.alert_id,
            args.label,
            args.response,
            args.note,
        )
    if args.command == "list-alerts":
        return _list_alerts(args.alerts, args.feedback, args.limit)
    if args.command == "brief":
        return _brief(
            args.output,
            args.period,
            args.alerts,
            args.risk_history,
            args.filing_alerts,
            args.feedback,
        )
    if args.command == "import-robinhood":
        return _import_robinhood(
            args.snapshot,
            args.positions,
            args.summary,
            args.metadata,
            args.default_max_weight,
            args.baseline_history,
        )
    if args.command == "sanitize-robinhood":
        return _sanitize_robinhood(args.input, args.output)
    if args.command == "import-robinhood-prices":
        return _import_robinhood_prices(args.input, args.output)
    if args.command == "extract-robinhood-prices":
        return _extract_robinhood_prices(args.session, args.output)
    if args.command == "diagnose-alerts":
        return _diagnose_alerts(args.alerts, args.output)
    if args.command == "compare-models":
        return _compare_models(args.baseline, args.candidate, args.output)
    if args.command == "diagnose-fundamentals":
        return _diagnose_fundamentals(
            args.positions, args.fundamentals, args.output
        )
    if args.command == "check-refresh":
        return _check_refresh(args.manifest, args.max_age_hours)
    if args.command == "archive-private":
        return _archive_private(args.source_dir, args.archive_dir, args.keep_days)
    if args.command == "verify-private-archive":
        return _verify_private_archive(args.archive)
    if args.command == "dashboard":
        return _dashboard(
            args.alerts,
            args.output,
            args.risk_history,
            args.scorecard,
            args.decision_scorecard,
            args.comparison,
            args.fundamental_coverage,
            args.kline_scorecard,
            args.wave_snapshot,
            args.wave_scorecard,
            args.wave_experiment_scorecard,
            args.wave_conditional_scorecard,
            args.direction_forecasts,
            args.direction_forecast_outcomes,
            args.direction_forecast_scorecard,
            args.forecast_calibration_curves,
            args.direction_classification_metrics,
            args.direction_error_cohorts,
            args.model_health,
            args.price_health,
            args.prices,
            args.latest_quotes,
            args.account_summary,
        )
    if args.command == "refresh":
        return _refresh(
            args.positions,
            args.prices,
            args.output_dir,
            args.model_version,
            args.cash,
            args.account_summary,
            args.fundamentals,
            args.risk_policy,
            args.theses,
            args.feedback,
            args.baseline_snapshot,
            args.benchmark,
            args.episode_sessions,
            args.price_source,
            args.latest_quotes,
            args.price_adjustment,
            args.production_safe,
        )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
