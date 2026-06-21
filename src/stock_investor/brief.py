from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .io import atomic_write_text

from .feedback import load_latest_feedback


def _load_jsonl(path: str | Path | None) -> list[dict]:
    if not path or not Path(path).exists():
        return []
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def _parse_timestamp(record: dict, fields: tuple[str, ...]) -> datetime | None:
    for field in fields:
        value = record.get(field)
        if not value:
            continue
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            continue
        return (
            parsed.replace(tzinfo=timezone.utc)
            if parsed.tzinfo is None
            else parsed.astimezone(timezone.utc)
        )
    return None


def _recent(
    records: list[dict],
    cutoff: datetime,
    timestamp_fields: tuple[str, ...],
) -> list[dict]:
    return [
        record
        for record in records
        if (timestamp := _parse_timestamp(record, timestamp_fields))
        and timestamp >= cutoff
    ]


def _latest_by(
    records: list[dict],
    key_fields: tuple[str, ...],
    timestamp_fields: tuple[str, ...],
) -> list[dict]:
    latest: dict[tuple[object, ...], tuple[datetime, dict]] = {}
    for record in records:
        timestamp = _parse_timestamp(record, timestamp_fields)
        if timestamp is None:
            continue
        key = tuple(record.get(field) for field in key_fields)
        if key not in latest or timestamp >= latest[key][0]:
            latest[key] = (timestamp, record)
    return [value[1] for value in latest.values()]


def build_brief(
    period_days: int,
    alerts_path: str | Path | None = None,
    risk_path: str | Path | None = None,
    filings_path: str | Path | None = None,
    feedback_path: str | Path | None = None,
    now: datetime | None = None,
) -> str:
    if period_days < 1:
        raise ValueError("period_days must be at least 1")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    cutoff = now - timedelta(days=period_days)

    alerts = _latest_by(
        _recent(_load_jsonl(alerts_path), cutoff, ("observed_at", "signal_date")),
        ("symbol",),
        ("observed_at", "signal_date"),
    )
    risks = _latest_by(
        _recent(_load_jsonl(risk_path), cutoff, ("observed_at",)),
        ("key",),
        ("observed_at",),
    )
    filings = _recent(_load_jsonl(filings_path), cutoff, ("observed_at", "filed_at"))
    feedback = load_latest_feedback(feedback_path) if feedback_path else {}

    label = "Daily" if period_days == 1 else f"{period_days}-Day"
    lines = [
        f"# {label} Portfolio Brief",
        "",
        f"As of {now.date().isoformat()} UTC | Since {cutoff.date().isoformat()} UTC",
        "",
        "## Action Alerts",
    ]
    if alerts:
        for record in sorted(
            alerts,
            key=lambda item: (
                item.get("signal_date", ""),
                item.get("symbol", ""),
            ),
            reverse=True,
        ):
            alert = record.get("alert", {})
            score = alert.get("score")
            score_text = "missing" if score is None else f"{float(score):+.2f}"
            review = feedback.get(record.get("alert_id", ""))
            review_text = (
                ""
                if review is None
                else f" | feedback {review.label}/{review.response}"
            )
            reasons = alert.get("reasons", ())
            reason_text = f" | {reasons[0]}" if reasons else ""
            lines.append(
                f"- {record.get('symbol', 'UNKNOWN')}: "
                f"{alert.get('action', 'UNKNOWN')} | score {score_text}"
                f"{review_text}{reason_text}"
            )
    else:
        lines.append("- No new action alerts.")

    lines.extend(("", "## Portfolio Risk"))
    if risks:
        for record in risks:
            lines.append(
                f"- [{record.get('severity', 'UNKNOWN')}] "
                f"{record.get('message', 'Risk alert')}"
            )
    else:
        lines.append("- No newly recorded portfolio-risk breaches.")

    lines.extend(("", "## Material Filings"))
    if filings:
        for record in sorted(
            filings, key=lambda item: item.get("filed_at", ""), reverse=True
        ):
            categories = ", ".join(record.get("event_categories", ()))
            detail = categories or record.get("form", "Filing")
            lines.append(
                f"- [{record.get('importance', 'INFO')}] "
                f"{record.get('symbol', 'UNKNOWN')}: {detail} "
                f"({record.get('filed_at', 'unknown date')})"
            )
    else:
        lines.append("- No new monitored SEC filings.")

    lines.extend(
        (
            "",
            "Human review is required before any trade. This brief is decision "
            "support, not a prediction or order.",
        )
    )
    return "\n".join(lines) + "\n"


def write_brief(content: str, path: str | Path) -> None:
    atomic_write_text(content, path)


def _format_percent(value: object) -> str:
    return "pending" if value is None else f"{float(value):.1%}"


