from __future__ import annotations


MULTIPLE_TESTING_LEDGER_VERSION = "multiple-testing-ledger-v1"
FALSE_DISCOVERY_WARNING_VERSION = "false-discovery-warnings-v1"


EXPERIMENT_REGISTRY = [
    {
        "id": "alert_forward_scorecard",
        "family": "decision_policy",
        "artifact_key": "scorecard",
        "hypothesis": "Actionable alert classes lead to favorable forward outcomes.",
        "predeclared": True,
        "promoted_signal_allowed": False,
    },
    {
        "id": "all_decision_scorecard",
        "family": "decision_policy",
        "artifact_key": "decision_scorecard",
        "hypothesis": "All emitted decisions, including HOLD and REVIEW, have auditable forward outcomes.",
        "predeclared": True,
        "promoted_signal_allowed": False,
    },
    {
        "id": "kline_scorecard",
        "family": "technical_context",
        "artifact_key": "kline_scorecard",
        "hypothesis": "Daily OHLCV regimes provide useful supporting context.",
        "predeclared": True,
        "promoted_signal_allowed": False,
    },
    {
        "id": "wave_scorecard",
        "family": "structural_wave",
        "artifact_key": "wave_scorecard",
        "hypothesis": "Confirmed structural-wave regimes have useful long-horizon outcomes.",
        "predeclared": True,
        "promoted_signal_allowed": False,
    },
    {
        "id": "wave_walk_forward_scorecard",
        "family": "structural_wave",
        "artifact_key": "wave_experiment_scorecard",
        "hypothesis": "Causal non-overlapping wave analogs explain future absolute and SPY-relative returns.",
        "predeclared": True,
        "promoted_signal_allowed": False,
    },
    {
        "id": "wave_conditional_scorecard",
        "family": "structural_wave",
        "artifact_key": "wave_conditional_scorecard",
        "hypothesis": "Predeclared wave age and magnitude cells improve precision.",
        "predeclared": True,
        "promoted_signal_allowed": False,
    },
    {
        "id": "direction_forecast_scorecard",
        "family": "direction_forecast",
        "artifact_key": "direction_forecast_scorecard",
        "hypothesis": "Displayed BUY and SELL directions are calibrated after outcomes mature.",
        "predeclared": True,
        "promoted_signal_allowed": False,
    },
    {
        "id": "forecast_calibration_scorecard",
        "family": "direction_forecast",
        "artifact_key": "forecast_calibration_scorecard",
        "hypothesis": "Displayed confidence buckets match realized directional success.",
        "predeclared": True,
        "promoted_signal_allowed": False,
    },
    {
        "id": "direction_classification_metrics",
        "family": "direction_forecast",
        "artifact_key": "direction_classification_metrics",
        "hypothesis": "BUY and SELL labels have acceptable precision, recall, and false-positive rates.",
        "predeclared": True,
        "promoted_signal_allowed": False,
    },
    {
        "id": "direction_error_cohorts",
        "family": "direction_forecast",
        "artifact_key": "direction_error_cohorts",
        "hypothesis": "Largest false-direction episodes do not reveal repeatable failure modes.",
        "predeclared": True,
        "promoted_signal_allowed": False,
    },
    {
        "id": "price_zone_replay_scorecard",
        "family": "price_zone",
        "artifact_key": "price_zone_replay_scorecard",
        "hypothesis": "Support, resistance, and retest zones are touched or invalidated in measurable ways.",
        "predeclared": True,
        "promoted_signal_allowed": False,
    },
    {
        "id": "direction_rate_comparison",
        "family": "calibration_audit",
        "artifact_key": "direction_rate_comparison",
        "hypothesis": "Shrunk displayed confidence is safer than raw historical rates.",
        "predeclared": True,
        "promoted_signal_allowed": False,
    },
    {
        "id": "wave_time_decay_scorecard",
        "family": "structural_wave",
        "artifact_key": "wave_time_decay_scorecard",
        "hypothesis": "Recent wave analogs may deserve more weight than older regimes.",
        "predeclared": True,
        "promoted_signal_allowed": False,
    },
]


def _risk_level(hypothesis_count: int) -> str:
    if hypothesis_count >= 20:
        return "HIGH"
    if hypothesis_count >= 6:
        return "MEDIUM"
    return "LOW"


def build_multiple_testing_ledger(artifact_counts: dict[str, int]) -> dict:
    rows = []
    family_totals: dict[str, int] = {}
    for experiment in EXPERIMENT_REGISTRY:
        count = int(artifact_counts.get(experiment["artifact_key"], 0))
        family_totals[experiment["family"]] = (
            family_totals.get(experiment["family"], 0) + count
        )
        rows.append(
            {
                "ledger_version": MULTIPLE_TESTING_LEDGER_VERSION,
                **experiment,
                "hypothesis_count": count,
                "multiple_testing_risk": _risk_level(count),
                "promotion_status": "LEDGER_ONLY",
                "required_before_promotion": (
                    "Apply family-level false-discovery controls or sealed holdout replication before using this experiment to promote a model."
                ),
            }
        )
    for row in rows:
        row["family_hypothesis_count"] = family_totals[row["family"]]
        row["family_multiple_testing_risk"] = _risk_level(
            family_totals[row["family"]]
        )
    return {
        "ledger_version": MULTIPLE_TESTING_LEDGER_VERSION,
        "total_hypothesis_count": sum(family_totals.values()),
        "family_hypothesis_counts": dict(sorted(family_totals.items())),
        "rows": rows,
    }


def build_false_discovery_warnings(ledger: dict) -> list[dict]:
    warnings = []
    for family, count in sorted(ledger.get("family_hypothesis_counts", {}).items()):
        risk = _risk_level(int(count))
        if risk == "LOW":
            continue
        warnings.append(
            {
                "warning_version": FALSE_DISCOVERY_WARNING_VERSION,
                "family": family,
                "family_hypothesis_count": int(count),
                "risk": risk,
                "status": "BLOCK_PROMOTION",
                "message": (
                    f"{family} has {int(count)} tested rows; raw winners need false-discovery control or sealed holdout replication before promotion."
                ),
            }
        )
    return warnings
