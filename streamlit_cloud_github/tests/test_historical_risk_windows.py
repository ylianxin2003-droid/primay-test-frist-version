import os
import sys
import unittest

import pandas as pd


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class HistoricalRiskWindowsTest(unittest.TestCase):
    def test_selected_range_generates_severe_historical_advisory(self):
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

        self.assertEqual(overall, "Severe")

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
