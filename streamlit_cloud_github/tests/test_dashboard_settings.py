import os
import sys
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "app.py"
CLIENT_PATH = PROJECT_ROOT / "serene_client.py"
REQUIREMENTS_PATH = PROJECT_ROOT / "requirements.txt"
ENV_EXAMPLE_PATH = PROJECT_ROOT / ".env.example"


class DashboardSettingsTest(unittest.TestCase):
    def test_app_uses_current_streamlit_width_parameter(self):
        app_source = APP_PATH.read_text()

        self.assertNotIn("use_container_width", app_source)

    def test_app_describes_local_grid_not_per_point_api_calls(self):
        app_source = APP_PATH.read_text()

        self.assertNotIn('"TOMIRIS"', app_source)
        self.assertNotIn("capped at {MAX_GRID_POINTS}", app_source)
        self.assertIn("Local map points", app_source)
        self.assertIn("AIDA raw datasets downloaded", app_source)
        self.assertIn("calculated locally", app_source)
        self.assertNotIn("output catalog", app_source.lower())

    def test_legacy_point_grid_api_path_is_removed(self):
        client_source = CLIENT_PATH.read_text()

        self.assertNotIn("MAX_GRID_POINTS", client_source)
        self.assertNotIn("def _fetch_calc_grid", client_source)
        self.assertNotIn("def fetch_model_output", client_source)

    def test_legacy_catalogue_code_is_removed(self):
        client_source = CLIENT_PATH.read_text()

        self.assertNotIn("BeautifulSoup", client_source)
        self.assertNotIn("fetch_aida_catalog", client_source)
        self.assertNotIn("param_2d", client_source)
        self.assertIn("breid-phys/aida-ionosphere", client_source)

    def test_invalid_timeout_falls_back_to_default(self):
        from config import _parse_timeout

        self.assertEqual(_parse_timeout("not-a-number"), 30)
        self.assertEqual(_parse_timeout("0"), 30)
        self.assertEqual(_parse_timeout("45"), 45)

    def test_upstream_aida_dependency_is_pinned(self):
        requirements = REQUIREMENTS_PATH.read_text()

        self.assertIn("numpy>=1.25,<2", requirements)
        self.assertIn("pandas<2", requirements)
        self.assertIn(
            "git+https://github.com/breid-phys/aida-ionosphere.git@v0.1.3",
            requirements,
        )
        self.assertNotIn("beautifulsoup4", requirements)

    def test_example_uses_raw_api_host(self):
        example = ENV_EXAMPLE_PATH.read_text()

        self.assertIn(
            "SERENE_API_BASE_URL=https://spaceweather.bham.ac.uk",
            example,
        )

    def test_combine_date_time_to_iso8601(self):
        from app_utils import combine_date_time_iso

        value = combine_date_time_iso(date(2026, 6, 7), time(12, 0, 43))

        self.assertEqual(value, "2026-06-07T12:00:43")

    def test_default_time_range_avoids_unpublished_near_realtime_output(self):
        from app_utils import default_time_range

        now = datetime(2026, 6, 22, 18, 49, 37, tzinfo=timezone.utc)

        start, end = default_time_range(now)

        self.assertEqual(end, now.replace(microsecond=0) - timedelta(minutes=15))
        self.assertEqual(start, end - timedelta(hours=6))

    def test_aida_date_inputs_use_archive_minimum(self):
        app_source = APP_PATH.read_text()

        self.assertEqual(app_source.count("min_value=AIDA_ARCHIVE_START"), 2)


if __name__ == "__main__":
    unittest.main()
