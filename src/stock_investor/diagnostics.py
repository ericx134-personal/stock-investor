from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path

from .data import Position, Price
from .fundamentals import FundamentalSnapshot


ACTIONABLE_ACTIONS = {"BUY_CANDIDATE", "ADD_CANDIDATE", "REVIEW", "TRIM_REVIEW"}


def infer_price_source(path: str | Path, declared_source: str | None = None) -> dict:
    if declared_source:
        return {"name": declared_source, "confidence": "DECLARED"}
    name = Path(path).name.lower()
    if "robinhood" in name:
        return {"name": "Robinhood MCP export", "confidence": "INFERRED"}
    if "alpaca" in name:
        return {"name": "Alpaca Market Data export", "confidence": "INFERRED"}
    return {"name": "CSV import", "confidence": "UNKNOWN"}


def build_price_health_report(
    prices: dict[str, list[Price]],
    symbols: set[str],
    *,
    as_of: date,
    source: dict,
    expected_sessions: set[date] | None = None,
    expected_session_source: str | None = None,
    fresh_days: int = 7,
) -> dict:
    recent_expected = set(sorted(expected_sessions or ())[-252:])
    rows = []
    for symbol in sorted(symbols):
        history = prices.get(symbol, [])
        latest = history[-1] if history else None
        age_days = (as_of - latest.date).days if latest else None
        ohlcv_rows = sum(
            item.open is not None
            and item.high is not None
            and item.low is not None
            and item.volume is not None
            for item in history
        )
        suspicious_range_dates = [
            item.date.isoformat()
            for item in history
            if item.high is not None
            and item.low is not None
            and item.low > 0
            and item.high / item.low - 1 > 0.5
        ]
        suspicious_close_gaps = []
        for previous, item in zip(history[:-1], history[1:]):
            move = item.close / previous.close - 1
            if abs(move) <= 0.4:
                continue
            intraday_range = (
                item.high / item.low - 1
                if item.high is not None and item.low is not None and item.low > 0
                else None
            )
            suspicious_close_gaps.append(
                {
                    "date": item.date.isoformat(),
                    "close_return": move,
                    "classification": (
                        "POSSIBLE_CORPORATE_ACTION"
                        if intraday_range is not None and intraday_range <= 0.2
                        else "EXTREME_MOVE"
                    ),
                }
            )
        status = (
            "MISSING"
            if latest is None
            else "FRESH" if age_days is not None and age_days <= fresh_days else "STALE"
        )
        observed_dates = {item.date for item in history}
        relevant_expected = {
            session
            for session in recent_expected
            if latest is not None and history[0].date <= session <= latest.date
        }
        missing_sessions = sorted(relevant_expected - observed_dates)
        rows.append(
            {
                "symbol": symbol,
                "status": status,
                "latest_date": latest.date.isoformat() if latest else None,
                "age_calendar_days": age_days,
                "history_rows": len(history),
                "ohlcv_coverage_rate": ohlcv_rows / len(history) if history else 0.0,
                "suspicious_intraday_range_count": len(suspicious_range_dates),
                "suspicious_intraday_range_dates": suspicious_range_dates[-10:],
                "suspicious_close_gap_count": len(suspicious_close_gaps),
                "suspicious_close_gaps": suspicious_close_gaps[-10:],
                "expected_session_count": len(relevant_expected),
                "missing_session_count": len(missing_sessions),
                "missing_session_dates": [item.isoformat() for item in missing_sessions[-10:]],
                "session_coverage_rate": (
                    1 - len(missing_sessions) / len(relevant_expected)
                    if relevant_expected
                    else None
                ),
                "source": source["name"],
                "source_confidence": source["confidence"],
            }
        )
    counts = Counter(row["status"] for row in rows)
    return {
        "schema_version": "price-health-v1",
        "as_of": as_of.isoformat(),
        "freshness_threshold_calendar_days": fresh_days,
        "source": source,
        "expected_session_source": expected_session_source,
        "expected_session_count": len(recent_expected),
        "expected_session_analysis_available": bool(recent_expected),
        "status_counts": dict(sorted(counts.items())),
        "symbols_with_missing_sessions": [
            row["symbol"] for row in rows if row["missing_session_count"] > 0
        ],
        "symbols_with_suspicious_ohlcv": [
            row["symbol"] for row in rows if row["suspicious_intraday_range_count"] > 0
        ],
        "symbols_with_suspicious_close_gaps": [
            row["symbol"] for row in rows if row["suspicious_close_gap_count"] > 0
        ],
        "all_held_symbols_fresh": bool(rows) and all(row["status"] == "FRESH" for row in rows),
        "symbols": rows,
    }


