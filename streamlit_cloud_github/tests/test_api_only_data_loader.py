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

    def fetch_kp_ap_indices(self, **_kwargs):
        return False, "indices unavailable", pd.DataFrame()


class ApiOnlyDataLoaderTest(unittest.TestCase):
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

    def test_archive_time_uses_final_product(self):
        import data_loader

        client = FakeRawClient()
        with (
            patch.object(data_loader, "SereneClient", return_value=client),
            patch.object(data_loader, "calculate_aida_grid", side_effect=_fake_calculation),
        ):
            data_loader.load_data(start_time="2024-05-10T21:00:00Z")

        self.assertEqual(client.download_requests[0][1], "final")

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
