"""Generate deterministic demo prices for the monitor example."""

import csv
from datetime import date, timedelta
from pathlib import Path


def series(start: float, daily_change: float, shock_after: int | None = None):
    value = start
    for day in range(300):
        variation = (0.0015, -0.0008, 0.0004, -0.0005)[day % 4]
        value *= 1 + daily_change + variation
        if shock_after is not None and day >= shock_after:
            value *= 0.997
        yield day, value


output = Path(__file__).with_name("prices.csv")
start_date = date(2025, 1, 1)
with output.open("w", newline="") as handle:
    writer = csv.writer(handle)
    writer.writerow(("date", "symbol", "close"))
    for symbol, values in (
        ("STEADY", series(80, 0.0012)),
        ("SLIPPING", series(130, 0.0002, shock_after=220)),
        ("WATCH", series(45, 0.0015)),
    ):
        for day, close in values:
            writer.writerow((start_date + timedelta(days=day), symbol, f"{close:.4f}"))
print(output)
