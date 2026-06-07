import os
import sys
import unittest
from unittest.mock import patch

import pandas as pd


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class ApiOnlyDataLoaderTest(unittest.TestCase):
    def test_api_failure_does_not_fall_back_to_local_file(self):
        import data_loader

        class FailingClient:
            def fetch_model_output(self, **_kwargs):
                return False, "calc failed", None

            def fetch_kp_ap_indices(self, **_kwargs):
                return False, "indices failed", pd.DataFrame()

        with patch.object(data_loader, "SereneClient", return_value=FailingClient()):
            df, status = data_loader.load_data(source="api")

        self.assertTrue(df.empty)
        self.assertEqual(status.source, "none")
        self.assertFalse(status.ok)
        self.assertNotIn("fallback", status.message.lower())


if __name__ == "__main__":
    unittest.main()
