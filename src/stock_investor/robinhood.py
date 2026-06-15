from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .data import Position, load_positions
from .io import atomic_text_writer, atomic_write_text


POSITION_FIELDS = (
    "symbol",
    "shares",
    "average_cost",
    "max_portfolio_weight",
    "quality",
    "valuation",
    "revisions",
    "thesis_broken",
    "cik",
    "sector",
    "theme",
)


@dataclass(frozen=True)
class RobinhoodImportSummary:
    imported_at: str
    account_count: int
    position_count: int
    skipped_non_equity_positions: int
    total_cash: float
    total_buying_power: float


def sanitize_robinhood_snapshot(
    payload: dict, captured_at: str | None = None
) -> dict:
    """Whitelist monitor inputs from a combined Robinhood read-only payload."""
    accounts = payload.get("accounts")
    if not isinstance(accounts, list) or not accounts:
        raise ValueError("Robinhood snapshot must contain a non-empty accounts list")
    sanitized_accounts = []
    for account in accounts:
        if not isinstance(account, dict):
            raise ValueError("each Robinhood account must be an object")
        sanitized_positions = []
        positions = account.get("positions", [])
        if not isinstance(positions, list):
            raise ValueError("account positions must be a list")
        for raw in positions:
            if not isinstance(raw, dict):
                raise ValueError("each Robinhood position must be an object")
            sanitized_positions.append(
                {
                    "symbol": str(raw.get("symbol", "")).strip().upper(),
                    "asset_type": str(raw.get("asset_type", "equity"))
                    .strip()
                    .lower(),
                    "quantity": _number(raw.get("quantity"), "quantity"),
                    "average_cost": _number(raw.get("average_cost"), "average_cost"),
                }
            )
        sanitized_accounts.append(
            {
                "cash": _number(
                    account.get("cash", 0), "cash", allow_negative=True
                ),
                "buying_power": _number(
                    account.get("buying_power", 0), "buying_power"
                ),
                "positions": sanitized_positions,
            }
        )
    return {
        "schema_version": 1,
        "captured_at": captured_at or datetime.now(timezone.utc).isoformat(),
        "accounts": sanitized_accounts,
    }


def _number(value: object, field: str, *, allow_negative: bool = False) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} must be numeric") from error
    if result < 0 and not allow_negative:
        raise ValueError(f"{field} cannot be negative")
    return result


def import_robinhood_snapshot(
    snapshot_path: str | Path,
    metadata_path: str | Path | None = None,
    default_max_weight: float = 0.10,
) -> tuple[list[Position], RobinhoodImportSummary]:
    """Convert a sanitized, read-only Robinhood MCP snapshot into monitor inputs."""
    if not 0 < default_max_weight <= 1:
        raise ValueError("default_max_weight must be above 0 and at most 1")
    payload = json.loads(Path(snapshot_path).read_text())
    accounts = payload.get("accounts")
    if not isinstance(accounts, list) or not accounts:
        raise ValueError("Robinhood snapshot must contain a non-empty accounts list")

    metadata = {
        position.symbol: position
        for position in load_positions(metadata_path)
    } if metadata_path else {}
    totals: dict[str, tuple[float, float]] = {}
    total_cash = 0.0
    total_buying_power = 0.0
    skipped_non_equity_positions = 0
    for account in accounts:
        if not isinstance(account, dict):
            raise ValueError("each Robinhood account must be an object")
        total_cash += _number(account.get("cash", 0), "cash", allow_negative=True)
        total_buying_power += _number(
            account.get("buying_power", 0), "buying_power"
        )
        positions = account.get("positions", [])
        if not isinstance(positions, list):
            raise ValueError("account positions must be a list")
        for raw in positions:
            asset_type = str(raw.get("asset_type", "equity")).strip().lower()
            if asset_type not in {"equity", "stock", "etf"}:
                skipped_non_equity_positions += 1
                continue
            symbol = str(raw.get("symbol", "")).strip().upper()
            if not symbol:
                raise ValueError("Robinhood position symbol cannot be empty")
            shares = _number(raw.get("quantity"), f"{symbol} quantity")
            average_cost = _number(raw.get("average_cost"), f"{symbol} average_cost")
            if shares == 0:
                continue
            prior_shares, prior_cost_basis = totals.get(symbol, (0.0, 0.0))
            totals[symbol] = (
                prior_shares + shares,
                prior_cost_basis + shares * average_cost,
            )

    positions = []
    for symbol, (shares, cost_basis) in sorted(totals.items()):
        prior = metadata.get(symbol)
        positions.append(
            Position(
                symbol=symbol,
                shares=shares,
                average_cost=cost_basis / shares,
                max_portfolio_weight=(
                    prior.max_portfolio_weight if prior else default_max_weight
                ),
                quality=prior.quality if prior else None,
                valuation=prior.valuation if prior else None,
                revisions=prior.revisions if prior else None,
                thesis_broken=prior.thesis_broken if prior else False,
                cik=prior.cik if prior else None,
                sector=prior.sector if prior else None,
                theme=prior.theme if prior else None,
            )
        )
    held_symbols = set(totals)
    positions.extend(
        position
        for symbol, position in sorted(metadata.items())
        if symbol not in held_symbols and position.shares == 0
    )
    if not positions:
        raise ValueError("Robinhood snapshot and metadata contain no positions")

    return positions, RobinhoodImportSummary(
        imported_at=datetime.now(timezone.utc).isoformat(),
        account_count=len(accounts),
        position_count=len(totals),
        skipped_non_equity_positions=skipped_non_equity_positions,
        total_cash=total_cash,
        total_buying_power=total_buying_power,
    )


def write_robinhood_import(
    positions: list[Position],
    summary: RobinhoodImportSummary,
    positions_path: str | Path,
    summary_path: str | Path,
) -> None:
    position_output = Path(positions_path)
    with atomic_text_writer(position_output, newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=POSITION_FIELDS)
        writer.writeheader()
        for position in positions:
            row = asdict(position)
            row["thesis_broken"] = str(position.thesis_broken).lower()
            writer.writerow(
                {
                    field: "" if row[field] is None else row[field]
                    for field in POSITION_FIELDS
                }
            )
    atomic_write_text(
        json.dumps(asdict(summary), indent=2, sort_keys=True) + "\n", summary_path
    )


def write_robinhood_baseline(
    positions: list[Position],
    summary: RobinhoodImportSummary,
    path: str | Path,
) -> bool:
    """Append a privacy-safe portfolio baseline unless the state is unchanged."""
    holdings = [
        {
            "symbol": position.symbol,
            "shares": position.shares,
            "average_cost": position.average_cost,
        }
        for position in sorted(positions, key=lambda item: item.symbol)
        if position.shares > 0
    ]
    state = {
        "total_cash": summary.total_cash,
        "total_buying_power": summary.total_buying_power,
        "holdings": holdings,
    }
    fingerprint = hashlib.sha256(
        json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    record = {
        "observed_at": summary.imported_at,
        "fingerprint": fingerprint,
        **state,
    }
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        records = [
            json.loads(line) for line in output.read_text().splitlines() if line.strip()
        ]
        if records and records[-1].get("fingerprint") == fingerprint:
            return False
    with output.open("a") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    return True


def load_robinhood_cash(path: str | Path) -> float:
    payload = json.loads(Path(path).read_text())
    return _number(payload.get("total_cash"), "total_cash", allow_negative=True)
