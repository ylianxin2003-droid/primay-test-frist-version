import os
import sys
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path

import pandas as pd


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class TrialCacheTest(unittest.TestCase):
    def test_cache_key_is_stable_and_files_round_trip(self):
        import trial_cache
        from data_loader import IcaoProductBundle, LoadStatus

        region = {"lat_min": -90.0, "lat_max": 90.0, "lon_min": -180.0, "lon_max": 180.0}
        key = trial_cache.make_trial_cache_key(
            "2025-01-01T17:55:00",
            region,
            15.0,
            "Full ICAO-style mode",
        )

        self.assertIn("20250101T175500", key)
        self.assertEqual(
            key,
            trial_cache.make_trial_cache_key(
                "2025-01-01T17:55:00Z",
                dict(reversed(region.items())),
                15,
                "Full ICAO-style mode",
            ),
        )

        products = pd.DataFrame([{
            "time": pd.Timestamp("2025-01-01T17:55:00Z"),
            "lat": -90.0,
            "lon": -180.0,
            "variable": "TEC",
            "value": 12.0,
        }])
        indices = pd.DataFrame([{
            "time": pd.Timestamp("2025-01-01T17:55:00Z"),
            "variable": "Kp",
            "value": 8.0,
        }])
        summary = pd.DataFrame([{
            "Domain": "GNSS",
            "Indicator": "Vertical TEC",
            "Status": "OK",
        }])
        data = pd.DataFrame([{
            "time": pd.Timestamp("2025-01-01T17:55:00Z"),
            "variable": "TEC",
            "value": 12.0,
        }])
        bundle = IcaoProductBundle(
            products=products,
            indices=indices,
            status=LoadStatus(
                source="api",
                ok=True,
                message="Loaded from API",
                warnings=["sample warning"],
                metadata={
                    "analysis_time": "2025-01-01T17:55:00+00:00",
                    "loaded_region": region,
                    "token_like_value": "not-a-secret",
                },
            ),
            kp_storm_eligible=True,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = trial_cache.save_trial_bundle(
                key,
                bundle,
                summary,
                data,
                base_dir=Path(tmpdir),
            )
            loaded_bundle, loaded_summary, loaded_data = trial_cache.load_trial_bundle(
                key,
                base_dir=Path(tmpdir),
            )

            self.assertTrue((cache_path / "status.json").exists())
            self.assertEqual(loaded_bundle.status.source, "trial_cache")
            self.assertTrue(loaded_bundle.status.ok)
            self.assertEqual(loaded_bundle.kp_storm_eligible, True)
            self.assertEqual(set(loaded_bundle.products["variable"]), {"TEC"})
            self.assertEqual(loaded_summary.iloc[0]["Indicator"], "Vertical TEC")
            self.assertEqual(loaded_data.iloc[0]["variable"], "TEC")

            for file_path in cache_path.rglob("*"):
                if file_path.is_file():
                    content = file_path.read_bytes()
                    self.assertNotIn(b"SERENE_API_TOKEN", content)
                    self.assertNotIn(b"your-new-api-token", content)

    def test_missing_cache_raises_file_not_found(self):
        import trial_cache

        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(FileNotFoundError):
                trial_cache.load_trial_bundle("missing-key", base_dir=Path(tmpdir))

    def test_cache_zip_contains_commit_ready_folder_without_secrets(self):
        import trial_cache
        from data_loader import IcaoProductBundle, LoadStatus

        cache_key = "20250101T175500-Quick-Demo-test"
        bundle = IcaoProductBundle(
            products=pd.DataFrame([{
                "time": pd.Timestamp("2025-01-01T17:55:00Z"),
                "variable": "TEC",
                "value": 12.0,
            }]),
            indices=pd.DataFrame([{
                "time": pd.Timestamp("2025-01-01T17:55:00Z"),
                "variable": "Kp",
                "value": 8.0,
            }]),
            status=LoadStatus(
                source="api",
                ok=True,
                message="Loaded from API",
                metadata={
                    "analysis_time": "2025-01-01T17:55:00+00:00",
                    "SERENE_API_TOKEN": "must-not-be-written",
                },
            ),
        )

        archive_bytes = trial_cache.build_trial_bundle_zip(
            cache_key,
            bundle,
            pd.DataFrame([{"Indicator": "Vertical TEC", "Status": "OK"}]),
            bundle.products,
        )

        with zipfile.ZipFile(BytesIO(archive_bytes), "r") as archive:
            names = set(archive.namelist())
            self.assertIn(f"{cache_key}/status.json", names)
            self.assertTrue(any(name.startswith(f"{cache_key}/products.") for name in names))
            for name in names:
                content = archive.read(name)
                self.assertNotIn(b"SERENE_API_TOKEN", content)
                self.assertNotIn(b"must-not-be-written", content)

    def test_generation_utility_uses_global_trial_windows(self):
        import generate_trial_outputs

        times = generate_trial_outputs._analysis_times()

        self.assertIn("2024-10-11T02:55:00", times)
        self.assertIn("2026-01-19T23:55:00", times)
        self.assertEqual(generate_trial_outputs.GLOBAL_REGION, {
            "lat_min": -90.0,
            "lat_max": 90.0,
            "lon_min": -180.0,
            "lon_max": 180.0,
        })


if __name__ == "__main__":
    unittest.main()
