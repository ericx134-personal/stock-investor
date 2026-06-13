from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


FEEDBACK_LABELS = ("HELPFUL", "NOT_HELPFUL", "UNSURE")
FEEDBACK_RESPONSES = ("ACTED", "WATCHING", "DISMISSED", "NO_ACTION")


@dataclass(frozen=True)
class AlertFeedback:
    feedback_id: str
    alert_id: str
    label: str
    response: str
    note: str
    recorded_at: str


def _alert_ids(path: str | Path) -> set[str]:
    return {
        record["alert_id"]
        for line in Path(path).read_text().splitlines()
        if (record := json.loads(line)).get("alert_id")
    }


def append_feedback(
    alerts_path: str | Path,
    feedback_path: str | Path,
    alert_id: str,
    label: str,
    response: str = "NO_ACTION",
    note: str = "",
) -> AlertFeedback:
    label = label.upper()
    response = response.upper()
    note = note.strip()
    if label not in FEEDBACK_LABELS:
        raise ValueError(f"label must be one of {', '.join(FEEDBACK_LABELS)}")
    if response not in FEEDBACK_RESPONSES:
        raise ValueError(f"response must be one of {', '.join(FEEDBACK_RESPONSES)}")
    if alert_id not in _alert_ids(alerts_path):
        raise ValueError(f"unknown alert_id: {alert_id}")

    recorded_at = datetime.now(timezone.utc).isoformat()
    event_key = "|".join((alert_id, label, response, note, recorded_at))
    feedback = AlertFeedback(
        feedback_id=hashlib.sha256(event_key.encode()).hexdigest()[:20],
        alert_id=alert_id,
        label=label,
        response=response,
        note=note,
        recorded_at=recorded_at,
    )
    output = Path(feedback_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a") as handle:
        handle.write(json.dumps(asdict(feedback), sort_keys=True) + "\n")
    return feedback


def load_latest_feedback(path: str | Path) -> dict[str, AlertFeedback]:
    source = Path(path)
    if not source.exists():
        return {}
    latest: dict[str, AlertFeedback] = {}
    for line in source.read_text().splitlines():
        payload = json.loads(line)
        feedback = AlertFeedback(**payload)
        previous = latest.get(feedback.alert_id)
        if previous is None or feedback.recorded_at >= previous.recorded_at:
            latest[feedback.alert_id] = feedback
    return latest
