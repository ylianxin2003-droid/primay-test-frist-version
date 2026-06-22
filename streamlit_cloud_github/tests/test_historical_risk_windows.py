import os
import sys
import unittest

import pandas as pd


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class HistoricalRiskWindowsTest(unittest.TestCase):
    def test_historical_events_start_in_2024_or_later(self):
        from app_utils import historical_risk_windows

        windows = historical_risk_windows()
        starts = pd.to_datetime(
            windows["Select range"].str.split(" to ").str[0],
            utc=True,
        )

        self.assertTrue((starts >= pd.Timestamp("2024-01-01", tz="UTC")).all())

    def test_historical_table_contains_recent_serene_events(self):
        from app_utils import historical_risk_windows

        windows = historical_risk_windows()

        self.assertIn("Risk", windows.columns)
        self.assertIn("G5 Extreme geomagnetic storm", set(windows["Risk"]))
        self.assertIn(
            "2024-05-10T18:00:00 to 2024-05-11T18:00:00",
            set(windows["Select range"]),
        )

    def test_select_range_parses_to_sidebar_widget_values(self):
        from datetime import date, time

        from app_utils import parse_select_range_to_widgets

        parsed = parse_select_range_to_widgets(
            "2024-05-10T18:00:00 to 2024-05-11T18:00:00"
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["start_date"], date(2024, 5, 10))
        self.assertEqual(parsed["start_time_clock"], time(18, 0))
        self.assertEqual(parsed["end_date"], date(2024, 5, 11))
        self.assertEqual(parsed["end_time_clock"], time(18, 0))

    def test_selected_range_generates_g5_historical_advisory(self):
        from alert_engine import generate_overall_risk
        from app_utils import generate_historical_risk_alerts

        alerts = generate_historical_risk_alerts(
            "2024-05-11T00:00:00",
            "2024-05-12T23:59:00",
        )

        self.assertFalse(alerts.empty)
        self.assertIn("Historical geomagnetic storm window", set(alerts["alert_type"]))
        self.assertIn("G5 Extreme", " ".join(alerts["reason"]))

        overall, _summary = generate_overall_risk(alerts)

        self.assertEqual(overall, "G5 Extreme")

    def test_non_matching_range_generates_no_historical_advisory(self):
        from app_utils import generate_historical_risk_alerts

        alerts = generate_historical_risk_alerts(
            "2024-06-01T00:00:00",
            "2024-06-01T12:00:00",
        )

        self.assertTrue(alerts.empty)
        self.assertIsInstance(alerts, pd.DataFrame)


if __name__ == "__main__":
    unittest.main()
