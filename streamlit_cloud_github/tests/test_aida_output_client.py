import os
import sys
import unittest
from unittest.mock import Mock, patch


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


HDF5_RESPONSE = b"\x89HDF\r\n\x1a\nraw-state"


def _response(
    *,
    content: bytes = HDF5_RESPONSE,
    content_type: str = "application/x-hdf5",
    status_code: int = 200,
    text: str = "",
):
    return Mock(
        ok=200 <= status_code < 300,
        status_code=status_code,
        content=content,
        headers={"Content-Type": content_type},
        text=text,
    )


class AidaRawOutputClientTest(unittest.TestCase):
    def setUp(self):
        from serene_client import SereneClient

        SereneClient._aida_raw_cache = {}
        self.client = SereneClient(
            base_url="https://spaceweather.bham.ac.uk",
            token="test-token",
        )

    def test_raw_cache_default_max_entries_is_exported(self):
        from serene_client import AIDA_RAW_CACHE_MAX_ENTRIES

        self.assertEqual(AIDA_RAW_CACHE_MAX_ENTRIES, 16)

    def test_historical_raw_request_matches_upstream_contract(self):
        response = _response()
        self.client._session.request = Mock(return_value=response)

        ok, message, payload = self.client.download_aida_raw_output(
            requested_time="2025-01-01T13:55:00Z",
            latency="rapid",
        )

        self.assertTrue(ok, message)
        self.assertEqual(payload, response.content)
        kwargs = self.client._session.request.call_args.kwargs
        self.assertEqual(kwargs["method"], "GET")
        self.assertEqual(
            kwargs["url"],
            "https://spaceweather.bham.ac.uk/api/download-output/",
        )
        self.assertEqual(kwargs["headers"]["Authorization"], "Token test-token")
        self.assertEqual(kwargs["data"], {
            "file_time": "2025-01-01T13:55:00",
            "product": "rapid",
            "file_type": "raw",
        })

    def test_request_time_is_rounded_to_nearest_five_minutes_like_upstream(self):
        self.client._session.request = Mock(return_value=_response())

        ok, message, _payload = self.client.download_aida_raw_output(
            requested_time="2025-04-11T12:00:01Z",
            latency="ultra",
        )

        self.assertTrue(ok, message)
        self.assertEqual(
            self.client._session.request.call_args.kwargs["data"]["file_time"],
            "2025-04-11T12:00:00",
        )

    def test_latest_raw_request_is_cached(self):
        response = _response()
        self.client._session.request = Mock(return_value=response)

        first = self.client.download_aida_raw_output(None, "ultra")
        second = self.client.download_aida_raw_output(None, "ultra")

        self.assertTrue(first[0], first[1])
        self.assertEqual(second[2], response.content)
        self.assertEqual(self.client._session.request.call_count, 1)
        self.assertEqual(
            self.client._session.request.call_args.kwargs["data"],
            {"latest": True, "product": "ultra", "file_type": "raw"},
        )

    def test_html_response_is_rejected_without_exposing_token(self):
        self.client._session.request = Mock(return_value=_response(
            content=b"<html><form id='login-form'></form></html>",
            content_type="text/html",
        ))

        ok, message, payload = self.client.download_aida_raw_output(None, "ultra")

        self.assertFalse(ok)
        self.assertIsNone(payload)
        self.assertNotIn("test-token", message)
        self.assertIn("non-HDF5", message)

    def test_rejected_token_is_reported_without_echoing_it(self):
        self.client._session.request = Mock(return_value=_response(status_code=401))

        ok, message, payload = self.client.download_aida_raw_output(None, "ultra")

        self.assertFalse(ok)
        self.assertIsNone(payload)
        self.assertIn("rejected", message)
        self.assertNotIn("test-token", message)

    def test_bad_request_includes_safe_server_detail(self):
        self.client._session.request = Mock(return_value=_response(
            status_code=400,
            content=b'{"detail":"No matching AIDA output"}',
            content_type="application/json",
            text='{"detail":"No matching AIDA output"}',
        ))

        ok, message, payload = self.client.download_aida_raw_output(
            "2024-03-24T15:00:00Z",
            "final",
        )

        self.assertFalse(ok)
        self.assertIsNone(payload)
        self.assertIn("No matching AIDA output", message)
        self.assertNotIn("test-token", message)

    def test_analysis_request_exception_does_not_expose_token(self):
        from requests.exceptions import RequestException

        self.client._session.request = Mock(
            side_effect=RequestException("request carried test-token")
        )

        ok, message, payload = self.client.download_aida_raw_output(None, "ultra")

        self.assertFalse(ok)
        self.assertIsNone(payload)
        self.assertIn("[redacted]", message)
        self.assertNotIn("test-token", message)

    def test_server_detail_redacts_token_before_truncating(self):
        self.client.token = "credential-value"
        server_detail = ("x" * 235) + self.client.token + " trailing detail"
        self.client._session.request = Mock(return_value=_response(
            status_code=400,
            content=server_detail.encode(),
            content_type="text/plain",
            text=server_detail,
        ))

        ok, message, payload = self.client.download_aida_raw_output(None, "ultra")

        self.assertFalse(ok)
        self.assertIsNone(payload)
        self.assertNotIn("crede", message)
        self.assertNotIn(self.client.token, message)

    def test_forecast_request_matches_model_from_api_contract(self):
        response = _response()
        self.client._session.request = Mock(return_value=response)

        ok, message, payload = self.client.download_aida_forecast(
            requested_time="2025-01-01T13:55:00Z",
            latency="rapid",
            period_minutes=90,
        )

        self.assertTrue(ok, message)
        self.assertEqual(payload, response.content)
        kwargs = self.client._session.request.call_args.kwargs
        self.assertEqual(kwargs["method"], "GET")
        self.assertEqual(
            kwargs["url"],
            "https://spaceweather.bham.ac.uk/api/download-forecast/",
        )
        self.assertEqual(kwargs["headers"]["Authorization"], "Token test-token")
        self.assertEqual(kwargs["data"], {
            "file_time": "2025-01-01T13:55:00",
            "product": "rapid",
            "file_type": "raw",
            "period": 90,
        })

    def test_forecast_rejects_latest_without_making_request(self):
        self.client._session.request = Mock(return_value=_response())

        ok, message, payload = self.client.download_aida_forecast(
            requested_time=None,
            latency="ultra",
            period_minutes=30,
        )

        self.assertFalse(ok)
        self.assertIsNone(payload)
        self.assertIn("time", message.lower())
        self.client._session.request.assert_not_called()

    def test_forecast_rejects_unsupported_period_without_making_request(self):
        self.client._session.request = Mock(return_value=_response())

        ok, message, payload = self.client.download_aida_forecast(
            requested_time="2025-01-01T13:55:00Z",
            latency="final",
            period_minutes=60,
        )

        self.assertFalse(ok)
        self.assertIsNone(payload)
        self.assertIn("period", message.lower())
        self.client._session.request.assert_not_called()

    def test_cache_key_separates_analysis_forecast_and_forecast_period(self):
        analysis = _response(content=HDF5_RESPONSE + b"-analysis")
        forecast_30 = _response(content=HDF5_RESPONSE + b"-forecast-30")
        forecast_90 = _response(content=HDF5_RESPONSE + b"-forecast-90")
        self.client._session.request = Mock(
            side_effect=[analysis, forecast_30, forecast_90],
        )
        requested_time = "2025-01-01T13:55:00Z"

        first_analysis = self.client.download_aida_raw_output(requested_time, "rapid")
        first_30 = self.client.download_aida_forecast(requested_time, "rapid", 30)
        first_90 = self.client.download_aida_forecast(requested_time, "rapid", 90)
        second_analysis = self.client.download_aida_raw_output(requested_time, "rapid")
        second_30 = self.client.download_aida_forecast(requested_time, "rapid", 30)
        second_90 = self.client.download_aida_forecast(requested_time, "rapid", 90)

        self.assertEqual(first_analysis[2], analysis.content)
        self.assertEqual(first_30[2], forecast_30.content)
        self.assertEqual(first_90[2], forecast_90.content)
        self.assertEqual(second_analysis[2], analysis.content)
        self.assertEqual(second_30[2], forecast_30.content)
        self.assertEqual(second_90[2], forecast_90.content)
        self.assertEqual(self.client._session.request.call_count, 3)

    def test_cache_key_separates_normalised_api_base_urls(self):
        from serene_client import SereneClient

        first_response = _response(content=HDF5_RESPONSE + b"-first-api")
        second_response = _response(content=HDF5_RESPONSE + b"-second-api")
        self.client._session.request = Mock(return_value=first_response)
        second_client = SereneClient(
            base_url="https://secondary.example.test/",
            token="test-token",
        )
        second_client._session.request = Mock(return_value=second_response)

        first = self.client.download_aida_raw_output(None, "ultra")
        second = second_client.download_aida_raw_output(None, "ultra")

        self.assertEqual(first[2], first_response.content)
        self.assertEqual(second[2], second_response.content)
        self.client._session.request.assert_called_once()
        second_client._session.request.assert_called_once()

    def test_raw_cache_is_lru_bounded_by_environment_setting(self):
        responses = [
            _response(content=HDF5_RESPONSE + marker)
            for marker in (b"-one", b"-two", b"-three", b"-two-again")
        ]
        self.client._session.request = Mock(side_effect=responses)

        with patch.dict(os.environ, {"SERENE_AIDA_RAW_CACHE_MAX_ENTRIES": "2"}):
            one = self.client.download_aida_raw_output("2025-01-01T00:00:00Z", "ultra")
            two = self.client.download_aida_raw_output("2025-01-01T00:05:00Z", "ultra")
            one_cached = self.client.download_aida_raw_output(
                "2025-01-01T00:00:00Z", "ultra"
            )
            three = self.client.download_aida_raw_output("2025-01-01T00:10:00Z", "ultra")
            one_still_cached = self.client.download_aida_raw_output(
                "2025-01-01T00:00:00Z", "ultra"
            )
            two_refetched = self.client.download_aida_raw_output(
                "2025-01-01T00:05:00Z", "ultra"
            )

        self.assertEqual(one[2], responses[0].content)
        self.assertEqual(two[2], responses[1].content)
        self.assertEqual(one_cached[2], responses[0].content)
        self.assertEqual(three[2], responses[2].content)
        self.assertEqual(one_still_cached[2], responses[0].content)
        self.assertEqual(two_refetched[2], responses[3].content)
        self.assertEqual(self.client._session.request.call_count, 4)
        self.assertEqual(len(type(self.client)._aida_raw_cache), 2)

    def test_raw_cache_lookup_is_disabled_when_environment_limit_is_zero(self):
        first_response = _response(content=HDF5_RESPONSE + b"-first")
        second_response = _response(content=HDF5_RESPONSE + b"-second")
        self.client._session.request = Mock(
            side_effect=[first_response, second_response],
        )

        with patch.dict(os.environ, {"SERENE_AIDA_RAW_CACHE_MAX_ENTRIES": "2"}):
            first = self.client.download_aida_raw_output(None, "ultra")
        with patch.dict(os.environ, {"SERENE_AIDA_RAW_CACHE_MAX_ENTRIES": "0"}):
            second = self.client.download_aida_raw_output(None, "ultra")

        self.assertEqual(first[2], first_response.content)
        self.assertEqual(second[2], second_response.content)
        self.assertEqual(self.client._session.request.call_count, 2)
        self.assertEqual(type(self.client)._aida_raw_cache, {})


if __name__ == "__main__":
    unittest.main()
