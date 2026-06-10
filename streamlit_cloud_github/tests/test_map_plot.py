import os
import sys
import unittest

import pandas as pd


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class MapPlotTest(unittest.TestCase):
    def test_kp_ap_without_coordinates_shows_clear_message(self):
        from visualisation import create_map_plot

        df = pd.DataFrame([
            {
                "time": pd.Timestamp("2024-05-11T00:00:00Z"),
                "lat": None,
                "lon": None,
                "variable": "Kp",
                "value": 9.0,
            },
            {
                "time": pd.Timestamp("2024-05-11T00:00:00Z"),
                "lat": None,
                "lon": None,
                "variable": "ap",
                "value": 400.0,
            },
        ])

        fig = create_map_plot(df, variable="Kp")

        annotation_texts = [ann.text for ann in fig.layout.annotations]
        self.assertIn("No mappable lat/lon data for Kp.", annotation_texts)
        self.assertEqual(len(fig.data), 0)

    def test_mappable_variable_options_exclude_global_indices(self):
        from app_utils import mappable_variable_options

        df = pd.DataFrame([
            {"lat": None, "lon": None, "variable": "Kp", "value": 9.0},
            {"lat": None, "lon": None, "variable": "ap", "value": 400.0},
            {"lat": 60.0, "lon": -5.0, "variable": "TEC", "value": 8.2},
        ])

        self.assertEqual(mappable_variable_options(df), ["TEC"])

    def test_calc_grid_parser_fills_missing_point_coordinates(self):
        from app_utils import mappable_variable_options
        from serene_client import SereneClient

        batch = [
            {
                "lat": 60.0,
                "lon": -10.0,
                "model": "AIDA",
                "response": {
                    "data": [
                        {"variable": "TEC", "value": 8.2, "lat": None, "lon": None},
                    ],
                },
            },
        ]

        df = SereneClient().parse_response_to_dataframe(batch, model="AIDA")

        self.assertEqual(mappable_variable_options(df), ["TEC"])
        self.assertEqual(float(df.loc[0, "lat"]), 60.0)
        self.assertEqual(float(df.loc[0, "lon"]), -10.0)

    def test_map_keeps_tec_points_without_valid_time(self):
        from visualisation import create_map_plot

        df = pd.DataFrame([
            {
                "time": None,
                "lat": 60.0,
                "lon": -10.0,
                "variable": "TEC",
                "value": 8.2,
            },
            {
                "time": None,
                "lat": 60.0,
                "lon": -5.0,
                "variable": "TEC",
                "value": 8.6,
            },
        ])

        fig = create_map_plot(df, variable="TEC")

        point_count = sum(len(trace.lat) for trace in fig.data if hasattr(trace, "lat"))
        self.assertEqual(point_count, 2)
        self.assertEqual(len(fig.layout.annotations), 0)

    def test_time_series_uses_sample_index_without_valid_time(self):
        from visualisation import create_time_series_plot

        df = pd.DataFrame([
            {"time": None, "variable": "TEC", "value": 8.2},
            {"time": None, "variable": "TEC", "value": 8.6},
        ])

        fig = create_time_series_plot(df, variable="TEC")

        point_count = sum(len(trace.x) for trace in fig.data if hasattr(trace, "x"))
        self.assertEqual(point_count, 2)


if __name__ == "__main__":
    unittest.main()
