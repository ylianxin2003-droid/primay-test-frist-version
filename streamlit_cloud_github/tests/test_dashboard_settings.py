import os
import sys
import unittest
from datetime import date, time


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class DashboardSettingsTest(unittest.TestCase):
    def test_default_api_call_limit_is_50(self):
        import serene_client

        self.assertEqual(serene_client.MAX_GRID_POINTS, 50)

    def test_combine_date_time_to_iso8601(self):
        from app_utils import combine_date_time_iso

        value = combine_date_time_iso(date(2026, 6, 7), time(12, 0, 43))

        self.assertEqual(value, "2026-06-07T12:00:43")


if __name__ == "__main__":
    unittest.main()
