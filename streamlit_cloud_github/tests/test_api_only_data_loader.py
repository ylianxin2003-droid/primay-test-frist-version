import os
import sys
import unittest
from unittest.mock import patch

import pandas as pd


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


GLOBAL_REGION = {"lat_min": -90, "lat_max": 90, "lon_min": -180, "lon_max": 180}


def _fake_calculation(_payload, region, step, variables):
    variable = (variables or ["TEC"])[0]
    return pd.DataFrame([{
        "time": pd.Timestamp("2026-06-21T20:00:00Z"),
        "lat": float(region["lat_min"]),
        "lon": float(region["lon_min"]),
        "variable": variable,
        "value": float(step),
        "model": "AIDA",
        "source": "test upstream adapter",
    }])


class FakeRawClient:
    def __init__(self):
        self.download_requests = []

    def download_aida_raw_output(self, requested_time, latency):
        self.download_requests.append((requested_time, latency))
        return True, f"downloaded {requested_time or 'latest'}", b"raw-state"

    def download_aida_forecast(self, requested_time, latency, period_minutes):
        self.forecast_requests = getattr(self, "forecast_requests", [])
        self.forecast_requests.append((requested_time, latency, period_minutes))
        return True, f"forecast {period_minutes}", b"forecast-state"

    def fetch_kp_ap_indices(self, **_kwargs):
        return False, "indices unavailable", pd.DataFrame()


