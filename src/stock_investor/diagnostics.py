from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .data import Position
from .fundamentals import FundamentalSnapshot


ACTIONABLE_ACTIONS = {"BUY_CANDIDATE", "ADD_CANDIDATE", "REVIEW", "TRIM_REVIEW"}


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