def load_monitor_records(path: str | Path) -> list[dict]:
    """Load either append-only alert JSONL or a full monitor snapshot."""
    content = Path(path).read_text().strip()
    if not content:
        return []
    if content[0] not in "[{":
        return [json.loads(line) for line in content.splitlines() if line.strip()]
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return [json.loads(line) for line in content.splitlines() if line.strip()]
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and "results" not in payload:
        return [json.loads(line) for line in content.splitlines() if line.strip()]
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ValueError("monitor snapshot must contain a results list")
    records = []
    for result in payload["results"]:
        record = dict(result)
        record["model_version"] = payload.get("model_version")
        record["observed_at"] = payload.get("observed_at")
        records.append(record)
    return records


def _reason_category(reason: str) -> str:
    if reason.startswith("Position weight"):
        return "position_limit"
    if reason.startswith("Drawdown"):
        return "drawdown"
    if "trend is materially negative" in reason:
        return "negative_trend"
    if "Fundamental coverage is incomplete" in reason:
        return "missing_fundamentals"
    if "need at least" in reason:
        return "insufficient_history"
    if "earnings expectations" in reason.lower():
        return "negative_revisions"
    if "earnings revisions are unavailable" in reason.lower():
        return "missing_revisions"
    return "other"


def analyze_alert_burden(records: list[dict]) -> dict:
    """Measure how selective the latest alert per symbol is."""
    latest = {}
    for record in records:
        symbol = str(record.get("symbol", "")).strip().upper()
        if symbol:
            latest[symbol] = record
    actions = Counter(
        record.get("alert", {}).get("action", "UNKNOWN") for record in latest.values()
    )
    reasons = Counter(
        _reason_category(reason)
        for record in latest.values()
        for reason in record.get("alert", {}).get("reasons", [])
    )
    total = len(latest)
    actionable = sum(actions[action] for action in ACTIONABLE_ACTIONS)
    actionable_rate = actionable / total if total else 0.0
    data_review_rate = actions["DATA_REVIEW"] / total if total else 0.0
    hold_rate = actions["HOLD"] / total if total else 0.0
    return {
        "symbols": total,
        "action_counts": dict(sorted(actions.items())),
        "reason_counts": dict(sorted(reasons.items())),
        "actionable_rate": actionable_rate,
        "data_review_rate": data_review_rate,
        "hold_rate": hold_rate,
        "attention_rate": 1 - hold_rate if total else 0.0,
        "alert_fatigue_risk": actionable_rate > 0.50,
        "data_quality_burden": data_review_rate > 0.25,
    }


def diagnose_alert_file(path: str | Path) -> dict:
    return analyze_alert_burden(load_monitor_records(path))


