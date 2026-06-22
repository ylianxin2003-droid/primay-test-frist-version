import os
import sys
import unittest

import pandas as pd


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class ForecastEngineTest(unittest.TestCase):
    def test_high_tec_generates_warning_or_severe_forecast(self):
        from forecast_engine import aggregate_forecast_for_map, generate_risk_forecast

        df = pd.DataFrame([
            {
                "time": pd.Timestamp("2026-06-16T10:00:00Z"),
                "lat": 55.0,
                "lon": -3.0,
                "variable": "TEC",
                "value": 95.0,
                "model": "AIDA",
            },
            {
                "time": pd.Timestamp("2026-06-16T11:00:00Z"),
                "lat": 55.0,
                "lon": -3.0,
                "variable": "TEC",
                "value": 125.0,
                "model": "AIDA",
            },
        ])

        forecast = generate_risk_forecast(df)
        mapped = aggregate_forecast_for_map(forecast, horizon="Now")

        self.assertFalse(forecast.empty)
        self.assertEqual(mapped.loc[0, "risk_level"], "Severe")
        self.assertGreaterEqual(float(mapped.loc[0, "risk_probability"]), 0.8)

    def test_kp_does_not_raise_mappable_cells(self):
        from forecast_engine import aggregate_forecast_for_map, generate_risk_forecast

        df = pd.DataFrame([
            {
                "time": pd.Timestamp("2026-06-16T10:00:00Z"),
                "lat": 50.0,
                "lon": 1.0,
                "variable": "TEC",
                "value": 10.0,
            },
            {
                "time": pd.Timestamp("2026-06-16T10:00:00Z"),
                "lat": None,
                "lon": None,
                "variable": "Kp",
                "value": 8.0,
            },
        ])

        forecast = generate_risk_forecast(df)
        mapped = aggregate_forecast_for_map(forecast, horizon="Now")

        self.assertEqual(mapped.loc[0, "risk_level"], "Normal")
        self.assertEqual(mapped.loc[0, "driver"], "TEC persistence")

    def test_single_timestamp_is_labelled_as_low_confidence_persistence(self):
        from forecast_engine import generate_risk_forecast

        df = pd.DataFrame([
            {
                "time": pd.Timestamp("2026-06-16T10:00:00Z"),
                "lat": 50.0,
                "lon": 1.0,
                "variable": "TEC",
                "value": 10.0,
            },
        ])

        forecast = generate_risk_forecast(df)

        self.assertTrue((forecast["driver"] == "TEC persistence").all())
        self.assertLessEqual(float(forecast["confidence"].max()), 0.45)
        self.assertIn("persistence", forecast.iloc[0]["explanation"].lower())

    def test_risk_forecast_map_draws_points(self):
        from forecast_engine import generate_risk_forecast
        from forecast_visualisation import create_risk_forecast_map

        df = pd.DataFrame([
            {"lat": 52.0, "lon": -1.0, "variable": "TEC", "value": 70.0},
            {"lat": 54.0, "lon": -2.0, "variable": "TEC", "value": 130.0},
        ])

        forecast = generate_risk_forecast(df)
        fig = create_risk_forecast_map(forecast, horizon="Now")

        point_count = sum(len(trace.lat) for trace in fig.data if hasattr(trace, "lat"))
        self.assertEqual(point_count, 2)


if __name__ == "__main__":
    unittest.main()
