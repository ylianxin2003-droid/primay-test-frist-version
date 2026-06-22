import os
import sys
import unittest
from datetime import date, time
from pathlib import Path


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class DashboardSettingsTest(unittest.TestCase):
    def test_app_uses_current_streamlit_width_parameter(self):
        app_source = Path(__file__).resolve().parents[1].joinpath("app.py").read_text()

        self.assertNotIn("use_container_width", app_source)

    def test_app_describes_local_grid_not_per_point_api_calls(self):
        app_source = Path(__file__).resolve().parents[1].joinpath("app.py").read_text()

        self.assertNotIn('"TOMIRIS"', app_source)
        self.assertNotIn("capped at {MAX_GRID_POINTS}", app_source)
        self.assertIn("Local map points", app_source)
        self.assertIn("AIDA datasets downloaded", app_source)

    def test_legacy_point_grid_api_path_is_removed(self):
        client_source = Path(__file__).resolve().parents[1].joinpath("serene_client.py").read_text()

        self.assertNotIn("MAX_GRID_POINTS", client_source)
        self.assertNotIn("def _fetch_calc_grid", client_source)
        self.assertNotIn("def fetch_model_output", client_source)

    def test_invalid_timeout_falls_back_to_default(self):
        from config import _parse_timeout

        self.assertEqual(_parse_timeout("not-a-number"), 30)
        self.assertEqual(_parse_timeout("0"), 30)
        self.assertEqual(_parse_timeout("45"), 45)

    def test_combine_date_time_to_iso8601(self):
        from app_utils import combine_date_time_iso

        value = combine_date_time_iso(date(2026, 6, 7), time(12, 0, 43))

        self.assertEqual(value, "2026-06-07T12:00:43")


if __name__ == "__main__":
    unittest.main()
