import os
import sys
import unittest
from unittest.mock import Mock, patch

import pandas as pd


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class SereneIndicesTest(unittest.TestCase):
    def setUp(self):
        from serene_client import SereneClient

        SereneClient._kp_ap_csv_cache = None

    def test_parse_kp_ap_csv_filters_selected_time_range(self):
        from serene_client import SereneClient

        csv_text = (
            "time,Kp,ap,rAp\n"
            "2024-05-10T21:00:00Z,8.7,300,250\n"
            "2024-05-11T00:00:00Z,9.0,400,300\n"
            "2024-06-01T00:00:00Z,2.0,7,8\n"
        )

        df = SereneClient.parse_kp_ap_csv(
            csv_text,
            start_time="2024-05-11T00:00:00",
            end_time="2024-05-11T03:00:00",
        )

        self.assertEqual(set(df["variable"]), {"Kp", "ap"})
        self.assertEqual(len(df), 2)
        self.assertEqual(df["source"].iloc[0], "SERENE API Kp/ap")

    def test_kp_ap_rows_generate_geomagnetic_storm_risk(self):
        from alert_engine import generate_alerts, generate_overall_risk

        df = pd.DataFrame([
            {
                "time": "2024-05-11T00:00:00Z",
                "lat": None,
                "lon": None,
                "variable": "Kp",
                "value": 9.0,
                "model": "SERENE Indices",
            },
            {
                "time": "2024-05-11T00:00:00Z",
                "lat": None,
                "lon": None,
                "variable": "ap",
                "value": 400,
                "model": "SERENE Indices",
            },
        ])

        alerts = generate_alerts(df)
        overall, _summary = generate_overall_risk(alerts)

        self.assertEqual(overall, "G5 Extreme")
        self.assertIn("Geomagnetic storm risk", set(alerts["alert_type"]))
        self.assertIn("G5 Extreme", set(alerts["risk_level"]))

    def test_public_kp_ap_download_does_not_send_api_token(self):
        from serene_client import SereneClient

        response = Mock(
            ok=True,
            text="time,Kp,ap,rAp\n2024-05-11T00:00:00Z,9.0,400,300\n",
        )
        client = SereneClient(base_url="https://api.example", token="private-token")
        client._session.request = Mock(return_value=response)

        ok, _message, frame = client.fetch_kp_ap_indices()

        self.assertTrue(ok)
        self.assertFalse(frame.empty)
        headers = client._session.request.call_args.kwargs["headers"]
        self.assertNotIn("Authorization", headers)

    def test_public_kp_ap_download_is_reused_across_client_instances(self):
        from serene_client import SereneClient

        response = Mock(
            ok=True,
            text="time,Kp,ap,rAp\n2024-05-11T00:00:00Z,9.0,400,300\n",
        )
        with patch("serene_client.requests.Session.request", return_value=response) as request:
            first = SereneClient(base_url="https://api.example", token="one")
            second = SereneClient(base_url="https://api.example", token="two")

            first.fetch_kp_ap_indices()
            second.fetch_kp_ap_indices()

        self.assertEqual(request.call_count, 1)


if __name__ == "__main__":
    unittest.main()
