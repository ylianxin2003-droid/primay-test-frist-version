import os
import sys
import unittest
from io import BytesIO

import h5py
import numpy as np


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _make_hdf5(include_latitudes: bool = True) -> bytes:
    buffer = BytesIO()
    latitudes = np.array([-1.0, 0.0, 1.0])
    longitudes = np.array([-2.0, -1.0, 0.0, 1.0])
    values = longitudes[:, None] * 100.0 + latitudes[None, :]
    with h5py.File(buffer, "w") as handle:
        if include_latitudes:
            handle.create_dataset("Latitudes", data=latitudes)
        handle.create_dataset("Longitudes", data=longitudes)
        for variable in ("TEC", "foF2", "MUF3000F2", "NmF2", "hmF2"):
            handle.create_dataset(variable, data=values)
    return buffer.getvalue()


class AidaGridTest(unittest.TestCase):
    def setUp(self):
        self.payload = _make_hdf5()

    def test_global_axis_keeps_exact_requested_spacing(self):
        from aida_grid import target_axis

        latitudes = target_axis(-90, 90, 30)
        longitudes = target_axis(-180, 180, 30)

        self.assertEqual(latitudes.tolist(), [-90, -60, -30, 0, 30, 60, 90])
        self.assertEqual(len(longitudes), 13)
        self.assertTrue(np.allclose(np.diff(longitudes), 30.0))

    def test_exact_grid_request_preserves_coordinates_and_values(self):
        from aida_grid import sample_aida_hdf5

        frame = sample_aida_hdf5(
            self.payload,
            region={"lat_min": -1, "lat_max": 1, "lon_min": -2, "lon_max": 1},
            step=1.0,
            variables=["TEC"],
            timestamp="2026-06-21T21:40:00Z",
        )

        self.assertEqual(sorted(frame["lat"].unique()), [-1.0, 0.0, 1.0])
        self.assertEqual(sorted(frame["lon"].unique()), [-2.0, -1.0, 0.0, 1.0])
        selected = frame[(frame["lat"] == 1.0) & (frame["lon"] == -2.0)]
        self.assertAlmostEqual(float(selected.iloc[0]["value"]), -199.0)

    def test_bilinear_interpolation_preserves_lon_lat_orientation(self):
        from aida_grid import sample_aida_hdf5

        frame = sample_aida_hdf5(
            self.payload,
            region={"lat_min": -0.5, "lat_max": -0.5, "lon_min": -1.5, "lon_max": -1.5},
            step=0.5,
            variables=["TEC"],
            timestamp="2026-06-21T21:40:00Z",
        )

        self.assertAlmostEqual(float(frame.iloc[0]["value"]), -150.5)

    def test_missing_required_dataset_is_rejected(self):
        from aida_grid import AidaGridError, sample_aida_hdf5

        with self.assertRaisesRegex(AidaGridError, "Latitudes"):
            sample_aida_hdf5(
                _make_hdf5(include_latitudes=False),
                region={"lat_min": -1, "lat_max": 1, "lon_min": -2, "lon_max": 1},
                step=1.0,
                variables=["TEC"],
                timestamp="2026-06-21T21:40:00Z",
            )


if __name__ == "__main__":
    unittest.main()
