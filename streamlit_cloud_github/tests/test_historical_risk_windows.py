import os
import sys
import unittest

import pandas as pd


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class HistoricalRiskWindowsTest(unittest.TestCase):
    def test_historical_events_respect_aida_archive_start(self):
        from app_utils import AIDA_ARCHIVE_START, historical_risk_windows

        windows = historical_risk_windows()
        starts = pd.to_datetime(
            windows["Select range"].str.split(" to ").str[0],
            utc=True,
        )

        archive_start = pd.Timestamp(AIDA_ARCHIVE_START, tz="UTC")
        self.assertTrue((starts >= archive_start).all())

    def test_historical_table_contains_recent_serene_events(self):
        from app_utils import historical_risk_windows

        windows = historical_risk_windows()

        self.assertIn("Risk", windows.columns)
        self.assertIn("Peak Kp", windows.columns)
        self.assertIn("Peak ap", windows.columns)
        self.assertNotIn("Kp", windows.columns)
        self.assertNotIn("ap", windows.columns)
        self.assertIn(
            "2024-10-10T18:00:00 to 2024-10-11T02:55:00",
            set(windows["Select range"]),
        )

    def test_historical_load_ranges_stop_inside_the_displayed_interval(self):
        from app_utils import historical_risk_windows

        windows = historical_risk_windows()
        ends = pd.to_datetime(
            windows["Select range"].str.split(" to ").str[1],
            utc=True,
        )

        self.assertTrue((ends.dt.minute == 55).all())

    def test_select_range_parses_to_sidebar_widget_values(self):
        from datetime import date, time

        from app_utils import parse_select_range_to_widgets

        parsed = parse_select_range_to_widgets(
            "2024-10-10T18:00:00 to 2024-10-11T02:55:00"
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["start_date"], date(2024, 10, 10))
        self.assertEqual(parsed["start_time_clock"], time(18, 0))
        self.assertEqual(parsed["end_date"], date(2024, 10, 11))
        self.assertEqual(parsed["end_time_clock"], time(2, 55))

    def test_selected_range_generates_g4_historical_advisory(self):
        from alert_engine import generate_overall_risk
        from app_utils import generate_historical_risk_alerts

        alerts = generate_historical_risk_alerts(
            "2024-10-10T18:00:00",
            "2024-10-11T03:00:00",
        )

        self.assertFalse(alerts.empty)
        self.assertIn("Historical geomagnetic storm window", set(alerts["alert_type"]))
        self.assertIn("G4 Severe", " ".join(alerts["reason"]))

        overall, _summary = generate_overall_risk(alerts)

        self.assertEqual(overall, "G4 Severe")

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
