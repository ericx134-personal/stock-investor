from __future__ import annotations

import json
from pathlib import Path


def load_account_cash(path: str | Path) -> float:
    payload = json.loads(Path(path).read_text())
    return _number(payload.get("total_cash"), "total_cash", allow_negative=True)


def _number(value: object, field: str, *, allow_negative: bool = False) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} must be numeric") from error
    if result < 0 and not allow_negative:
        raise ValueError(f"{field} cannot be negative")
    return result
