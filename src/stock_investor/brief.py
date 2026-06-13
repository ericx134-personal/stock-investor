from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content)
