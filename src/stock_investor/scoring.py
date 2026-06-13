from __future__ import annotations

from dataclasses import dataclass

from .model import DecisionPolicy, get_model_policy


SIGNAL_WEIGHTS = {
    "trend": 0.25,
    "momentum": 0.20,
    "quality": 0.25,
    "valuation": 0.20,
    "revisions": 0.10,
}
BUY_CANDIDATE_THRESHOLD = 0.45


@dataclass(frozen=True)
class SignalSnapshot:
    symbol: str
    portfolio_weight: float
    max_portfolio_weight: float
    drawdown_from_high: float
    trend: float
    momentum: float
    quality: float
    valuation: float
    revisions: float
    revisions_available: bool = True
    thesis_broken: bool = False
    is_held: bool = False
    fundamentals_complete: bool = True
    portfolio_risk_allows_buy: bool = True
    portfolio_risk_reasons: tuple[str, ...] = ()
    thesis_review_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class Alert:
    symbol: str
    action: str
    score: float
    reasons: tuple[str, ...]


def _validate_unit_interval(name: str, value: float) -> None:
    if not -1.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between -1 and 1")


def _score(snapshot: SignalSnapshot) -> float:
    values = {
        "trend": snapshot.trend,
        "momentum": snapshot.momentum,
        "quality": snapshot.quality,
        "valuation": snapshot.valuation,
        "revisions": snapshot.revisions,
    }
    for name, value in values.items():
        _validate_unit_interval(name, value)
    return sum(values[name] * weight for name, weight in SIGNAL_WEIGHTS.items())


def evaluate(snapshot: SignalSnapshot, policy: DecisionPolicy | None = None) -> Alert:
    """Create an explainable review alert from a normalized signal snapshot."""
    policy = policy or get_model_policy()
    score = _score(snapshot)
    reasons: list[str] = []

    if snapshot.thesis_broken:
        reasons.append("The recorded investment thesis is marked broken.")
        reasons.extend(snapshot.thesis_review_reasons)
        action = "TRIM_REVIEW" if snapshot.is_held else "REVIEW"
        return Alert(snapshot.symbol, action, score, tuple(reasons))

    if snapshot.portfolio_weight > snapshot.max_portfolio_weight:
        reasons.append(
            f"Position weight {snapshot.portfolio_weight:.1%} exceeds the "
            f"{snapshot.max_portfolio_weight:.1%} limit."
        )

    deterioration_reasons: list[str] = []
    if snapshot.drawdown_from_high <= policy.drawdown_review_threshold:
        deterioration_reasons.append(
            f"Drawdown is {snapshot.drawdown_from_high:.1%}; review the thesis."
        )

    if snapshot.trend <= policy.negative_trend_threshold:
        deterioration_reasons.append("The medium-term trend is materially negative.")

    if snapshot.revisions <= policy.negative_revisions_threshold:
        deterioration_reasons.append("Earnings expectations are being revised downward.")

    deterioration_review = (
        len(deterioration_reasons) >= policy.minimum_deterioration_signals
        or snapshot.drawdown_from_high <= policy.severe_drawdown_threshold
    )
    if deterioration_review:
        reasons.extend(deterioration_reasons)
    elif deterioration_reasons:
        reasons.append(
            "Deterioration is not yet confirmed by enough independent signals."
        )

    reasons.extend(snapshot.thesis_review_reasons)
    risk_review = (
        snapshot.portfolio_weight > snapshot.max_portfolio_weight
        or deterioration_review
        or bool(snapshot.thesis_review_reasons)
    )
    if snapshot.portfolio_weight > snapshot.max_portfolio_weight or (
        risk_review and score <= -0.25
    ):
        action = "TRIM_REVIEW"
    elif risk_review:
        action = "REVIEW"
    elif not snapshot.fundamentals_complete:
        action = "DATA_REVIEW"
        reasons.append(
            "Fundamental coverage is incomplete; buy and add alerts are disabled."
        )
    elif score >= policy.buy_candidate_threshold and snapshot.quality >= 0:
        if not snapshot.portfolio_risk_allows_buy:
            action = "HOLD" if snapshot.is_held else "DATA_REVIEW"
            reasons.extend(snapshot.portfolio_risk_reasons)
        elif (
            snapshot.is_held
            and snapshot.portfolio_weight >= snapshot.max_portfolio_weight * 0.8
        ):
            action = "HOLD"
            reasons.append(
                "Signals are strong, but the holding is already near its size limit."
            )
        elif snapshot.is_held:
            action = "ADD_CANDIDATE"
            reasons.append(
                "Multiple signals support reviewing a limited addition."
            )
        else:
            action = "BUY_CANDIDATE"
            reasons.append("Multiple independent signals are positively aligned.")
    else:
        action = "HOLD"
        reasons.append("No configured action threshold has been reached.")

    if not snapshot.revisions_available and not policy.require_revisions_for_buy:
        reasons.append(
            "Earnings revisions are unavailable and treated as neutral by this model."
        )

    return Alert(snapshot.symbol, action, score, tuple(reasons))
