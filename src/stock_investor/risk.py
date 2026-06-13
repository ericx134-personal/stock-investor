from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .data import Position, Price


@dataclass(frozen=True)
class RiskPolicy:
    sector_limit: float = 0.35
    theme_limit: float = 0.25
    correlated_exposure_limit: float = 0.40
    correlation_threshold: float = 0.75
    annual_risk_budget_per_position: float = 0.025
    correlation_lookback: int = 120
    minimum_correlation_observations: int = 60
    factor_proxies: dict[str, str] = field(default_factory=dict)
    factor_beta_limit: float = 1.25
    gross_exposure_limit: float = 1.0
    gross_exposure_blocks_buy: bool = False


@dataclass(frozen=True)
class PositionRisk:
    symbol: str
    annualized_volatility: float | None
    suggested_max_weight: float | None
    sector_exposure: float | None
    theme_exposure: float | None
    correlated_exposure: float | None
    correlated_symbols: tuple[str, ...]
    factor_betas: dict[str, float]
    buy_allowed: bool
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class PortfolioRiskAlert:
    key: str
    severity: str
    message: str


@dataclass(frozen=True)
class PortfolioRiskReport:
    positions: dict[str, PositionRisk]
    sector_exposures: dict[str, float]
    theme_exposures: dict[str, float]
    factor_exposures: dict[str, float]
    gross_exposure: float
    cash_weight: float
    alerts: tuple[PortfolioRiskAlert, ...]


def validate_risk_policy(policy: RiskPolicy) -> None:
    unit_fields = (
        "sector_limit",
        "theme_limit",
        "correlated_exposure_limit",
        "correlation_threshold",
        "annual_risk_budget_per_position",
    )
    for name in unit_fields:
        value = getattr(policy, name)
        if not 0 < value <= 1:
            raise ValueError(f"{name} must be above 0 and at most 1")
    if policy.correlation_lookback < 2:
        raise ValueError("correlation_lookback must be at least 2")
    if not 2 <= policy.minimum_correlation_observations <= policy.correlation_lookback:
        raise ValueError(
            "minimum_correlation_observations must be between 2 and correlation_lookback"
        )
    if policy.factor_beta_limit <= 0:
        raise ValueError("factor_beta_limit must be above 0")
    if policy.gross_exposure_limit <= 0:
        raise ValueError("gross_exposure_limit must be above 0")
    if any(
        not name.strip() or not symbol.strip()
        for name, symbol in policy.factor_proxies.items()
    ):
        raise ValueError("factor_proxies names and symbols cannot be blank")


def load_risk_policy(path: str | Path) -> RiskPolicy:
    policy = RiskPolicy(**json.loads(Path(path).read_text()))
    validate_risk_policy(policy)
    return policy


def _daily_returns(history: list[Price], lookback: int) -> dict[str, float]:
    recent = history[-(lookback + 1) :]
    return {
        current.date.isoformat(): current.close / previous.close - 1
        for previous, current in zip(recent, recent[1:])
    }


def _volatility(returns: dict[str, float]) -> float | None:
    values = list(returns.values())
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    annualized = math.sqrt(variance) * math.sqrt(252)
    return annualized if annualized >= 0.000001 else None


def _correlation(
    first: dict[str, float], second: dict[str, float], minimum: int
) -> float | None:
    dates = sorted(set(first) & set(second))
    if len(dates) < minimum:
        return None
    left = [first[item] for item in dates]
    right = [second[item] for item in dates]
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum(
        (a - left_mean) * (b - right_mean) for a, b in zip(left, right)
    )
    left_sum = sum((value - left_mean) ** 2 for value in left)
    right_sum = sum((value - right_mean) ** 2 for value in right)
    denominator = math.sqrt(left_sum * right_sum)
    return numerator / denominator if denominator else None


def _beta(
    asset: dict[str, float], factor: dict[str, float], minimum: int
) -> float | None:
    dates = sorted(set(asset) & set(factor))
    if len(dates) < minimum:
        return None
    asset_values = [asset[item] for item in dates]
    factor_values = [factor[item] for item in dates]
    asset_mean = sum(asset_values) / len(asset_values)
    factor_mean = sum(factor_values) / len(factor_values)
    covariance = sum(
        (asset_value - asset_mean) * (factor_value - factor_mean)
        for asset_value, factor_value in zip(asset_values, factor_values)
    )
    factor_variance = sum(
        (factor_value - factor_mean) ** 2 for factor_value in factor_values
    )
    return covariance / factor_variance if factor_variance else None


