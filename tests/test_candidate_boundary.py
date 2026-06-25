import unittest

from stock_investor.candidate_boundary import build_candidate_boundary
from stock_investor.data import Position


class CandidateBoundaryTests(unittest.TestCase):
    def test_boundary_keeps_watchlists_out_of_direction_forecasts(self):
        positions = [
            Position("HELD", 10, 5, 0.2, None, None, None),
            Position("CSVWATCH", 0, 0, 0.2, None, None, None),
        ]
        broker_universe = {
            "watchlist_only": [
                {"symbol": "MOOWATCH"},
                {"symbol": "CSVWATCH"},
            ]
        }
        forecasts = [{"symbol": "HELD", "direction": "WAIT"}]

        payload = build_candidate_boundary(
            positions,
            forecasts,
            broker_universe=broker_universe,
            generated_at="2026-06-25T12:00:00+00:00",
        )

        self.assertEqual(payload["forecast_scope"], "held_positions_only")
        self.assertEqual(payload["held_symbols"], ["HELD"])
        self.assertEqual(payload["csv_watchlist_symbols"], ["CSVWATCH"])
        self.assertEqual(payload["broker_watchlist_only_symbols"], ["CSVWATCH", "MOOWATCH"])
        self.assertEqual(payload["research_candidate_symbols"], ["CSVWATCH", "MOOWATCH"])
        self.assertEqual(payload["direction_forecast_violations"], [])

    def test_boundary_reports_non_held_forecast_violation(self):
        positions = [Position("HELD", 1, 5, 0.2, None, None, None)]
        payload = build_candidate_boundary(
            positions,
            [{"symbol": "WATCH", "direction": "BUY"}],
            generated_at="2026-06-25T12:00:00+00:00",
        )

        self.assertEqual(payload["direction_forecast_violations"], ["WATCH"])
        self.assertEqual(payload["counts"]["direction_forecast_violations"], 1)

    def test_boundary_can_fall_back_to_moomoo_watchlist_payload(self):
        positions = [Position("HELD", 1, 5, 0.2, None, None, None)]
        moomoo = {
            "unique_symbols": ["HELD", "WATCH"],
            "items": [{"symbol": "EXTRA"}],
        }

        payload = build_candidate_boundary(
            positions,
            [{"symbol": "HELD", "direction": "WAIT"}],
            moomoo_watchlists=moomoo,
            generated_at="2026-06-25T12:00:00+00:00",
        )

        self.assertEqual(payload["broker_watchlist_only_symbols"], ["EXTRA", "WATCH"])


if __name__ == "__main__":
    unittest.main()
