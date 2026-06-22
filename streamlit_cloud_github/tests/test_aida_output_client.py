import os
import sys
import unittest
from unittest.mock import Mock

import pandas as pd


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


CATALOG_HTML = """
<html><body><table>
<tr><th>ID</th><th>Assimilation UTC</th><th>Parameter File</th></tr>
<tr><td>808555</td><td>2026-06-21 21:40</td><td>
<a href="/output/aida/ultra/assimilation/808555/param_2d/download/">2D</a>
</td></tr>
<tr><td>808559</td><td>2026-06-21 21:45</td><td>
<a href="/output/aida/ultra/assimilation/808559/param_2d/download/">2D</a>
</td></tr>
</table></body></html>
"""


def _response(*, text: str = "", content: bytes | None = None, url: str = "https://api.test/output/"):
    body = text.encode() if content is None else content
    return Mock(
        ok=True,
        status_code=200,
        url=url,
        text=text,
        content=body,
    )


class AidaOutputClientTest(unittest.TestCase):
    def setUp(self):
        from serene_client import SereneClient

        SereneClient._aida_download_cache = {}
        self.client = SereneClient(base_url="https://api.test", token="secret")

    def test_catalog_html_is_parsed_into_typed_outputs(self):
        self.client._session.request = Mock(return_value=_response(text=CATALOG_HTML))

        ok, message, outputs = self.client.fetch_aida_catalog("ultra", "assimilation")

        self.assertTrue(ok, message)
        self.assertEqual([item.output_id for item in outputs], ["808555", "808559"])
        self.assertEqual(outputs[0].cadence, "ultra")
        self.assertEqual(outputs[0].timestamp, pd.Timestamp("2026-06-21T21:40:00Z"))
        headers = self.client._session.request.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Token secret")

    def test_login_redirect_is_reported_as_token_authentication_failure(self):
        login = _response(
            text='<form id="login-form"></form>',
            url="https://api.test/accounts/login/?next=/output/aida/latest/",
        )
        self.client._session.request = Mock(return_value=login)

        ok, message, outputs = self.client.fetch_aida_catalog("ultra", "assimilation")

        self.assertFalse(ok)
        self.assertEqual(outputs, [])
        self.assertIn("Token authentication", message)

    def test_nearest_output_respects_tolerance(self):
        from serene_client import AidaOutput

        outputs = [
            AidaOutput(
                output_id="1",
                timestamp=pd.Timestamp("2026-06-21T21:40:00Z"),
                cadence="ultra",
                kind="assimilation",
                download_path="/one",
            )
        ]

        close = self.client.select_nearest_aida_output(
            outputs, "2026-06-21T21:50:00Z", pd.Timedelta(minutes=15)
        )
        far = self.client.select_nearest_aida_output(
            outputs, "2026-06-21T22:00:00Z", pd.Timedelta(minutes=15)
        )

        self.assertEqual(close.output_id, "1")
        self.assertIsNone(far)

    def test_binary_output_is_downloaded_once_and_reused(self):
        from serene_client import AidaOutput

        response = _response(content=b"\x89HDF\r\n\x1a\ncontent")
        self.client._session.request = Mock(return_value=response)
        output = AidaOutput(
            output_id="808555",
            timestamp=pd.Timestamp("2026-06-21T21:40:00Z"),
            cadence="ultra",
            kind="assimilation",
            download_path="/output/aida/ultra/assimilation/808555/param_2d/download/",
        )

        first = self.client.download_aida_output(output)
        second = self.client.download_aida_output(output)

        self.assertTrue(first[0])
        self.assertEqual(first[2], response.content)
        self.assertEqual(second[2], response.content)
        self.assertEqual(self.client._session.request.call_count, 1)


if __name__ == "__main__":
    unittest.main()
