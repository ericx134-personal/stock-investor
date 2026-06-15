from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .io import atomic_write_text


@dataclass(frozen=True)
class FundamentalSnapshot:
    symbol: str
    cik: str
    filed_at: str
    fiscal_end: str
    quality: float | None
    valuation: float | None
    metrics: dict[str, float | None]
    warnings: tuple[str, ...]
    source: str = "SEC Company Facts"
    taxonomy: str = ""
    reporting_currency: str = ""
    annual_form: str = ""

    @property
    def complete(self) -> bool:
        return self.quality is not None and self.valuation is not None


def _clamp(value: float) -> float:
    return max(-1.0, min(1.0, value))


def _concept(payload: dict, taxonomy: str, names: tuple[str, ...], unit: str) -> list[dict]:
    facts = payload.get("facts", {}).get(taxonomy, {})
    for name in names:
        units = facts.get(name, {}).get("units", {})
        if unit in units:
            return units[unit]
    return []


ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}

CONCEPTS = {
    "us-gaap": {
        "revenue": ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"),
        "profit": ("NetIncomeLoss",),
        "operating_cash": ("NetCashProvidedByUsedInOperatingActivities",),
        "capex": (
            "PaymentsToAcquirePropertyPlantAndEquipment",
            "PaymentsForAdditionsToPropertyPlantAndEquipment",
        ),
        "assets": ("Assets",),
        "liabilities": ("Liabilities",),
        "shares": ("CommonStockSharesOutstanding",),
    },
    "ifrs-full": {
        "revenue": ("Revenue",),
        "profit": ("ProfitLoss",),
        "operating_cash": ("CashFlowsFromUsedInOperatingActivities",),
        "capex": (
            "PurchaseOfPropertyPlantAndEquipment",
            "PurchaseOfPropertyPlantAndEquipmentIntangibleAssetsOtherThanGoodwillInvestmentPropertyAndBiologicalAssets",
        ),
        "assets": ("Assets",),
        "liabilities": ("Liabilities",),
        "shares": ("NumberOfSharesOutstanding",),
    },
}


def _annual(entries: list[dict]) -> list[dict]:
    valid = [
        item
        for item in entries
        if item.get("form") in ANNUAL_FORMS
        and item.get("fp") == "FY"
        and item.get("filed")
        and item.get("end")
    ]
    by_end: dict[str, dict] = {}
    for item in sorted(valid, key=lambda value: value["filed"]):
        by_end[item["end"]] = item
    return sorted(by_end.values(), key=lambda value: value["end"], reverse=True)


def _value_for_end(
    payload: dict,
    taxonomy: str,
    names: tuple[str, ...],
    end: str,
    unit: str = "USD",
) -> tuple[float | None, dict | None]:
    entries = [
        item for item in _annual(_concept(payload, taxonomy, names, unit))
        if item["end"] == end
    ]
    return (float(entries[0]["val"]), entries[0]) if entries else (None, None)


def _latest_value(
    payload: dict, taxonomy: str, names: tuple[str, ...], unit: str = "USD"
) -> tuple[float | None, dict | None]:
    entries = _annual(_concept(payload, taxonomy, names, unit))
    return (float(entries[0]["val"]), entries[0]) if entries else (None, None)


def _latest_two(
    payload: dict, taxonomy: str, names: tuple[str, ...], unit: str = "USD"
) -> tuple[float | None, float | None, dict | None]:
    entries = _annual(_concept(payload, taxonomy, names, unit))
    if not entries:
        return None, None, None
    return (
        float(entries[0]["val"]),
        float(entries[1]["val"]) if len(entries) > 1 else None,
        entries[0],
    )


def _reporting_basis(payload: dict) -> tuple[str, str]:
    """Choose the latest supported annual revenue series and its currency."""
    candidates = []
    for taxonomy, concepts in CONCEPTS.items():
        facts = payload.get("facts", {}).get(taxonomy, {})
        for name in concepts["revenue"]:
            for unit, entries in facts.get(name, {}).get("units", {}).items():
                annual = _annual(entries)
                if annual:
                    candidates.append((annual[0]["end"], annual[0]["filed"], taxonomy, unit))
    if not candidates:
        return "", ""
    _, _, taxonomy, unit = max(candidates)
    return taxonomy, unit


