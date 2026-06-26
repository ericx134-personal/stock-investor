from __future__ import annotations

import json
import hashlib
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from .data import Position, Price
from .fundamentals import FundamentalSnapshot
from .indicators import TechnicalSignals, calculate_technicals
from .io import atomic_write_text
from .model import MODEL_VERSION, get_model_policy
from .risk import PortfolioRiskReport, PositionRisk, analyze_portfolio_risk
from .scoring import Alert, SignalSnapshot, evaluate
from .thesis import Thesis, ThesisAssessment, assess_thesis


@dataclass(frozen=True)
class MonitorResult:
    symbol: str
    shares: float
    average_cost: float
    cost_basis: float
    latest_close: float | None
    market_value: float
    portfolio_weight: float
    unrealized_return: float | None
    fundamentals: FundamentalSnapshot | None
    risk: PositionRisk | None
    thesis: ThesisAssessment | None
    technicals: TechnicalSignals | None
    alert: Alert
    sector: str | None = None
    theme: str | None = None


def _portfolio_values(
    positions: list[Position], prices: dict[str, list[Price]]
) -> tuple[dict[str, float], float]:
    values = {}
    for position in positions:
        history = prices.get(position.symbol, [])
        values[position.symbol] = (
            position.shares * history[-1].close if history else 0.0
        )
    return values, sum(values.values())


def run_monitor(
    positions: list[Position],
    prices: dict[str, list[Price]],
    cash_balance: float = 0.0,
    fundamentals: dict[str, FundamentalSnapshot] | None = None,
    portfolio_risk: PortfolioRiskReport | None = None,
    theses: dict[str, Thesis] | None = None,
    model_version: str = MODEL_VERSION,
) -> list[MonitorResult]:
    policy = get_model_policy(model_version)
    theses_provided = theses is not None
    values, invested_total = _portfolio_values(positions, prices)
    portfolio_total = invested_total + cash_balance
    if portfolio_total < 0:
        raise ValueError("portfolio net value cannot be negative")
    results: list[MonitorResult] = []
    latest_market_date = max(
        (history[-1].date for history in prices.values() if history), default=None
    )
    fundamentals = fundamentals or {}
    portfolio_risk = portfolio_risk or analyze_portfolio_risk(
        positions, prices, cash_balance
    )
    theses = theses or {}

    for position in positions:
        history = prices.get(position.symbol, [])
        market_value = values[position.symbol]
        portfolio_weight = market_value / portfolio_total if portfolio_total else 0.0
        unrealized_return = (
            history[-1].close / position.average_cost - 1
            if history and position.shares > 0 and position.average_cost > 0
            else None
        )
        fundamental = fundamentals.get(position.symbol)
        risk = portfolio_risk.positions.get(position.symbol)
        thesis = None

        if (
            history
            and latest_market_date
            and (latest_market_date - history[-1].date).days > 7
        ):
            alert = Alert(
                position.symbol,
                "DATA_REVIEW",
                0.0,
                (
                    f"Latest price is {history[-1].date.isoformat()}, behind the "
                    f"dataset's {latest_market_date.isoformat()} market date.",
                ),
            )
            results.append(
                MonitorResult(
                    position.symbol,
                    position.shares,
                    position.average_cost,
                    position.shares * position.average_cost,
                    history[-1].close,
                    market_value,
                    portfolio_weight,
                    unrealized_return,
                    fundamental,
                    risk,
                    thesis,
                    None,
                    alert,
                    position.sector,
                    position.theme,
                )
            )
            continue

        try:
            technicals = calculate_technicals(history)
        except ValueError as error:
            alert = Alert(
                position.symbol,
                "DATA_REVIEW",
                0.0,
                (f"Cannot evaluate signals: {error}.",),
            )
            results.append(
                MonitorResult(
                    position.symbol,
                    position.shares,
                    position.average_cost,
                    position.shares * position.average_cost,
                    history[-1].close if history else None,
                    market_value,
                    portfolio_weight,
                    unrealized_return,
                    fundamental,
                    risk,
                    thesis,
                    None,
                    alert,
                    position.sector,
                    position.theme,
                )
            )
            continue

        quality = (
            position.quality
            if position.quality is not None
            else fundamental.quality if fundamental else None
        )
        valuation = (
            position.valuation
            if position.valuation is not None
            else fundamental.valuation if fundamental else None
        )
        revisions = position.revisions
        uses_sec_fundamentals = (
            fundamental is not None
            and (position.quality is None or position.valuation is None)
        )
        fundamental_is_fresh = True
        if uses_sec_fundamentals and fundamental.filed_at:
            fundamental_is_fresh = (
                date.fromisoformat(technicals.latest_date)
                - date.fromisoformat(fundamental.filed_at)
            ).days <= 550
        if position.symbol in theses:
            thesis = assess_thesis(
                theses[position.symbol],
                fundamental,
                date.fromisoformat(technicals.latest_date),
            )
        elif theses_provided and position.shares > 0:
            thesis = ThesisAssessment(
                symbol=position.symbol,
                status="MISSING",
                broken=False,
                review_due=True,
                reasons=("Held position has no recorded investment thesis.",),
                warnings=(),
            )
        alert = evaluate(
            SignalSnapshot(
                symbol=position.symbol,
                portfolio_weight=portfolio_weight,
                max_portfolio_weight=position.max_portfolio_weight,
                drawdown_from_high=technicals.drawdown_from_high,
                trend=technicals.trend,
                momentum=technicals.momentum,
                quality=quality or 0.0,
                valuation=valuation or 0.0,
                revisions=revisions or 0.0,
                revisions_available=revisions is not None,
                thesis_broken=position.thesis_broken or bool(thesis and thesis.broken),
                is_held=position.shares > 0,
                fundamentals_complete=(
                    quality is not None
                    and valuation is not None
                    and (revisions is not None or not policy.require_revisions_for_buy)
                    and fundamental_is_fresh
                ),
                portfolio_risk_allows_buy=risk.buy_allowed if risk else False,
                portfolio_risk_reasons=risk.reasons if risk else (
                    "Portfolio risk assessment is unavailable; buy and add review is blocked.",
                ),
                thesis_review_reasons=(
                    thesis.reasons if thesis else ()
                ),
            ),
            policy,
        )
        results.append(
            MonitorResult(
                position.symbol,
                position.shares,
                position.average_cost,
                position.shares * position.average_cost,
                technicals.latest_close,
                market_value,
                portfolio_weight,
                unrealized_return,
                fundamental,
                risk,
                thesis,
                technicals,
                alert,
                position.sector,
                position.theme,
            )
        )
    return results


