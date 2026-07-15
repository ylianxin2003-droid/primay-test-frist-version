import os
import sys
import unittest

import pandas as pd


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class HfCoverageTest(unittest.TestCase):
    def test_psd_degrades_cells_that_were_usable_in_quiet_state(self):
        from hf_coverage import build_hf_coverage_case

        data = pd.DataFrame([
            {
                "time": "2025-01-01T12:00:00Z",
                "lat": 52.0,
                "lon": -5.0,
                "variable": "MUF3000F2",
                "value": 12.0,
                "product_kind": "analysis",
            },
            {
                "time": "2025-01-01T12:00:00Z",
                "lat": 45.0,
                "lon": -35.0,
                "variable": "MUF3000F2",
                "value": 8.0,
                "product_kind": "analysis",
            },
        ])

        case, summary = build_hf_coverage_case(data, frequency_mhz=10.0, psd_percent=30.0)

        self.assertEqual(summary["quiet_available_count"], 1)
        self.assertEqual(summary["storm_available_count"], 0)
        self.assertEqual(summary["degraded_count"], 1)
        self.assertEqual(
            case.loc[case["quiet_muf_mhz"] == 12.0, "coverage_change"].iloc[0],
            "Degraded during storm",
        )

    def test_latest_analysis_grid_is_used_for_case_study(self):
        from hf_coverage import latest_muf_grid

        data = pd.DataFrame([
            {
                "time": "2025-01-01T11:00:00Z",
                "lat": 52.0,
                "lon": -5.0,
                "variable": "MUF3000F2",
                "value": 20.0,
                "product_kind": "analysis",
            },
            {
                "time": "2025-01-01T12:00:00Z",
                "lat": 52.0,
                "lon": -5.0,
                "variable": "MUF3000F2",
                "value": 14.0,
                "product_kind": "analysis",
            },
        ])

        grid = latest_muf_grid(data)

        self.assertEqual(len(grid), 1)
        self.assertEqual(float(grid["quiet_muf_mhz"].iloc[0]), 14.0)

    def test_empty_case_is_returned_when_no_spatial_muf_grid_exists(self):
        from hf_coverage import build_hf_coverage_case

        data = pd.DataFrame([
            {"time": "2025-01-01T12:00:00Z", "variable": "Kp", "value": 8.0},
        ])

        case, summary = build_hf_coverage_case(data, frequency_mhz=10.0, psd_percent=30.0)

        self.assertTrue(case.empty)
        self.assertEqual(summary["total_cells"], 0)
        self.assertIn("MUF3000F2", summary["message"])

    def test_hf_coverage_map_contains_route_and_cells(self):
        try:
            import plotly  # noqa: F401
        except ModuleNotFoundError:
            self.skipTest("plotly is not installed in this local test interpreter")

        from hf_coverage import DEFAULT_UK_TRANSMITTER, create_hf_coverage_map

        case = pd.DataFrame([
            {
                "lat": 52.0,
                "lon": -5.0,
                "quiet_muf_mhz": 12.0,
                "storm_muf_mhz": 8.4,
                "selected_frequency_mhz": 10.0,
                "coverage_change": "Degraded during storm",
            }
        ])

        fig = create_hf_coverage_map(case, DEFAULT_UK_TRANSMITTER)

        self.assertGreaterEqual(len(fig.data), 2)
        self.assertEqual(len(fig.layout.annotations), 0)


if __name__ == "__main__":
    unittest.main()
