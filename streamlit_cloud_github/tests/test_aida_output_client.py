import os
import sys
import unittest
from unittest.mock import Mock


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


HDF5_RESPONSE = b"\x89HDF\r\n\x1a\nraw-state"


def _response(
    *,
    content: bytes = HDF5_RESPONSE,
    content_type: str = "application/x-hdf5",
    status_code: int = 200,
):
    return Mock(
        ok=200 <= status_code < 300,
        status_code=status_code,
        content=content,
        headers={"Content-Type": content_type},
    )


class AidaRawOutputClientTest(unittest.TestCase):
    def setUp(self):
        from serene_client import SereneClient

        SereneClient._aida_raw_cache = {}
        self.client = SereneClient(
            base_url="https://spaceweather.bham.ac.uk",
            token="test-token",
        )

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


if __name__ == "__main__":
    unittest.main()
