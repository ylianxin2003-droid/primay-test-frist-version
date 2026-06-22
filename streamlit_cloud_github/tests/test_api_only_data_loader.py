import os
import sys
import unittest
from io import BytesIO
from unittest.mock import patch

import h5py
import numpy as np
import pandas as pd


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class ApiOnlyDataLoaderTest(unittest.TestCase):
    def test_api_failure_does_not_fall_back_to_local_file(self):
        import data_loader

        class FailingClient:
            def fetch_aida_catalog(self, *_args):
                return False, "catalog failed", []

            def fetch_kp_ap_indices(self, **_kwargs):
                return False, "indices failed", pd.DataFrame()

        with patch.object(data_loader, "SereneClient", return_value=FailingClient()):
            df, status = data_loader.load_data(source="api")

        self.assertTrue(df.empty)
        self.assertEqual(status.source, "none")
        self.assertFalse(status.ok)
        self.assertNotIn("fallback", status.message.lower())

    @staticmethod
    def _aida_payload():
        buffer = BytesIO()
        latitudes = np.arange(-90.0, 91.0, 1.0)
        longitudes = np.arange(-180.0, 180.0, 1.0)
        values = np.add.outer(longitudes, latitudes)
        with h5py.File(buffer, "w") as handle:
            handle.create_dataset("Latitudes", data=latitudes)
            handle.create_dataset("Longitudes", data=longitudes)
            for variable in ("TEC", "foF2", "MUF3000F2", "NmF2", "hmF2"):
                handle.create_dataset(variable, data=values)
        return buffer.getvalue()

    def _fake_aida_client(self, same_output=False):
        from serene_client import AidaOutput, SereneClient

        first = AidaOutput(
            "1",
            pd.Timestamp("2026-06-21T20:00:00Z"),
            "ultra",
            "assimilation",
            "/output/1/param_2d/download/",
        )
        second = first if same_output else AidaOutput(
            "2",
            pd.Timestamp("2026-06-21T21:00:00Z"),
            "ultra",
            "assimilation",
            "/output/2/param_2d/download/",
        )

        class FakeClient:
            def __init__(self, payload):
                self.payload = payload
                self.download_count = 0

            def fetch_model_output(self, **_kwargs):
                raise AssertionError("point-grid fetch_model_output must not be used")

            def fetch_aida_catalog(self, _cadence, _kind):
                return True, "catalog ok", [first, second]

            def select_nearest_aida_output(self, outputs, requested, tolerance):
                return SereneClient.select_nearest_aida_output(outputs, requested, tolerance)

            def download_aida_output(self, _output):
                self.download_count += 1
                return True, "download ok", self.payload

            def fetch_kp_ap_indices(self, **_kwargs):
                return False, "indices unavailable", pd.DataFrame()

        return FakeClient(self._aida_payload())

    def test_grid_density_does_not_change_aida_download_count(self):
        import data_loader

        global_region = {"lat_min": -90, "lat_max": 90, "lon_min": -180, "lon_max": 180}
        coarse_client = self._fake_aida_client()
        with patch.object(data_loader, "SereneClient", return_value=coarse_client):
            _coarse, coarse_status = data_loader.load_data(
                start_time="2026-06-21T20:00:00Z",
                end_time="2026-06-21T21:00:00Z",
                variables=["TEC"],
                region=global_region,
                grid_step=30.0,
            )

        dense_client = self._fake_aida_client()
        with patch.object(data_loader, "SereneClient", return_value=dense_client):
            _dense, dense_status = data_loader.load_data(
                start_time="2026-06-21T20:00:00Z",
                end_time="2026-06-21T21:00:00Z",
                variables=["TEC"],
                region=global_region,
                grid_step=2.0,
            )

        self.assertEqual(coarse_client.download_count, 2)
        self.assertEqual(dense_client.download_count, 2)
        self.assertEqual(coarse_status.metadata["aida_dataset_downloads"], 2)
        self.assertEqual(dense_status.metadata["aida_dataset_downloads"], 2)
        self.assertEqual(coarse_status.metadata["local_map_points"], 91)
        self.assertEqual(dense_status.metadata["local_map_points"], 16471)

    def test_shared_start_end_output_is_downloaded_once(self):
        import data_loader

        client = self._fake_aida_client(same_output=True)
        with patch.object(data_loader, "SereneClient", return_value=client):
            _frame, status = data_loader.load_data(
                start_time="2026-06-21T20:00:00Z",
                end_time="2026-06-21T20:05:00Z",
                variables=["TEC"],
                region={"lat_min": 0, "lat_max": 10, "lon_min": 0, "lon_max": 10},
                grid_step=5.0,
            )

        self.assertEqual(client.download_count, 1)
        self.assertEqual(status.metadata["aida_dataset_downloads"], 1)


if __name__ == "__main__":
    unittest.main()
