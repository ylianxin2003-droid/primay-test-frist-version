import os
import sys
import unittest

import pandas as pd


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class IcaoVisualisationTest(unittest.TestCase):
    def test_category_map_draws_one_point_per_cell(self):
        from icao_visualisation import create_icao_category_map

        cells = pd.DataFrame([
            _cell(50, -3, 100, "OK"),
            _cell(55, 0, 150, "MODERATE"),
            _cell(60, 3, 180, "SEVERE"),
        ])

        fig = create_icao_category_map(cells, "Vertical TEC - Latest")

        self.assertEqual(sum(len(trace.lat) for trace in fig.data), 3)
        self.assertEqual(
            {trace.name for trace in fig.data},
            {"OK", "MODERATE", "SEVERE"},
        )
        self.assertEqual(fig.layout.geo.fitbounds, "locations")
        hover_templates = " ".join(trace.hovertemplate for trace in fig.data)
        self.assertIn("threshold_explanation", hover_templates)
        self.assertIn("product_state", hover_templates)

    def test_global_kp_is_never_drawn_as_regional_cells(self):
        from icao_visualisation import create_icao_category_map

        kp = pd.DataFrame([{
            "time": pd.Timestamp("2026-06-24T12:00:00Z"),
            "lat": 60,
            "lon": 0,
            "variable": "Kp",
            "display_value": 9,
            "category": "SEVERE",
            "indicator": "Auroral absorption proxy",
            "unit": "Kp",
            "source": "SERENE Indices",
        }])

        fig = create_icao_category_map(kp, "Kp")

        self.assertEqual(len(fig.data), 0)
        self.assertIn("not a regional map", fig.layout.annotations[0].text.lower())

    def test_empty_cells_show_an_explanation(self):
        from icao_visualisation import create_icao_category_map

        fig = create_icao_category_map(pd.DataFrame(), "Unavailable")

        self.assertEqual(len(fig.data), 0)
        self.assertIn("no regional", fig.layout.annotations[0].text.lower())

    def test_unavailable_cell_is_drawn_in_grey_category(self):
        from icao_visualisation import create_icao_category_map

        cell = _cell(50, -3, "N/A", "UNAVAILABLE")

        fig = create_icao_category_map(pd.DataFrame([cell]), "Unavailable cell")

        self.assertEqual(sum(len(trace.lat) for trace in fig.data), 1)
        self.assertEqual(fig.data[0].name, "UNAVAILABLE")


def _cell(lat, lon, value, category):
    return {
        "time": pd.Timestamp("2026-06-24T12:00:00Z"),
        "lat": lat,
        "lon": lon,
        "variable": "TEC",
        "display_value": value,
        "category": category,
        "indicator": "Vertical TEC",
        "horizon": "Latest",
        "unit": "TECU",
        "source": "SERENE AIDA",
        "threshold_explanation": "TEC: OK <125, MODERATE 125-175, SEVERE >=175",
        "product_state": "analysis",
    }


if __name__ == "__main__":
    unittest.main()
