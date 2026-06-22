import os
import sys
import unittest


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class AidaGridTest(unittest.TestCase):
    def test_global_axis_keeps_exact_requested_spacing(self):
        from aida_grid import target_axis

        latitudes = target_axis(-90, 90, 2)
        longitudes = target_axis(-180, 180, 2)

        self.assertEqual(len(latitudes), 91)
        self.assertEqual(len(longitudes), 181)
        self.assertTrue((latitudes[1:] - latitudes[:-1] == 2).all())
        self.assertTrue((longitudes[1:] - longitudes[:-1] == 2).all())

    def test_point_estimate_matches_requested_grid(self):
        from aida_grid import estimate_target_points

        points = estimate_target_points(
            {"lat_min": -90, "lat_max": 90, "lon_min": -180, "lon_max": 180},
            30,
        )

        self.assertEqual(points, 91)

    def test_variable_aliases_match_dashboard_names(self):
        from aida_grid import normalise_aida_variables

        selected = normalise_aida_variables(["vTEC", "MUF3000", "TEC"])

        self.assertEqual(selected, ["TEC", "MUF3000F2"])

    def test_unknown_variable_is_rejected(self):
        from aida_grid import AidaGridError, normalise_aida_variables

        with self.assertRaisesRegex(AidaGridError, "Unsupported"):
            normalise_aida_variables(["not-a-field"])


if __name__ == "__main__":
    unittest.main()
