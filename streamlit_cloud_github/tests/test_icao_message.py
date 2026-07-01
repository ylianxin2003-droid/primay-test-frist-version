import os
import sys
import unittest


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class IcaoMessageTest(unittest.TestCase):
    def _message(self, **overrides):
        from icao_message import generate_icao_message

        arguments = {
            "effect": "GNSS",
            "observed_time": "2026-06-24T12:00:00Z",
            "observed_category": "MODERATE",
            "region": {
                "lat_min": 45,
                "lat_max": 60,
                "lon_min": -15,
                "lon_max": 15,
            },
            "forecasts": {90: "MODERATE", 180: "MODERATE", 360: "OK"},
            "generated_time": "2026-06-24T12:05:00Z",
            "advisory_number": "2026/001",
        }
        arguments.update(overrides)
        return generate_icao_message(**arguments)

    def test_moderate_gnss_message_contains_required_research_fields(self):
        message = self._message()

        self.assertEqual(
            message.splitlines(),
            [
                "SWX ADVISORY",
                "STATUS: TEST",
                "DTG: 20260624/1205Z",
                "SWXC: UOB RESEARCH PROTOTYPE",
                "SWX EFFECT: GNSS",
                "ADVISORY NR: 2026/001",
                "OBS SWX: 24/1200Z MOD USER-SELECTED BOUNDING BOX "
                "LAT 45.00 TO 60.00, LON -15.00 TO 15.00",
                "FCST SWX +90 MIN: 24/1330Z MOD USER-SELECTED BOUNDING BOX "
                "LAT 45.00 TO 60.00, LON -15.00 TO 15.00",
                "FCST SWX +3 HR: 24/1500Z MOD USER-SELECTED BOUNDING BOX "
                "LAT 45.00 TO 60.00, LON -15.00 TO 15.00",
                "FCST SWX +6 HR: 24/1800Z NO SWX EXP USER-SELECTED "
                "BOUNDING BOX LAT 45.00 TO 60.00, LON -15.00 TO 15.00",
                "RMK: GENERATED ONLY FROM SERENE AIDA/KP DATA.",
                "NXT ADVISORY: NO FURTHER ADVISORIES",
                "RESEARCH PROTOTYPE - NOT FOR OPERATIONAL USE",
            ],
        )

    def test_severe_hf_message_uses_sev_category(self):
        message = self._message(
            effect="HF COM",
            observed_category="SEVERE",
            forecasts={90: "MODERATE", 180: "SEVERE", 360: "MODERATE"},
        )

        self.assertIn("SWX EFFECT: HF COM", message)
        self.assertIn("OBS SWX: 24/1200Z SEV ", message)
        self.assertIn("FCST SWX +3 HR: 24/1500Z SEV ", message)

    def test_ok_message_reports_no_space_weather_expected(self):
        message = self._message(
            observed_category="OK",
            forecasts={90: "OK", 180: "OK", 360: "OK"},
        )

        self.assertIn("OBS SWX: 24/1200Z NO SWX EXP ", message)
        self.assertEqual(message.count("NO SWX EXP"), 4)

    def test_missing_forecasts_are_not_reported_as_ok(self):
        message = self._message(forecasts={180: None})

        self.assertIn("FCST SWX +3 HR: NOT AVAILABLE", message)
        self.assertIn("FCST SWX +6 HR: NOT AVAILABLE", message)
        self.assertIn("FCST SWX +90 MIN: NOT AVAILABLE", message)
        self.assertNotIn("FCST SWX +3 HR: 24/1500Z NO SWX EXP", message)

    def test_rejects_unsupported_effect(self):
        with self.assertRaisesRegex(ValueError, "Unsupported SWX effect"):
            self._message(effect="SATCOM")

    def test_rejects_unsupported_observed_or_forecast_category(self):
        with self.assertRaisesRegex(ValueError, "Unsupported category"):
            self._message(observed_category="LOW")
        with self.assertRaisesRegex(ValueError, "Unsupported category"):
            self._message(forecasts={180: "WARNING", 360: "OK"})

    def test_same_inputs_produce_identical_output(self):
        first = self._message()
        second = self._message()

        self.assertEqual(first, second)

    def test_requires_keyword_arguments(self):
        from icao_message import generate_icao_message

        with self.assertRaises(TypeError):
            generate_icao_message(
                "GNSS",
                "2026-06-24T12:00:00Z",
                "MODERATE",
                {
                    "lat_min": 45,
                    "lat_max": 60,
                    "lon_min": -15,
                    "lon_max": 15,
                },
                {180: "MODERATE", 360: "OK"},
                "2026-06-24T12:05:00Z",
                "2026/001",
            )


if __name__ == "__main__":
    unittest.main()