def calculate_fundamentals(
    symbol: str, cik: str, payload: dict, market_price: float
) -> FundamentalSnapshot:
    """Calculate conservative scores from standardized annual SEC facts."""
    if market_price <= 0:
        raise ValueError("market_price must be positive")
    taxonomy, reporting_currency = _reporting_basis(payload)
    concepts = CONCEPTS.get(taxonomy, CONCEPTS["us-gaap"])
    revenue, prior_revenue, revenue_fact = _latest_two(
        payload,
        taxonomy,
        concepts["revenue"],
        reporting_currency,
    )
    target_end = revenue_fact["end"] if revenue_fact else ""
    net_income, net_fact = _value_for_end(
        payload, taxonomy, concepts["profit"], target_end, reporting_currency
    )
    operating_cash, cash_fact = _value_for_end(
        payload,
        taxonomy,
        concepts["operating_cash"],
        target_end,
        reporting_currency,
    )
    capex, _ = _value_for_end(
        payload,
        taxonomy,
        concepts["capex"],
        target_end,
        reporting_currency,
    )
    assets, assets_fact = _value_for_end(
        payload, taxonomy, concepts["assets"], target_end, reporting_currency
    )
    liabilities, _ = _value_for_end(
        payload, taxonomy, concepts["liabilities"], target_end, reporting_currency
    )
    # Current-price valuation uses the latest annual-filing share count; unlike
    # income and balance-sheet components, its cover-page date may not equal FY end.
    shares, shares_fact = _latest_value(
        payload, taxonomy, concepts["shares"], "shares"
    )
    if shares is None:
        dei_entries = _annual(
            _concept(
                payload,
                "dei",
                ("EntityCommonStockSharesOutstanding",),
                "shares",
            )
        )
        shares = float(dei_entries[0]["val"]) if dei_entries else None
        shares_fact = dei_entries[0] if dei_entries else None

    free_cash_flow = (
        operating_cash - abs(capex)
        if operating_cash is not None and capex is not None
        else None
    )
    # Foreign ordinary-share counts and non-USD facts cannot safely be compared
    # with a USD-listed ADR price without a point-in-time ADR ratio and FX rate.
    valuation_compatible = taxonomy == "us-gaap" and reporting_currency == "USD"
    market_cap = (
        market_price * shares
        if shares is not None and valuation_compatible
        else None
    )
    metrics = {
        "net_margin": net_income / revenue if net_income is not None and revenue else None,
        "free_cash_flow_margin": free_cash_flow / revenue
        if free_cash_flow is not None and revenue
        else None,
        "return_on_assets": net_income / assets if net_income is not None and assets else None,
        "equity_ratio": (assets - liabilities) / assets
        if assets and liabilities is not None
        else None,
        "revenue_growth": revenue / prior_revenue - 1
        if revenue is not None and prior_revenue
        else None,
        "earnings_yield": net_income / market_cap
        if net_income is not None and market_cap
        else None,
        "free_cash_flow_yield": free_cash_flow / market_cap
        if free_cash_flow is not None and market_cap
        else None,
    }

    quality_parts = [
        _clamp(metrics["net_margin"] / 0.20) if metrics["net_margin"] is not None else None,
        _clamp(metrics["free_cash_flow_margin"] / 0.15)
        if metrics["free_cash_flow_margin"] is not None
        else None,
        _clamp(metrics["return_on_assets"] / 0.15)
        if metrics["return_on_assets"] is not None
        else None,
        _clamp((metrics["equity_ratio"] - 0.20) / 0.40)
        if metrics["equity_ratio"] is not None
        else None,
        _clamp(metrics["revenue_growth"] / 0.20)
        if metrics["revenue_growth"] is not None
        else None,
    ]
    valuation_parts = [
        _clamp(metrics["earnings_yield"] / 0.08)
        if metrics["earnings_yield"] is not None
        else None,
        _clamp(metrics["free_cash_flow_yield"] / 0.08)
        if metrics["free_cash_flow_yield"] is not None
        else None,
    ]
    quality_values = [value for value in quality_parts if value is not None]
    valuation_values = [value for value in valuation_parts if value is not None]
    quality = sum(quality_values) / len(quality_values) if len(quality_values) >= 4 else None
    valuation = (
        sum(valuation_values) / len(valuation_values)
        if len(valuation_values) == 2
        else None
    )

    warnings = []
    if quality is None:
        warnings.append("Insufficient standardized SEC facts for a quality score.")
    if valuation is None:
        warnings.append("Insufficient standardized SEC facts for a valuation score.")
    if taxonomy == "ifrs-full":
        warnings.append(
            "IFRS quality ratios are supported, but valuation is disabled without "
            "point-in-time ADR-ratio and currency-conversion data."
        )
    warnings.append(
        "SEC-derived scores are not sector-adjusted; review financial companies separately."
    )
    facts = [
        fact
        for fact in (revenue_fact, net_fact, cash_fact, assets_fact, shares_fact)
        if fact
    ]
    filed_at = max((fact["filed"] for fact in facts), default="")
    fiscal_end = target_end
    return FundamentalSnapshot(
        symbol=symbol,
        cik=cik.zfill(10),
        filed_at=filed_at,
        fiscal_end=fiscal_end,
        quality=quality,
        valuation=valuation,
        metrics=metrics,
        warnings=tuple(warnings),
        taxonomy=taxonomy,
        reporting_currency=reporting_currency,
        annual_form=revenue_fact.get("form", "") if revenue_fact else "",
    )


def write_fundamentals(
    snapshots: dict[str, FundamentalSnapshot], path: str | Path
) -> None:
    atomic_write_text(
        json.dumps(
            {symbol: asdict(snapshot) for symbol, snapshot in snapshots.items()},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        path,
    )


def load_fundamentals(path: str | Path) -> dict[str, FundamentalSnapshot]:
    payload = json.loads(Path(path).read_text())
    return {
        symbol: FundamentalSnapshot(
            **{**values, "warnings": tuple(values.get("warnings", ()))}
        )
        for symbol, values in payload.items()
    }
