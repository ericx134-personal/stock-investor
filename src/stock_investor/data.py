from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class Position:
    symbol: str
    shares: float
    average_cost: float
    max_portfolio_weight: float
    quality: float | None
    valuation: float | None
    revisions: float | None
    thesis_broken: bool = False
    cik: str | None = None
    sector: str | None = None
    theme: str | None = None


@dataclass(frozen=True)
class Price:
    date: date
    close: float
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: float | None = None


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no", ""}:
        return False
    raise ValueError(f"invalid boolean value: {value!r}")


def _parse_optional_float(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    return float(value)


def load_positions(path: str | Path) -> list[Position]:
    with Path(path).open(newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "symbol",
            "shares",
            "average_cost",
            "max_portfolio_weight",
            "quality",
            "valuation",
            "revisions",
            "thesis_broken",
        }
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"positions CSV missing columns: {sorted(missing)}")
        positions = []
        for row in reader:
            position = Position(
                symbol=row["symbol"].strip().upper(),
                shares=float(row["shares"]),
                average_cost=float(row["average_cost"]),
                max_portfolio_weight=float(row["max_portfolio_weight"]),
                quality=_parse_optional_float(row["quality"]),
                valuation=_parse_optional_float(row["valuation"]),
                revisions=_parse_optional_float(row["revisions"]),
                thesis_broken=_parse_bool(row["thesis_broken"]),
                cik=(row.get("cik") or "").strip() or None,
                sector=(row.get("sector") or "").strip() or None,
                theme=(row.get("theme") or "").strip() or None,
            )
            if not position.symbol:
                raise ValueError("position symbol cannot be empty")
            if position.shares < 0 or position.average_cost < 0:
                raise ValueError(f"{position.symbol} has a negative position value")
            if not 0 < position.max_portfolio_weight <= 1:
                raise ValueError(
                    f"{position.symbol} max_portfolio_weight must be above 0 and at most 1"
                )
            for name in ("quality", "valuation", "revisions"):
                value = getattr(position, name)
                if value is not None and not -1 <= value <= 1:
                    raise ValueError(f"{position.symbol} {name} must be between -1 and 1")
            if position.cik and not position.cik.isdigit():
                raise ValueError(f"{position.symbol} CIK must contain only digits")
            positions.append(position)
    if not positions:
        raise ValueError("positions CSV is empty")
    if len({item.symbol for item in positions}) != len(positions):
        raise ValueError("positions CSV contains duplicate symbols")
    return positions


def load_prices(path: str | Path) -> dict[str, list[Price]]:
    prices: dict[str, list[Price]] = {}
    with Path(path).open(newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"date", "symbol", "close"}
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"prices CSV missing columns: {sorted(missing)}")
        for row in reader:
            symbol = row["symbol"].strip().upper()
            close = float(row["close"])
            if close <= 0:
                raise ValueError(f"{symbol} has non-positive close")
            optional = {
                name: _parse_optional_float(row.get(name))
                for name in ("open", "high", "low", "volume")
            }
            if optional["high"] is not None and optional["high"] < close:
                raise ValueError(f"{symbol} high is below close")
            if optional["low"] is not None and optional["low"] > close:
                raise ValueError(f"{symbol} low is above close")
            prices.setdefault(symbol, []).append(
                Price(date.fromisoformat(row["date"]), close, **optional)
            )
    for symbol, history in prices.items():
        history.sort(key=lambda item: item.date)
        if len({item.date for item in history}) != len(history):
            raise ValueError(f"{symbol} has duplicate price dates")
    return prices
