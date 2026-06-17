import tempfile
import unittest
from pathlib import Path

from stock_investor.data import load_positions, load_prices


class DataTests(unittest.TestCase):
    def write(self, directory, name, content):
        path = Path(directory) / name
        path.write_text(content)
        return path

    def test_load_positions_normalizes_symbols(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                directory,
                "positions.csv",
                "symbol,shares,average_cost,max_portfolio_weight,quality,"
                "valuation,revisions,thesis_broken\n"
                " aapl ,2,100,0.2,0.5,0.1,-0.2,no\n",
            )
            self.assertEqual(load_positions(path)[0].symbol, "AAPL")

    def test_load_positions_rejects_duplicate_symbols(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                directory,
                "positions.csv",
                "symbol,shares,average_cost,max_portfolio_weight,quality,"
                "valuation,revisions,thesis_broken\n"
                "AAPL,2,100,0.2,0.5,0.1,-0.2,no\n"
                "aapl,1,120,0.2,0.5,0.1,-0.2,no\n",
            )
            with self.assertRaisesRegex(ValueError, "duplicate"):
                load_positions(path)

    def test_load_positions_allows_blank_fundamentals_and_reads_cik(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                directory,
                "positions.csv",
                "symbol,shares,average_cost,max_portfolio_weight,quality,"
                "valuation,revisions,thesis_broken,cik,sector,theme\n"
                "AAPL,2,100,0.2,,,,no,320193,Technology,AI\n",
            )
            position = load_positions(path)[0]
            self.assertIsNone(position.quality)
            self.assertEqual(position.cik, "320193")
            self.assertEqual(position.sector, "Technology")
            self.assertEqual(position.theme, "AI")

    def test_load_prices_sorts_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                directory,
                "prices.csv",
                "date,symbol,close\n2026-01-02,ABC,12\n2026-01-01,ABC,10\n",
            )
            history = load_prices(path)["ABC"]
            self.assertEqual([price.close for price in history], [10.0, 12.0])

    def test_load_prices_rejects_invalid_ohlcv_relationships(self):
        invalid_rows = {
            "high is below open": "2026-01-01,ABC,10,12,11,9,100\n",
            "low is above open": "2026-01-01,ABC,10,8,12,9,100\n",
            "negative volume": "2026-01-01,ABC,10,10,11,9,-1\n",
        }
        with tempfile.TemporaryDirectory() as directory:
            for message, row in invalid_rows.items():
                path = self.write(
                    directory,
                    message.replace(" ", "-") + ".csv",
                    "date,symbol,close,open,high,low,volume\n" + row,
                )
                with self.assertRaisesRegex(ValueError, message):
                    load_prices(path)

    def test_load_prices_can_normalize_existing_provider_rows_for_merge(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                directory,
                "prices.csv",
                "date,symbol,close,open,high,low,volume\n"
                "2026-01-01,ABC,10,12,11,9,100\n",
            )
            history = load_prices(path, strict_ohlcv=False)["ABC"]
            self.assertEqual(history[0].high, 12)
            self.assertEqual(history[0].low, 9)