def _sum_scorecard_field(rows: list[dict], field: str) -> int:
    return sum(int(row.get(field) or 0) for row in rows)


def _latest_price_date(price_health: dict) -> str:
    direct = price_health.get("latest_date")
    if direct:
        return str(direct)
    dates = [
        str(row.get("latest_date"))
        for row in price_health.get("symbols", [])
        if row.get("latest_date")
    ]
    return max(dates) if dates else "unknown"


def build_portfolio_learning_review(
    *,
    model_health: dict | None = None,
    price_health: dict | None = None,
    first_observed_forecasts: dict | None = None,
    forecast_action_segments: dict | None = None,
    direction_forecast_scorecard: list[dict] | None = None,
    forecast_calibration_curves: list[dict] | None = None,
    direction_error_cohorts: list[dict] | None = None,
    now: datetime | None = None,
) -> str:
    """Build a private monthly learning review from sealed refresh artifacts."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    model_health = model_health or {}
    price_health = price_health or {}
    first_observed_forecasts = first_observed_forecasts or {}
    forecast_action_segments = forecast_action_segments or {}
    direction_forecast_scorecard = direction_forecast_scorecard or []
    forecast_calibration_curves = forecast_calibration_curves or []
    direction_error_cohorts = direction_error_cohorts or []

    calibration_counts = Counter(
        row.get("status", "UNKNOWN") for row in forecast_calibration_curves
    )
    action_segment_counts = forecast_action_segments.get("episode_segment_counts") or {}
    first_direction_counts = first_observed_forecasts.get("first_direction_counts") or {}
    matured = _sum_scorecard_field(direction_forecast_scorecard, "observations")
    pending = _sum_scorecard_field(direction_forecast_scorecard, "pending")
    displayed = _sum_scorecard_field(direction_forecast_scorecard, "forecast_episodes")
    top_errors = sorted(
        direction_error_cohorts,
        key=lambda row: (
            int(row.get("false_signal_count") or row.get("observations") or 0),
            row.get("direction", ""),
        ),
        reverse=True,
    )[:5]

    lines = [
        "# Monthly Portfolio Learning Review",
        "",
        f"As of {now.date().isoformat()} UTC",
        "",
        "This is a private learning artifact for model accountability. It is "
        "read-only decision support, not a trade instruction.",
        "",
        "## Executive Readout",
        f"- Model health: {model_health.get('overall_status', 'UNKNOWN')}.",
        f"- Latest price date: {_latest_price_date(price_health)}.",
        (
            "- Direction forecast episodes: "
            f"{displayed} displayed windows, {matured} matured observations, "
            f"{pending} pending observations."
        ),
        (
            "- First-observed tracking: "
            f"{int(first_observed_forecasts.get('tracked_count') or 0)} tracked, "
            f"{int(first_observed_forecasts.get('changed_since_first_count') or 0)} "
            "changed since first seen."
        ),
        "",
        "## First Forecast Accountability",
    ]
    if first_direction_counts:
        for direction, count in sorted(first_direction_counts.items()):
            lines.append(f"- {direction}: {count} first-observed holdings.")
    else:
        lines.append("- No first-observed forecast distribution is available yet.")

    lines.extend(("", "## Action Segment Proxy Comparison"))
    if action_segment_counts:
        for segment, count in sorted(action_segment_counts.items()):
            label = (
                forecast_action_segments.get("segment_definitions", {})
                .get(segment, {})
                .get("label", segment)
            )
            lines.append(f"- {label}: {count} forecast episodes.")
    else:
        lines.append("- No action-segment proxy episodes are available yet.")
    lines.append(
        "- Segment labels are current-state proxies only; do not read them as causal trade evidence."
    )

    lines.extend(("", "## Calibration And Error Review"))
    if calibration_counts:
        for status, count in sorted(calibration_counts.items()):
            lines.append(f"- Calibration {status}: {count} buckets.")
    else:
        lines.append("- No calibration buckets are available yet.")
    if top_errors:
        lines.append("- Top false-signal cohorts to inspect next:")
        for row in top_errors:
            rate = _format_percent(row.get("false_signal_rate"))
            lines.append(
                "  - "
                f"{row.get('direction', 'UNKNOWN')} {row.get('horizon', '')}: "
                f"{rate} false-signal rate across "
                f"{int(row.get('false_signal_count') or row.get('observations') or 0)} "
                "episodes."
            )
    else:
        lines.append("- No matured false BUY or SELL cohorts yet.")

    lines.extend(
        (
            "",
            "## Next Learning Priorities",
            "- Wait for more matured forward outcomes before changing thresholds aggressively.",
            "- Keep data quality failures visible instead of replacing missing prices or fundamentals with guesses.",
            "- Compare model changes only against sealed historical forecasts and preserved failures.",
            "",
        )
    )
    return "\n".join(lines)