class ApiOnlyDataLoaderTest(unittest.TestCase):
    def test_three_hour_schedule_has_37_five_minute_states(self):
        import data_loader

        times = data_loader.three_hour_aida_times("2026-06-21T20:00:00Z")

        self.assertEqual(len(times), 37)
        self.assertEqual(times[0], pd.Timestamp("2026-06-21T17:00:00Z"))
        self.assertEqual(times[-1], pd.Timestamp("2026-06-21T20:00:00Z"))
        self.assertTrue(all(
            right - left == pd.Timedelta(minutes=5)
            for left, right in zip(times, times[1:])
        ))

    def test_psd_reference_schedule_uses_previous_30_days_at_same_utc(self):
        import data_loader

        times = data_loader.psd_reference_times("2026-06-21T20:00:00Z")

        self.assertEqual(len(times), 30)
        self.assertEqual(times[0], pd.Timestamp("2026-05-22T20:00:00Z"))
        self.assertEqual(times[-1], pd.Timestamp("2026-06-20T20:00:00Z"))

    def test_icao_products_use_one_download_per_time_and_official_forecasts(self):
        import data_loader

        client = FakeRawClient()
        with (
            patch.object(data_loader, "SereneClient", return_value=client),
            patch.object(data_loader, "calculate_aida_grid", side_effect=_fake_calculation),
        ):
            bundle = data_loader.load_icao_products(
                analysis_time="2026-06-21T20:00:00Z",
                variables=["TEC"],
                region=GLOBAL_REGION,
                grid_step=30,
                include_psd_baseline=False,
            )

        self.assertEqual(len(client.download_requests), 37)
        self.assertEqual(len(set(client.download_requests)), 37)
        self.assertEqual(client.forecast_requests, [
            ("2026-06-21T21:30:00+00:00", "ultra", 90),
            ("2026-06-21T23:00:00+00:00", "ultra", 180),
            ("2026-06-22T02:00:00+00:00", "ultra", 360),
        ])
        self.assertIn("analysis", set(bundle.products["product_kind"]))
        self.assertIn("rolling", set(bundle.products["product_kind"]))
        self.assertIn("forecast_90", set(bundle.products["product_kind"]))
        self.assertIn("forecast_180", set(bundle.products["product_kind"]))
        self.assertIn("forecast_360", set(bundle.products["product_kind"]))
        self.assertEqual(bundle.status.metadata["analysis_downloads"], 37)
        self.assertEqual(bundle.status.metadata["rolling_analysis_downloads"], 37)
        self.assertEqual(bundle.status.metadata["forecast_downloads"], 3)
        self.assertEqual(
            [row["forecast_parameter"] for row in bundle.status.metadata["forecast_request_audit"]],
            [90, 180, 360],
        )

    def test_icao_products_keep_observations_when_forecasts_fail(self):
        import data_loader

        class ForecastFailingClient(FakeRawClient):
            def download_aida_forecast(self, requested_time, latency, period_minutes):
                return False, f"forecast {period_minutes} unavailable", None

        client = ForecastFailingClient()
        with (
            patch.object(data_loader, "SereneClient", return_value=client),
            patch.object(data_loader, "calculate_aida_grid", side_effect=_fake_calculation),
        ):
            bundle = data_loader.load_icao_products(
                analysis_time="2026-06-21T20:00:00Z",
                variables=["TEC"],
                region=GLOBAL_REGION,
                grid_step=30,
                include_three_hour_window=False,
                include_psd_baseline=False,
            )

        self.assertFalse(bundle.products.empty)
        self.assertEqual(set(bundle.products["product_kind"]), {"analysis", "rolling"})
        self.assertTrue(any("forecast 90 unavailable" in item for item in bundle.status.warnings))
        self.assertTrue(any("forecast 180 unavailable" in item for item in bundle.status.warnings))

    def test_psd_reference_tolerates_two_missing_daily_states(self):
        import data_loader

        products = pd.DataFrame([
            {
                "product_kind": "baseline",
                "requested_time": pd.Timestamp("2026-05-01T12:00:00Z") + pd.Timedelta(days=index),
                "lat": 50.0,
                "lon": 1.0,
                "variable": "MUF3000F2",
                "value": 10.0,
            }
            for index in range(28)
        ] + [{
            "product_kind": "analysis",
            "requested_time": pd.Timestamp("2026-06-01T12:00:00Z"),
            "lat": 50.0,
            "lon": 1.0,
            "variable": "MUF3000F2",
            "value": 7.0,
        }])

        result = data_loader._attach_psd_reference(products)

        analysis = result[result["product_kind"] == "analysis"].iloc[0]
        self.assertEqual(float(analysis["reference_value"]), 10.0)
        self.assertAlmostEqual(float(analysis["psd_percent"]), 30.0)

    def test_psd_reference_tolerates_three_missing_daily_states(self):
        import data_loader

        products = pd.DataFrame([
            {
                "product_kind": "baseline",
                "requested_time": pd.Timestamp("2026-05-01T12:00:00Z") + pd.Timedelta(days=index),
                "lat": 50.0,
                "lon": 1.0,
                "variable": "MUF3000F2",
                "value": 10.0,
            }
            for index in range(27)
        ] + [{
            "product_kind": "analysis",
            "requested_time": pd.Timestamp("2026-06-01T12:00:00Z"),
            "lat": 50.0,
            "lon": 1.0,
            "variable": "MUF3000F2",
            "value": 7.0,
        }])

        result = data_loader._attach_psd_reference(products)

        analysis = result[result["product_kind"] == "analysis"].iloc[0]
        self.assertEqual(float(analysis["reference_value"]), 10.0)
        self.assertAlmostEqual(float(analysis["psd_percent"]), 30.0)

    def test_psd_reference_uses_30_day_median(self):
        import data_loader

        products = pd.DataFrame([
            {
                "product_kind": "baseline",
                "requested_time": pd.Timestamp("2026-05-01T12:00:00Z") + pd.Timedelta(days=index),
                "lat": 50.0,
                "lon": 1.0,
                "variable": "MUF3000F2",
                "value": 10.0,
            }
            for index in range(30)
        ] + [{
            "product_kind": "analysis",
            "requested_time": pd.Timestamp("2026-06-01T12:00:00Z"),
            "lat": 50.0,
            "lon": 1.0,
            "variable": "MUF3000F2",
            "value": 7.0,
        }])

        result = data_loader._attach_psd_reference(products)

        analysis = result[result["product_kind"] == "analysis"].iloc[0]
        self.assertEqual(float(analysis["reference_value"]), 10.0)
        self.assertAlmostEqual(float(analysis["psd_percent"]), 30.0)

    def test_loader_aggregates_baseline_before_building_product_table(self):
        import data_loader

        client = FakeRawClient()
        captured = {}

        def capture_reference(products, reference=None):
            captured["product_kinds"] = set(products["product_kind"])
            captured["reference"] = reference
            return products

        with (
            patch.object(data_loader, "SereneClient", return_value=client),
            patch.object(data_loader, "calculate_aida_grid", side_effect=_fake_calculation),
            patch.object(data_loader, "_attach_psd_reference", side_effect=capture_reference),
        ):
            data_loader.load_icao_products(
                analysis_time="2026-06-21T20:00:00Z",
                variables=["MUF3000F2"],
                region=GLOBAL_REGION,
                grid_step=30,
                include_three_hour_window=False,
                include_psd_baseline=True,
            )

        self.assertNotIn("baseline", captured["product_kinds"])
        self.assertIsInstance(captured["reference"], pd.DataFrame)
        self.assertEqual(float(captured["reference"].iloc[0]["reference_value"]), 30.0)

    def test_loader_summarises_missing_psd_baseline_files(self):
        import data_loader

        class PartlyMissingBaselineClient(FakeRawClient):
            def download_aida_raw_output(self, requested_time, latency):
                parsed = pd.Timestamp(requested_time)
                if parsed.date().isoformat() in {"2026-05-22", "2026-05-23"}:
                    return (
                        False,
                        f"SERENE AIDA raw-output API returned status 404 for "
                        f"product={latency}, file_type=raw, file_time={parsed:%Y-%m-%dT%H:%M:%S}. "
                        '"Requested file is not available for download."',
                        None,
                    )
                return super().download_aida_raw_output(requested_time, latency)

        client = PartlyMissingBaselineClient()
        with (
            patch.object(data_loader, "SereneClient", return_value=client),
            patch.object(data_loader, "calculate_aida_grid", side_effect=_fake_calculation),
        ):
            bundle = data_loader.load_icao_products(
                analysis_time="2026-06-21T20:00:00Z",
                variables=["MUF3000F2"],
                region=GLOBAL_REGION,
                grid_step=30,
                include_three_hour_window=False,
                include_psd_baseline=True,
            )

        warnings = "\n".join(bundle.status.warnings)
        self.assertIn("PSD reference used 28/30 available SERENE AIDA states", warnings)
        self.assertNotIn("raw-output API returned status 404", warnings)
        self.assertEqual(bundle.status.metadata["baseline_download_failures"], 2)
        self.assertFalse(bundle.products["psd_percent"].dropna().empty)

    def test_loader_uses_psd_baseline_with_twenty_seven_reference_states(self):
        import data_loader

        class ThreeMissingBaselineClient(FakeRawClient):
            def download_aida_raw_output(self, requested_time, latency):
                parsed = pd.Timestamp(requested_time)
                if parsed.date().isoformat() in {
                    "2026-05-22", "2026-05-23", "2026-05-24",
                }:
                    return (
                        False,
                        f"SERENE AIDA raw-output API returned status 404 for "
                        f"product={latency}, file_type=raw, file_time={parsed:%Y-%m-%dT%H:%M:%S}. "
                        '"Requested file is not available for download."',
                        None,
                    )
                return super().download_aida_raw_output(requested_time, latency)

        client = ThreeMissingBaselineClient()
        with (
            patch.object(data_loader, "SereneClient", return_value=client),
            patch.object(data_loader, "calculate_aida_grid", side_effect=_fake_calculation),
        ):
            bundle = data_loader.load_icao_products(
                analysis_time="2026-06-21T20:00:00Z",
                variables=["MUF3000F2"],
                region=GLOBAL_REGION,
                grid_step=30,
                include_three_hour_window=False,
                include_psd_baseline=True,
            )

        warnings = "\n".join(bundle.status.warnings)
        self.assertIn("PSD reference used 27/30 available SERENE AIDA states", warnings)
        self.assertEqual(bundle.status.metadata["baseline_download_failures"], 3)
        self.assertEqual(bundle.status.metadata["baseline_reference_states_used"], 27)
        self.assertFalse(bundle.products["psd_percent"].dropna().empty)

    def test_early_archive_window_skips_psd_and_summarises_missing_forecasts(self):
        import data_loader

        class MissingForecastClient(FakeRawClient):
            def download_aida_forecast(self, requested_time, latency, period_minutes):
                return (
                    False,
                    f"SERENE AIDA forecast API returned status 404 for "
                    f"product={latency}, file_type=raw, file_time=2024-10-11T02:55:00, "
                    f"forecast_period={period_minutes} min. "
                    '"Requested file is not available for download."',
                    None,
                )

        client = MissingForecastClient()
        with (
            patch.object(data_loader, "SereneClient", return_value=client),
            patch.object(data_loader, "calculate_aida_grid", side_effect=_fake_calculation),
        ):
            bundle = data_loader.load_icao_products(
                analysis_time="2024-10-11T02:55:00Z",
                variables=["MUF3000F2"],
                region=GLOBAL_REGION,
                grid_step=30,
                include_three_hour_window=False,
                include_psd_baseline=True,
            )

        warnings = "\n".join(bundle.status.warnings)
        self.assertIn("PSD unavailable", warnings)
        self.assertIn("archive boundary", warnings)
        self.assertIn("Official AIDA +3h forecast unavailable", warnings)
        self.assertIn("Official AIDA +6h forecast unavailable", warnings)
        self.assertNotIn("only 13/30", warnings)
        self.assertNotIn("forecast API returned status 404", warnings)
        self.assertEqual(bundle.status.metadata["baseline_state_count"], 0)

    def test_api_failure_does_not_fall_back_to_local_file(self):
        import data_loader

        class FailingClient:
            def download_aida_raw_output(self, *_args):
                return False, "raw download failed", None

            def fetch_kp_ap_indices(self, **_kwargs):
                return False, "indices failed", pd.DataFrame()

        with patch.object(data_loader, "SereneClient", return_value=FailingClient()):
            frame, status = data_loader.load_data(source="api")

        self.assertTrue(frame.empty)
        self.assertEqual(status.source, "none")
        self.assertFalse(status.ok)
        self.assertNotIn("fallback", status.message.lower())

    def test_grid_density_does_not_change_raw_download_count(self):
        import data_loader

        coarse_client = FakeRawClient()
        with (
            patch.object(data_loader, "SereneClient", return_value=coarse_client),
            patch.object(data_loader, "calculate_aida_grid", side_effect=_fake_calculation),
        ):
            _coarse_frame, coarse = data_loader.load_data(
                start_time="2026-06-21T20:00:00Z",
                end_time="2026-06-21T21:00:00Z",
                variables=["TEC"],
                region=GLOBAL_REGION,
                grid_step=30,
            )

        dense_client = FakeRawClient()
        with (
            patch.object(data_loader, "SereneClient", return_value=dense_client),
            patch.object(data_loader, "calculate_aida_grid", side_effect=_fake_calculation),
        ):
            _dense_frame, dense = data_loader.load_data(
                start_time="2026-06-21T20:00:00Z",
                end_time="2026-06-21T21:00:00Z",
                variables=["TEC"],
                region=GLOBAL_REGION,
                grid_step=2,
            )

        self.assertEqual(len(coarse_client.download_requests), 2)
        self.assertEqual(len(dense_client.download_requests), 2)
        self.assertEqual(coarse.metadata["aida_dataset_downloads"], 2)
        self.assertEqual(dense.metadata["aida_dataset_downloads"], 2)
        self.assertEqual(coarse.metadata["local_map_points"], 91)
        self.assertEqual(dense.metadata["local_map_points"], 16471)

    def test_duplicate_time_and_latency_download_once(self):
        import data_loader

        client = FakeRawClient()
        with (
            patch.object(data_loader, "SereneClient", return_value=client),
            patch.object(data_loader, "calculate_aida_grid", side_effect=_fake_calculation),
        ):
            _frame, status = data_loader.load_data(
                start_time="2026-06-21T20:00:00Z",
                end_time="2026-06-21T20:00:00Z",
            )

        self.assertEqual(len(client.download_requests), 1)
        self.assertEqual(status.metadata["aida_dataset_downloads"], 1)

    def test_times_rounded_to_same_five_minute_output_download_once(self):
        import data_loader

        client = FakeRawClient()
        with (
            patch.object(data_loader, "SereneClient", return_value=client),
            patch.object(data_loader, "calculate_aida_grid", side_effect=_fake_calculation),
        ):
            _frame, status = data_loader.load_data(
                start_time="2026-06-21T20:00:01Z",
                end_time="2026-06-21T20:02:29Z",
            )

        self.assertEqual(len(client.download_requests), 1)
        self.assertEqual(
            client.download_requests[0],
            ("2026-06-21T20:00:00+00:00", "ultra"),
        )
        self.assertEqual(status.metadata["aida_dataset_downloads"], 1)

    def test_archive_time_uses_rapid_product_for_five_minute_raw_states(self):
        import data_loader

        client = FakeRawClient()
        with (
            patch.object(data_loader, "SereneClient", return_value=client),
            patch.object(data_loader, "calculate_aida_grid", side_effect=_fake_calculation),
        ):
            data_loader.load_data(start_time="2024-05-10T21:00:00Z")

        self.assertEqual(client.download_requests[0][1], "rapid")

    def test_indices_only_result_does_not_claim_aida_success(self):
        import data_loader

        indices = pd.DataFrame([{
            "time": pd.Timestamp("2026-06-21T21:00:00Z"),
            "lat": None,
            "lon": None,
            "variable": "Kp",
            "value": 5.0,
            "model": "SERENE Indices",
            "source": "SERENE API Kp/ap",
        }])

        class IndicesOnlyClient:
            def download_aida_raw_output(self, *_args):
                return False, "raw download failed", None

            def fetch_kp_ap_indices(self, **_kwargs):
                return True, "indices ok", indices

        with patch.object(data_loader, "SereneClient", return_value=IndicesOnlyClient()):
            frame, status = data_loader.load_data(
                start_time="2026-06-21T20:00:00Z",
                end_time="2026-06-21T21:00:00Z",
            )

        self.assertEqual(set(frame["variable"]), {"Kp"})
        self.assertFalse(status.ok)
        self.assertEqual(status.source, "indices")
        self.assertIn("regional AIDA", status.message)


if __name__ == "__main__":
    unittest.main()
