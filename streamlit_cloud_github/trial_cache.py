"""Local cached trial-output storage for demo and validation periods."""

from __future__ import annotations

import hashlib
import io
import json
import re
import tempfile
import zipfile
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from data_loader import IcaoProductBundle, LoadStatus


TRIAL_OUTPUT_DIR = Path(__file__).resolve().parent / "data" / "trial_outputs"
_SENSITIVE_KEY_PARTS = ("token", "secret", "password", "auth", "credential", "key")


def make_trial_cache_key(
    analysis_time: str,
    region: dict[str, float],
    grid_step: float,
    mode: str,
) -> str:
    """Create a stable filesystem-safe key for processed trial output."""
    parsed = pd.to_datetime(analysis_time, errors="coerce", utc=True)
    time_part = (
        parsed.strftime("%Y%m%dT%H%M%S")
        if pd.notna(parsed) else
        _slug(str(analysis_time))[:20]
    )
    normalised_region = {
        name: float(region[name])
        for name in ("lat_min", "lat_max", "lon_min", "lon_max")
    }
    payload = {
        "analysis_time": parsed.isoformat() if pd.notna(parsed) else str(analysis_time),
        "region": normalised_region,
        "grid_step": float(grid_step),
        "mode": str(mode),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:12]
    return f"{time_part}-{_slug(mode)}-{digest}"


def trial_cache_path(cache_key: str, base_dir: Path | None = None) -> Path:
    """Return the directory where a cache key is stored."""
    safe_key = _slug(cache_key)
    if not safe_key:
        raise ValueError("Trial cache key must not be empty.")
    return (base_dir or TRIAL_OUTPUT_DIR) / safe_key


def load_trial_bundle(
    cache_key: str,
    base_dir: Path | None = None,
) -> tuple[IcaoProductBundle, pd.DataFrame, pd.DataFrame]:
    """Load processed trial output from disk."""
    root = trial_cache_path(cache_key, base_dir)
    status_path = root / "status.json"
    if not status_path.exists():
        raise FileNotFoundError(f"Cached trial output not found: {root}")
    with status_path.open("r", encoding="utf-8") as handle:
        stored = json.load(handle)
    files = stored.get("files", {})
    products = _read_frame(root, files.get("products", "products.csv"))
    indices = _read_frame(root, files.get("indices", "indices.csv"))
    summary = _read_frame(root, files.get("summary", "summary.csv"))
    data = _read_frame(root, files.get("data", "data.csv"))

    status_data = stored.get("status", {})
    original_source = status_data.get("source", "api")
    metadata = status_data.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    metadata = dict(metadata)
    metadata.update({
        "cache_key": cache_key,
        "cached_trial_output": True,
        "original_source": original_source,
    })
    status = LoadStatus(
        source="trial_cache",
        ok=bool(status_data.get("ok", False)),
        message="Loaded cached trial output.",
        warnings=list(status_data.get("warnings", [])),
        metadata=metadata,
    )
    bundle = IcaoProductBundle(
        products=products,
        indices=indices,
        status=status,
        kp_storm_eligible=stored.get("kp_storm_eligible"),
    )
    return bundle, summary, data


def save_trial_bundle(
    cache_key: str,
    bundle: IcaoProductBundle,
    summary: pd.DataFrame,
    data: pd.DataFrame,
    base_dir: Path | None = None,
) -> Path:
    """Save processed dashboard output without credentials or raw API tokens."""
    root = trial_cache_path(cache_key, base_dir)
    root.mkdir(parents=True, exist_ok=True)
    files = {
        "products": _write_frame(root, "products", bundle.products),
        "indices": _write_frame(root, "indices", bundle.indices),
        "summary": _write_frame(root, "summary", summary),
        "data": _write_frame(root, "data", data),
    }
    status_payload = {
        "status": _sanitize_json(asdict(bundle.status)),
        "kp_storm_eligible": bundle.kp_storm_eligible,
        "files": files,
    }
    with (root / "status.json").open("w", encoding="utf-8") as handle:
        json.dump(status_payload, handle, indent=2, sort_keys=True, default=_json_default)
    return root


def build_trial_bundle_zip(
    cache_key: str,
    bundle: IcaoProductBundle,
    summary: pd.DataFrame,
    data: pd.DataFrame,
) -> bytes:
    """Return a ZIP archive containing one cached trial-output folder."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = save_trial_bundle(
            cache_key,
            bundle,
            summary,
            data,
            base_dir=Path(tmpdir),
        )
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file_path in sorted(root.rglob("*")):
                if file_path.is_file():
                    archive.write(file_path, file_path.relative_to(root.parent))
        return output.getvalue()


def _write_frame(root: Path, stem: str, frame: pd.DataFrame) -> str:
    safe = frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    parquet_name = f"{stem}.parquet"
    try:
        safe.to_parquet(root / parquet_name, index=False)
        return parquet_name
    except Exception:
        csv_name = f"{stem}.csv"
        safe.to_csv(root / csv_name, index=False)
        return csv_name


def _read_frame(root: Path, file_name: str) -> pd.DataFrame:
    path = root / file_name
    if not path.exists():
        fallback = root / f"{Path(file_name).stem}.csv"
        if fallback.exists():
            path = fallback
        else:
            fallback = root / f"{Path(file_name).stem}.parquet"
            if fallback.exists():
                path = fallback
            else:
                return pd.DataFrame()
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def _sanitize_json(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            key_text = str(key)
            if any(part in key_text.casefold() for part in _SENSITIVE_KEY_PARTS):
                continue
            cleaned[key_text] = _sanitize_json(item)
        return cleaned
    if isinstance(value, list):
        return [_sanitize_json(item) for item in value]
    if is_dataclass(value):
        return _sanitize_json(asdict(value))
    return value


def _json_default(value: Any) -> str:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return str(value)


def _slug(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value).strip()).strip("-")
    return text[:120]
