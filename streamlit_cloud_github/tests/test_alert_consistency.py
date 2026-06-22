import os
import sys
import unittest

import pandas as pd


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class AlertConsistencyTest(unittest.TestCase):
    def _alerts_input(self):
        timestamp = pd.Timestamp("2025-01-01T15:00:00Z")
        return pd.DataFrame([
            {"time": timestamp, "lat": None, "lon": None, "variable": "Kp", "value": 8.0},
            {"time": timestamp, "lat": None, "lon": None, "variable": "ap", "value": 207.0},
            {"time": timestamp, "lat": 50.0, "lon": 0.0, "variable": "TEC", "value": 85.0},
        ])

    def test_kp_and_ap_are_one_global_geomagnetic_advisory(self):
        from alert_engine import generate_alerts

        alerts = generate_alerts(self._alerts_input())
        geomagnetic = alerts[alerts["alert_type"] == "Geomagnetic storm risk"]

        self.assertEqual(len(geomagnetic), 1)
        self.assertEqual(len(alerts), 2)
        self.assertIn("Kp = 8.00", geomagnetic.iloc[0]["reason"])
        self.assertIn("ap = 207.00", geomagnetic.iloc[0]["reason"])

    def test_overall_summary_describes_loaded_sample_peak(self):
        from alert_engine import generate_alerts, generate_overall_risk

        overall, summary = generate_overall_risk(generate_alerts(self._alerts_input()))

        self.assertEqual(overall, "G4 Severe")
        self.assertIn("loaded-sample peak", summary.lower())

    def test_alert_summary_keeps_g4_category(self):
        from visualisation import create_alert_summary

        alerts = pd.DataFrame([
            {"alert_type": "Geomagnetic storm risk", "risk_level": "G4 Severe"},
            {"alert_type": "GNSS positioning risk", "risk_level": "Warning"},
        ])
        figure = create_alert_summary(alerts)

        self.assertEqual({trace.name for trace in figure.data}, {"G4 Severe", "Warning"})
        self.assertEqual(sum(sum(trace.y) for trace in figure.data), 2)

    def test_g4_timeline_is_red_and_equal_times_get_readable_range(self):
        from visualisation import RISK_COLORS, create_alert_timeline

        alerts = pd.DataFrame([
            {"timestamp": "2025-01-01T15:00:00Z", "alert_type": "Geomagnetic storm risk", "risk_level": "G4 Severe", "region": "Global", "reason": "Kp/ap peak"},
            {"timestamp": "2025-01-01T15:00:00Z", "alert_type": "GNSS positioning risk", "risk_level": "Warning", "region": "Mid-lat N", "reason": "TEC peak"},
        ])
        figure = create_alert_timeline(alerts)

        self.assertEqual(figure.data[0].marker.color, RISK_COLORS["G4 Severe"])
        self.assertIsNotNone(figure.layout.xaxis.range)
        self.assertIn("UTC", figure.layout.xaxis.tickformat)


if __name__ == "__main__":
    unittest.main()