def write_alert_history(
    results: list[MonitorResult],
    path: str | Path,
    model_version: str = MODEL_VERSION,
) -> None:
    """Append actionable monitor results to a JSONL audit trail."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    existing_keys = set()
    if output.exists():
        for line in output.read_text().splitlines():
            record = json.loads(line)
            existing_keys.add(record.get("event_key"))

    with output.open("a") as handle:
        for result in results:
            if result.alert.action == "HOLD":
                continue
            record = asdict(result)
            latest_date = (
                result.technicals.latest_date if result.technicals else "no-market-date"
            )
            event_key = "|".join(
                (
                    model_version,
                    result.symbol,
                    latest_date,
                    result.alert.action,
                    f"{result.alert.score:.4f}",
                    *result.alert.reasons,
                )
            )
            if event_key in existing_keys:
                continue
            record["alert_id"] = hashlib.sha256(event_key.encode()).hexdigest()[:20]
            record["model_version"] = model_version
            record["signal_date"] = latest_date
            record["entry_close"] = result.latest_close
            record["event_key"] = event_key
            record["observed_at"] = timestamp
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            existing_keys.add(event_key)


def write_decision_history(
    results: list[MonitorResult],
    path: str | Path,
    model_version: str = MODEL_VERSION,
) -> int:
    """Append every daily model decision, including HOLD, to an audit trail."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    existing_keys = set()
    if output.exists():
        existing_keys = {
            json.loads(line).get("event_key")
            for line in output.read_text().splitlines()
            if line.strip()
        }
    written = 0
    with output.open("a") as handle:
        for result in results:
            latest_date = (
                result.technicals.latest_date if result.technicals else "no-market-date"
            )
            event_key = "|".join(
                ("decision", model_version, result.symbol, latest_date, result.alert.action)
            )
            if event_key in existing_keys:
                continue
            record = asdict(result)
            record["decision_id"] = hashlib.sha256(event_key.encode()).hexdigest()[:20]
            record["model_version"] = model_version
            record["signal_date"] = latest_date
            record["entry_close"] = result.latest_close
            record["event_key"] = event_key
            record["observed_at"] = timestamp
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            existing_keys.add(event_key)
            written += 1
    return written


def write_monitor_snapshot(
    results: list[MonitorResult],
    path: str | Path,
    model_version: str = MODEL_VERSION,
) -> None:
    """Persist the full current monitor state, including HOLD results."""
    payload = {
        "model_version": model_version,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "results": [asdict(result) for result in results],
    }
    atomic_write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", path)
