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
README_PATH = PROJECT_ROOT / "README.md"


class DashboardSettingsTest(unittest.TestCase):
    def test_app_uses_current_streamlit_width_parameter(self):
        app_source = APP_PATH.read_text()

        self.assertNotIn("use_container_width", app_source)

    def test_app_describes_local_grid_not_per_point_api_calls(self):
        app_source = APP_PATH.read_text()

        self.assertNotIn('"TOMIRIS"', app_source)
        self.assertNotIn("capped at {MAX_GRID_POINTS}", app_source)
        self.assertIn("Local map points", app_source)
        self.assertIn("Rolling/analysis states", app_source)
        self.assertIn("Official forecast states", app_source)
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
        self.assertIn("SERENE_AIDA_ARCHIVE_START=2024-09-28T00:00:00Z", example)

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

        self.assertEqual(app_source.count("min_value=AIDA_ARCHIVE_START"), 1)
        self.assertIn('"Analysis date"', app_source)
        self.assertNotIn('"Start date"', app_source)

    def test_app_distinguishes_global_and_regional_risk(self):
        app_source = APP_PATH.read_text()

        self.assertIn("Global Kp/ap are excluded", app_source)
        self.assertIn("analysis time", app_source)
        self.assertIn('st.metric(f"Peak {variable}"', app_source)

    def test_app_exposes_serene_only_icao_products(self):
        app_source = APP_PATH.read_text()

        self.assertIn("ICAO/PECASUS-style summary table", app_source)
        self.assertIn("Overall risk status", app_source)
        self.assertIn("Categorical risk map", app_source)
        self.assertIn("Raw variable maps", app_source)
        self.assertIn("Automated text-based SPWX research messages", app_source)
        self.assertIn("load_icao_products", app_source)
        self.assertIn("build_icao_summary", app_source)
        self.assertIn("create_icao_category_map", app_source)
        self.assertIn("only SERENE-supported, derived, or proxy indicators", app_source)
        self.assertNotIn("Not available from SERENE", app_source)
        self.assertIn("generate_icao_message", app_source)
        self.assertIn("Download GNSS research message", app_source)
        self.assertIn("Download HF COM research message", app_source)

    def test_app_exposes_quick_demo_and_full_icao_modes(self):
        app_source = APP_PATH.read_text()

        self.assertIn("Quick Demo", app_source)
        self.assertIn("Full ICAO-style mode", app_source)
        self.assertIn("include_three_hour_window", app_source)
        self.assertIn("include_psd_baseline", app_source)
        self.assertIn("Demo / validation storm windows", app_source)
        self.assertNotIn("Historical risk windows", app_source)

    def test_event_windows_are_optional_shortcuts_not_time_locks(self):
        app_source = APP_PATH.read_text()

        self.assertIn("Custom analysis time can be entered manually", app_source)
        self.assertIn("Use selected event time", app_source)
        self.assertIn("apply_event_time_sidebar", app_source)
        self.assertIn("apply_event_time_main", app_source)

    def test_app_defaults_to_global_grid_and_cache_mode(self):
        app_source = APP_PATH.read_text()

        self.assertIn('st.number_input("Lat min", value=-90.0', app_source)
        self.assertIn('st.number_input("Lat max", value=90.0', app_source)
        self.assertIn('st.number_input("Lon min", value=-180.0', app_source)
        self.assertIn('st.number_input("Lon max", value=180.0', app_source)
        self.assertIn('st.slider("Grid step (degrees)", 2.0, 30.0, 15.0, 1.0)', app_source)
        self.assertIn("The default grid is global for aviation-scale awareness", app_source)
        self.assertIn("Cached trial output", app_source)
        self.assertIn("Live SERENE API", app_source)

    def test_app_mentions_cached_trial_outputs_in_method_text(self):
        app_source = APP_PATH.read_text()

        self.assertIn("cached trial outputs", app_source.lower())
        self.assertIn("Live SERENE API", app_source)
        self.assertIn("Save current result as cached trial output", app_source)

    def test_prediction_columns_disclose_forecast_source(self):
        app_source = APP_PATH.read_text()

        self.assertNotIn("generate_risk_forecast", app_source)
        self.assertNotIn("Official product horizon", app_source)
        self.assertIn("Prediction horizon", app_source)
        self.assertIn("Forecast source: SERENE", app_source)
        self.assertIn("dashboard-generated forecast", app_source)

    def test_app_exposes_hf_propagation_case_study(self):
        app_source = APP_PATH.read_text()
        app_one_line = app_source.replace("\n", " ")
        readme = README_PATH.read_text()

        self.assertIn("Engineering Impact: HF Communication Coverage", app_source)
        self.assertIn("Phase 1: MUF-based coverage proxy", app_source)
        self.assertIn("Phase 2: experimental Trace", app_source)
        self.assertIn("Trace HF ray-tracing", app_source)
        self.assertIn("MUF-threshold demonstration", app_source)
        self.assertIn("Quiet coverage", app_source)
        self.assertIn("Storm coverage", app_source)
        self.assertIn("Coverage loss", app_source)
        self.assertIn("Quiet route availability", app_source)
        self.assertIn("Route coverage reduction", app_source)
        self.assertIn("Degraded route points", app_source)
        self.assertIn("Frequency sweep", app_source)
        self.assertIn("Research comparison only", app_source)
        self.assertIn("not recommend operational frequencies", app_source)
        self.assertIn("not an operational", app_one_line)
        self.assertIn("not a full propagation solver", app_one_line)
        self.assertIn("HF propagation case study", readme)
        self.assertIn("not run full Trace ray tracing", readme)
        self.assertIn("Engineering decision-support workflow", readme)
        self.assertIn("Communication Impact", readme)

    def test_app_exposes_validation_section_for_decision_support(self):
        app_source = APP_PATH.read_text()

        self.assertIn("Validation and engineering assumptions", app_source)
        self.assertIn("Historical event replay", app_source)
        self.assertIn("Quiet vs storm comparison", app_source)
        self.assertIn("PSD sensitivity", app_source)
        self.assertIn("Frequency sensitivity", app_source)
        self.assertIn("Route assessment verification", app_source)
        self.assertIn("MUF-threshold engineering proxy", app_source)

    def test_readme_explains_prediction_fallback_sources(self):
        readme = README_PATH.read_text()
        readme_one_line = readme.replace("\n", " ")

        self.assertIn("The +90 min, +3h, and +6h columns are prediction outputs.", readme)
        self.assertIn("official SERENE AIDA forecasts when available", readme_one_line)
        self.assertIn("persistence or trend-based extrapolation", readme_one_line)
        self.assertIn(
            "Each horizon has its own source column to avoid misrepresenting "
            "generated predictions as official",
            readme_one_line,
        )
        self.assertNotIn(
            "columns use official SERENE AIDA forecast HDF5 products",
            readme,
        )


if __name__ == "__main__":
    unittest.main()
