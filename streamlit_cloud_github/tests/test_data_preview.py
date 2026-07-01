import os
import sys
import unittest

import pandas as pd


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class DataPreviewTest(unittest.TestCase):
    def test_data_preview_rows_include_matching_alert_fields(self):
        from app_utils import build_data_preview
        from alert_engine import generate_alerts

        df = pd.DataFrame([
            {
                "time": pd.Timestamp("2024-08-12T12:00:00Z"),
                "lat": None,
                "lon": None,
                "alt": None,
                "variable": "Kp",
                "value": 8.0,
                "model": "SERENE Indices",
                "source": "SERENE API Kp/ap",
            },
            {
                "time": pd.Timestamp("2024-08-12T12:00:00Z"),
                "lat": None,
                "lon": None,
                "alt": None,
                "variable": "ap",
                "value": 207.0,
                "model": "SERENE Indices",
                "source": "SERENE API Kp/ap",
            },
        ])
        alerts = generate_alerts(df)

        preview = build_data_preview(df, alerts)

        self.assertIn("risk_level", preview.columns)
        self.assertIn("alert_type", preview.columns)
        self.assertEqual(set(preview["risk_level"]), {"G4 Severe"})
        self.assertEqual(set(preview["alert_type"]), {"Geomagnetic storm risk"})

    def test_data_preview_converts_mixed_object_values_for_streamlit(self):
        from app_utils import build_data_preview

        df = pd.DataFrame([
            {
                "time": pd.Timestamp("2026-01-19T23:55:00Z"),
                "lat": 50.0,
                "lon": -5.0,
                "variable": "TEC",
                "value": 7.3,
                "request_metadata": {"forecast": 90},
            },
            {
                "time": "N/A",
                "lat": None,
                "lon": None,
                "variable": "MUF3000F2",
                "value": pd.NA,
                "request_metadata": ["missing"],
            },
        ])

        preview = build_data_preview(df, pd.DataFrame())

        self.assertEqual(preview.loc[0, "time"], "2026-01-19 23:55:00 UTC")
        self.assertEqual(preview.loc[1, "time"], "N/A")
        self.assertIsInstance(preview.loc[0, "request_metadata"], str)
        self.assertIsInstance(preview.loc[1, "request_metadata"], str)


if __name__ == "__main__":
    unittest.main()
