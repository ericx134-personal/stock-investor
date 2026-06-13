"""Stable, versioned policies for alert-generating model behavior."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DecisionPolicy:
    model_version: str
    buy_candidate_threshold: float
    drawdown_review_threshold: float
    severe_drawdown_threshold: float
    negative_trend_threshold: float
    negative_revisions_threshold: float
    trim_score_threshold: float
    minimum_deterioration_signals: int
    require_revisions_for_buy: bool


MODEL_VERSION = "decision-support-v1"
MODEL_POLICIES = {
    MODEL_VERSION: DecisionPolicy(
        MODEL_VERSION, 0.45, -0.20, -0.20, -0.50, -0.50, -0.25, 1, True
    ),
    "decision-support-v2": DecisionPolicy(
        "decision-support-v2", 0.50, -0.30, -0.50, -0.50, -0.50, -0.25, 2, True
    ),
    "decision-support-v3": DecisionPolicy(
        "decision-support-v3", 0.50, -0.30, -0.50, -0.50, -0.50, -0.25, 2, False
    ),
}


def get_model_policy(model_version: str = MODEL_VERSION) -> DecisionPolicy:
    try:
        return MODEL_POLICIES[model_version]
    except KeyError as error:
        raise ValueError(f"unknown model version: {model_version}") from error
