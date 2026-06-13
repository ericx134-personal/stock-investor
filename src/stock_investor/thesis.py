from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .fundamentals import FundamentalSnapshot


ALLOWED_STATUSES = {"ACTIVE", "WATCH", "BROKEN", "CLOSED"}


@dataclass(frozen=True)
class Thesis:
    symbol: str
    summary: str
    status: str
    review_by: str | None
    invalidation_rules: dict[str, float]


@dataclass(frozen=True)
class ThesisAssessment:
    symbol: str
    status: str
    broken: bool
    review_due: bool
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]


def load_theses(path: str | Path) -> dict[str, Thesis]:
    payload = json.loads(Path(path).read_text())
    theses = {}
    for symbol, values in payload.items():
        thesis = Thesis(
            symbol=symbol.upper(),
            summary=values["summary"].strip(),
            status=values.get("status", "ACTIVE").upper(),
            review_by=values.get("review_by"),
            invalidation_rules={
                name: float(value)
                for name, value in values.get("invalidation_rules", {}).items()
            },
        )
        if not thesis.summary:
            raise ValueError(f"{symbol} thesis summary cannot be empty")
        if thesis.status not in ALLOWED_STATUSES:
            raise ValueError(f"{symbol} has invalid thesis status {thesis.status}")
        if thesis.review_by:
            date.fromisoformat(thesis.review_by)
        theses[thesis.symbol] = thesis
    return theses


def assess_thesis(
    thesis: Thesis,
    fundamentals: FundamentalSnapshot | None,
    as_of: date,
) -> ThesisAssessment:
    reasons = []
    warnings = []
    review_due = bool(thesis.review_by and date.fromisoformat(thesis.review_by) <= as_of)
    if review_due:
        reasons.append(f"Investment thesis review was due by {thesis.review_by}.")
    broken = thesis.status in {"BROKEN", "CLOSED"}
    if broken:
        reasons.append(f"Investment thesis status is marked {thesis.status}.")

    metrics = fundamentals.metrics if fundamentals else {}
    for rule, threshold in thesis.invalidation_rules.items():
        if rule.endswith("_below"):
            metric_name = rule.removesuffix("_below")
            value = metrics.get(metric_name)
            if value is None:
                warnings.append(f"Cannot evaluate {rule}: {metric_name} is unavailable.")
            elif value < threshold:
                broken = True
                reasons.append(
                    f"{metric_name} {value:.1%} is below the thesis floor "
                    f"of {threshold:.1%}."
                )
        elif rule.endswith("_above"):
            metric_name = rule.removesuffix("_above")
            value = metrics.get(metric_name)
            if value is None:
                warnings.append(f"Cannot evaluate {rule}: {metric_name} is unavailable.")
            elif value > threshold:
                broken = True
                reasons.append(
                    f"{metric_name} {value:.1%} is above the thesis ceiling "
                    f"of {threshold:.1%}."
                )
        else:
            raise ValueError(f"unsupported thesis invalidation rule: {rule}")

    return ThesisAssessment(
        symbol=thesis.symbol,
        status=thesis.status,
        broken=broken,
        review_due=review_due,
        reasons=tuple(reasons),
        warnings=tuple(warnings),
    )
