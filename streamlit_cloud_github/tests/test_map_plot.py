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


if __name__ == "__main__":
    unittest.main()