def compare_monitor_files(baseline_path: str | Path, candidate_path: str | Path) -> dict:
    baseline_records = load_monitor_records(baseline_path)
    candidate_records = load_monitor_records(candidate_path)
    baseline = analyze_alert_burden(baseline_records)
    candidate = analyze_alert_burden(candidate_records)
    baseline_actions = {
        record["symbol"]: record.get("alert", {}).get("action", "UNKNOWN")
        for record in baseline_records
    }
    candidate_actions = {
        record["symbol"]: record.get("alert", {}).get("action", "UNKNOWN")
        for record in candidate_records
    }
    shared_symbols = sorted(set(baseline_actions) & set(candidate_actions))
    transitions = Counter(
        f"{baseline_actions[symbol]} -> {candidate_actions[symbol]}"
        for symbol in shared_symbols
    )
    return {
        "baseline": baseline,
        "candidate": candidate,
        "actionable_rate_change": (
            candidate["actionable_rate"] - baseline["actionable_rate"]
        ),
        "actionable_count_change": sum(
            candidate["action_counts"].get(action, 0) for action in ACTIONABLE_ACTIONS
        )
        - sum(
            baseline["action_counts"].get(action, 0) for action in ACTIONABLE_ACTIONS
        ),
        "action_transitions": dict(sorted(transitions.items())),
        "changed_symbols": {
            symbol: {
                "baseline": baseline_actions[symbol],
                "candidate": candidate_actions[symbol],
            }
            for symbol in shared_symbols
            if baseline_actions[symbol] != candidate_actions[symbol]
        },
    }


def analyze_fundamental_coverage(
    positions: list[Position],
    fundamentals: dict[str, FundamentalSnapshot] | None = None,
) -> dict:
    """Measure effective fundamental coverage without inventing missing inputs."""
    fundamentals = fundamentals or {}
    gaps: dict[str, list[str]] = {
        "quality": [],
        "valuation": [],
        "revisions": [],
    }
    taxonomy_counts = Counter()
    v1_ready = []
    v3_ready = []
    for position in positions:
        snapshot = fundamentals.get(position.symbol)
        if snapshot and snapshot.taxonomy:
            taxonomy_counts[snapshot.taxonomy] += 1
        quality = (
            position.quality
            if position.quality is not None
            else snapshot.quality if snapshot else None
        )
        valuation = (
            position.valuation
            if position.valuation is not None
            else snapshot.valuation if snapshot else None
        )
        revisions = position.revisions
        if quality is None:
            gaps["quality"].append(position.symbol)
        if valuation is None:
            gaps["valuation"].append(position.symbol)
        if revisions is None:
            gaps["revisions"].append(position.symbol)
        if quality is not None and valuation is not None:
            v3_ready.append(position.symbol)
            if revisions is not None:
                v1_ready.append(position.symbol)
    total = len(positions)
    return {
        "symbols": total,
        "quality_coverage_rate": (total - len(gaps["quality"])) / total if total else 0.0,
        "valuation_coverage_rate": (
            (total - len(gaps["valuation"])) / total if total else 0.0
        ),
        "revisions_coverage_rate": (
            (total - len(gaps["revisions"])) / total if total else 0.0
        ),
        "v1_buy_ready_symbols": sorted(v1_ready),
        "v3_buy_ready_symbols": sorted(v3_ready),
        "gap_symbols": {name: sorted(symbols) for name, symbols in gaps.items()},
        "sec_snapshot_count": len(fundamentals),
        "taxonomy_counts": dict(sorted(taxonomy_counts.items())),
    }