def analyze_portfolio_risk(
    positions: list[Position],
    prices: dict[str, list[Price]],
    cash_balance: float = 0.0,
    policy: RiskPolicy = RiskPolicy(),
) -> PortfolioRiskReport:
    validate_risk_policy(policy)
    values = {
        position.symbol: (
            position.shares * prices[position.symbol][-1].close
            if prices.get(position.symbol)
            else 0.0
        )
        for position in positions
    }
    total = sum(values.values()) + cash_balance
    if total < 0:
        raise ValueError("portfolio net value cannot be negative")
    gross_exposure = sum(abs(value) for value in values.values()) / total if total else 0.0
    cash_weight = cash_balance / total if total else 0.0
    weights = {
        symbol: value / total if total else 0.0 for symbol, value in values.items()
    }
    returns = {
        symbol: _daily_returns(history, policy.correlation_lookback)
        for symbol, history in prices.items()
    }
    sector_exposures: dict[str, float] = {}
    theme_exposures: dict[str, float] = {}
    for position in positions:
        if position.shares <= 0:
            continue
        if position.sector:
            sector_exposures[position.sector] = (
                sector_exposures.get(position.sector, 0.0) + weights[position.symbol]
            )
        if position.theme:
            theme_exposures[position.theme] = (
                theme_exposures.get(position.theme, 0.0) + weights[position.symbol]
            )

    assessments = {}
    for position in positions:
        warnings = []
        reasons = []
        if (
            policy.gross_exposure_blocks_buy
            and gross_exposure > policy.gross_exposure_limit
        ):
            reasons.append(
                f"Gross exposure is {gross_exposure:.1%}, above the "
                f"{policy.gross_exposure_limit:.1%} limit; buy and add review is blocked."
            )
        symbol_returns = returns.get(position.symbol, {})
        volatility = _volatility(symbol_returns)
        suggested = (
            min(
                position.max_portfolio_weight,
                policy.annual_risk_budget_per_position / volatility,
            )
            if volatility and volatility > 0
            else None
        )
        if suggested is None:
            warnings.append("Insufficient price variation for volatility sizing.")
            reasons.append("Volatility sizing is unavailable; buy and add review is blocked.")

        sector_exposure = (
            sector_exposures.get(position.sector, 0.0) if position.sector else None
        )
        theme_exposure = (
            theme_exposures.get(position.theme, 0.0) if position.theme else None
        )
        if position.sector is None:
            warnings.append("Sector is unknown; sector concentration was not evaluated.")
            reasons.append("Sector is unknown; buy and add review is blocked.")
        elif sector_exposure is not None and sector_exposure >= policy.sector_limit:
            reasons.append(
                f"Sector {position.sector} exposure is {sector_exposure:.1%}, at or "
                f"above the {policy.sector_limit:.1%} limit."
            )
        if (
            position.theme
            and theme_exposure is not None
            and theme_exposure >= policy.theme_limit
        ):
            reasons.append(
                f"Theme {position.theme} exposure is {theme_exposure:.1%}, at or "
                f"above the {policy.theme_limit:.1%} limit."
            )

        correlated = []
        correlated_exposure = 0.0
        for other in positions:
            if other.symbol == position.symbol or other.shares <= 0:
                continue
            correlation = _correlation(
                symbol_returns,
                returns.get(other.symbol, {}),
                policy.minimum_correlation_observations,
            )
            if correlation is not None and correlation >= policy.correlation_threshold:
                correlated.append(other.symbol)
                correlated_exposure += weights[other.symbol]
        held_others = [
            other
            for other in positions
            if other.symbol != position.symbol and other.shares > 0
        ]
        if held_others and len(symbol_returns) < policy.minimum_correlation_observations:
            warnings.append("Insufficient history for correlation exposure.")
            reasons.append(
                "Correlation exposure is unavailable; buy and add review is blocked."
            )
        elif correlated_exposure >= policy.correlated_exposure_limit:
            reasons.append(
                f"Exposure to highly correlated holdings is {correlated_exposure:.1%}, "
                f"at or above the {policy.correlated_exposure_limit:.1%} limit."
            )
        factor_betas = {
            name: beta
            for name, symbol in policy.factor_proxies.items()
            if (
                beta := _beta(
                    symbol_returns,
                    returns.get(symbol.upper(), {}),
                    policy.minimum_correlation_observations,
                )
            )
            is not None
        }

        assessments[position.symbol] = PositionRisk(
            symbol=position.symbol,
            annualized_volatility=volatility,
            suggested_max_weight=suggested,
            sector_exposure=sector_exposure,
            theme_exposure=theme_exposure,
            correlated_exposure=correlated_exposure,
            correlated_symbols=tuple(sorted(correlated)),
            factor_betas=factor_betas,
            buy_allowed=not reasons,
            reasons=tuple(reasons),
            warnings=tuple(warnings),
        )

    alerts = []
    if gross_exposure > policy.gross_exposure_limit:
        alerts.append(
            PortfolioRiskAlert(
                "gross-exposure",
                "HIGH",
                f"Gross exposure is {gross_exposure:.1%} of net portfolio value, "
                f"above the {policy.gross_exposure_limit:.1%} limit; cash weight "
                f"is {cash_weight:.1%}.",
            )
        )
    for sector, exposure in sector_exposures.items():
        if exposure > policy.sector_limit:
            alerts.append(
                PortfolioRiskAlert(
                    f"sector:{sector}",
                    "HIGH",
                    f"Sector {sector} is {exposure:.1%} of the portfolio, above "
                    f"the {policy.sector_limit:.1%} limit.",
                )
            )
    factor_exposures: dict[str, float] = {}
    held = [position for position in positions if weights.get(position.symbol, 0) > 0]
    for name, symbol in policy.factor_proxies.items():
        available = [
            (weights[position.symbol], assessments[position.symbol].factor_betas.get(name))
            for position in held
        ]
        if not held or any(beta is None for _, beta in available):
            alerts.append(
                PortfolioRiskAlert(
                    f"factor-data:{name}",
                    "MEDIUM",
                    f"Portfolio {name} factor exposure is unavailable; ensure "
                    f"{symbol.upper()} and every held position have sufficient history.",
                )
            )
            continue
        exposure = sum(weight * float(beta) for weight, beta in available)
        factor_exposures[name] = exposure
        if abs(exposure) > policy.factor_beta_limit:
            alerts.append(
                PortfolioRiskAlert(
                    f"factor:{name}",
                    "HIGH",
                    f"Portfolio {name} factor beta is {exposure:+.2f}, beyond "
                    f"the +/-{policy.factor_beta_limit:.2f} limit.",
                )
            )
    for theme, exposure in theme_exposures.items():
        if exposure > policy.theme_limit:
            alerts.append(
                PortfolioRiskAlert(
                    f"theme:{theme}",
                    "HIGH",
                    f"Theme {theme} is {exposure:.1%} of the portfolio, above "
                    f"the {policy.theme_limit:.1%} limit.",
                )
            )
    seen_pairs = set()
    for symbol, assessment in assessments.items():
        for other in assessment.correlated_symbols:
            pair = tuple(sorted((symbol, other)))
            if weights.get(symbol, 0.0) == 0 or weights.get(other, 0.0) == 0:
                continue
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            combined = weights.get(symbol, 0.0) + weights.get(other, 0.0)
            if combined > policy.correlated_exposure_limit:
                alerts.append(
                    PortfolioRiskAlert(
                        f"correlation:{pair[0]}:{pair[1]}",
                        "HIGH",
                        f"{pair[0]} and {pair[1]} are highly correlated and together "
                        f"represent {combined:.1%} of the portfolio.",
                    )
                )
    return PortfolioRiskReport(
        positions=assessments,
        sector_exposures=sector_exposures,
        theme_exposures=theme_exposures,
        factor_exposures=factor_exposures,
        gross_exposure=gross_exposure,
        cash_weight=cash_weight,
        alerts=tuple(alerts),
    )


def write_portfolio_risk_history(
    report: PortfolioRiskReport, path: str | Path
) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    existing_keys = set()
    if output.exists():
        existing_keys = {
            json.loads(line).get("event_key")
            for line in output.read_text().splitlines()
        }
    with output.open("a") as handle:
        for alert in report.alerts:
            event_key = f"{alert.key}|{alert.message}"
            if event_key in existing_keys:
                continue
            record = asdict(alert)
            record["event_key"] = event_key
            record["observed_at"] = timestamp
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            existing_keys.add(event_key)