def build_model_health_summary(
    *,
    read_only: bool,
    price_coverage_rate: float,
    prices_fresh: bool,
    kline_coverage_rate: float,
    wave_coverage_rate: float,
    diagnostic: dict,
    fundamental_coverage_rate: float,
    direction_forecast_scorecard: list[dict],
) -> dict:
    """Apply explicit operational and evidence gates to one machine-readable view."""
    matured_by_direction = {
        direction: sum(
            int(row.get("observations", 0))
            for row in direction_forecast_scorecard
            if row.get("direction") == direction
        )
        for direction in ("BUY", "SELL")
    }
    matured_directional = sum(matured_by_direction.values())
    gates = [
        {
            "id": "read_only",
            "category": "safety",
            "status": "PASS" if read_only else "FAIL",
            "blocking": True,
            "actual": read_only,
            "threshold": True,
            "detail": "No brokerage write or trade action is permitted.",
        },
        {
            "id": "price_coverage",
            "category": "data",
            "status": "PASS" if price_coverage_rate >= 1 else "FAIL",
            "blocking": True,
            "actual": price_coverage_rate,
            "threshold": 1.0,
            "detail": "Every held symbol must have price history.",
        },
        {
            "id": "price_freshness",
            "category": "data",
            "status": "PASS" if prices_fresh else "FAIL",
            "blocking": True,
            "actual": prices_fresh,
            "threshold": True,
            "detail": "Latest prices must be no more than seven calendar days old.",
        },
        {
            "id": "kline_coverage",
            "category": "data",
            "status": "PASS" if kline_coverage_rate >= 0.8 else "FAIL",
            "blocking": False,
            "actual": kline_coverage_rate,
            "threshold": 0.8,
            "detail": "At least 80% of holdings should have complete OHLCV chart evidence.",
        },
        {
            "id": "wave_coverage",
            "category": "data",
            "status": "PASS" if wave_coverage_rate >= 0.8 else "FAIL",
            "blocking": False,
            "actual": wave_coverage_rate,
            "threshold": 0.8,
            "detail": "At least 80% of holdings should have structural wave evidence.",
        },
        {
            "id": "alert_selectivity",
            "category": "behavior",
            "status": (
                "PASS" if float(diagnostic.get("actionable_rate", 0)) <= 0.5 else "FAIL"
            ),
            "blocking": False,
            "actual": float(diagnostic.get("actionable_rate", 0)),
            "threshold": 0.5,
            "detail": "Action-review rate should not exceed 50%.",
        },
        {
            "id": "data_review_burden",
            "category": "behavior",
            "status": (
                "PASS" if float(diagnostic.get("data_review_rate", 0)) <= 0.25 else "FAIL"
            ),
            "blocking": False,
            "actual": float(diagnostic.get("data_review_rate", 0)),
            "threshold": 0.25,
            "detail": "Data-review rate should not exceed 25%.",
        },
        {
            "id": "fundamental_coverage",
            "category": "data",
            "status": "PASS" if fundamental_coverage_rate >= 0.8 else "FAIL",
            "blocking": False,
            "actual": fundamental_coverage_rate,
            "threshold": 0.8,
            "detail": "At least 80% of holdings should be ready for fundamental evaluation.",
        },
        {
            "id": "matured_directional_evidence",
            "category": "validation",
            "status": "PASS" if matured_directional >= 30 else "PENDING",
            "blocking": False,
            "actual": matured_directional,
            "threshold": 30,
            "detail": "At least 30 matured BUY/SELL forecast outcomes are required.",
        },
        {
            "id": "two_sided_directional_evidence",
            "category": "validation",
            "status": (
                "PASS"
                if min(matured_by_direction.values()) >= 10
                else "PENDING"
            ),
            "blocking": False,
            "actual": matured_by_direction,
            "threshold": {"BUY": 10, "SELL": 10},
            "detail": "Both BUY and SELL require at least 10 matured outcomes.",
        },
    ]
    counts = Counter(gate["status"] for gate in gates)
    blocking_failures = [gate["id"] for gate in gates if gate["blocking"] and gate["status"] == "FAIL"]
    failed = [gate["id"] for gate in gates if gate["status"] == "FAIL"]
    pending = [gate["id"] for gate in gates if gate["status"] == "PENDING"]
    overall = "BLOCKED" if blocking_failures else "DEGRADED" if failed else "PENDING" if pending else "READY"
    return {
        "schema_version": "model-health-v1",
        "overall_status": overall,
        "gate_counts": dict(sorted(counts.items())),
        "blocking_failures": blocking_failures,
        "failed_gates": failed,
        "pending_gates": pending,
        "matured_directional_by_direction": matured_by_direction,
        "gates": gates,
    }
