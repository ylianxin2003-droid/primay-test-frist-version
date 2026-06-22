"""Unified SERENE API data loader."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from aida_adapter import UPSTREAM_AIDA_VERSION, calculate_aida_grid
from aida_grid import AidaGridError, estimate_target_points
from serene_client import SereneClient, normalise_aida_request_time

logger = logging.getLogger(__name__)


@dataclass
class LoadStatus:
    """Metadata about a data loading operation."""

    source: str = "unknown"
    ok: bool = False
    message: str = ""
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def load_data(
    source: str = "api",
    model: str = "AIDA",
    start_time: str | None = None,
    end_time: str | None = None,
    variables: list[str] | None = None,
    region: dict[str, float] | None = None,
    local_file: str | None = None,
    grid_step: float = 10.0,
    progress_callback: Any | None = None,
) -> tuple[pd.DataFrame, LoadStatus]:
    """Download one raw AIDA state per requested time and calculate locally."""
    del local_file
    status = LoadStatus()
    warnings: list[str] = []

    if source != "api":
        status.source = "none"
        status.message = "Only SERENE API data mode is supported."
        return pd.DataFrame(), status
    if model != "AIDA":
        status.source = "none"
        status.message = "Only the verified SERENE AIDA model is supported."
        return pd.DataFrame(), status

    selected_region = region or {
        "lat_min": -90.0,
        "lat_max": 90.0,
        "lon_min": -180.0,
        "lon_max": 180.0,
    }
    try:
        local_map_points = estimate_target_points(selected_region, grid_step)
    except (AidaGridError, KeyError, TypeError, ValueError) as exc:
        status.source = "none"
        status.message = f"Invalid regional grid: {exc}"
        return pd.DataFrame(), status

    requested_times = list(dict.fromkeys(
        value for value in (start_time, end_time) if value
    ))
    request_specs: list[tuple[str | None, str]] = []
    if not requested_times:
        request_specs = [(None, "ultra")]
    else:
        current_year = pd.Timestamp.now(tz="UTC").year
        for value in requested_times:
            try:
                parsed = normalise_aida_request_time(value)
            except ValueError:
                warnings.append(f"Invalid requested AIDA time: {value}")
                continue
            latency = "final" if parsed.year < current_year else "ultra"
            request_specs.append((parsed.isoformat(), latency))
        request_specs = list(dict.fromkeys(request_specs))

    client = SereneClient()
    aida_frames: list[pd.DataFrame] = []
    downloaded_count = 0
    download_messages: list[str] = []
    total_requests = max(len(request_specs), 1)
    for index, (requested_time, latency) in enumerate(request_specs, start=1):
        if progress_callback:
            progress_callback(index, total_requests)
        ok_download, download_message, payload = client.download_aida_raw_output(
            requested_time,
            latency,
        )
        download_messages.append(download_message)
        if not ok_download or payload is None:
            warnings.append(download_message)
            continue
        downloaded_count += 1
        try:
            frame = calculate_aida_grid(
                payload,
                selected_region,
                grid_step,
                variables,
            )
        except AidaGridError as exc:
            warnings.append(str(exc))
            continue
        if not frame.empty:
            aida_frames.append(frame)

    ok_indices, indices_message, indices_frame = client.fetch_kp_ap_indices(
        start_time=start_time,
        end_time=end_time,
    )
    if not ok_indices or indices_frame.empty:
        warnings.append(indices_message)
        indices_frame = pd.DataFrame()

    actual_output_times: list[str] = []
    for frame in aida_frames:
        if "time" not in frame.columns:
            continue
        for value in pd.to_datetime(frame["time"], errors="coerce", utc=True).dropna().unique():
            iso = pd.Timestamp(value).isoformat()
            if iso not in actual_output_times:
                actual_output_times.append(iso)

    metadata = {
        "model": model,
        "cadences": list(dict.fromkeys(latency for _time, latency in request_specs)),
        "indices_message": indices_message,
        "requested_times": requested_times,
        "request_specs": [
            {"time": requested or "latest", "latency": latency}
            for requested, latency in request_specs
        ],
        "download_messages": download_messages,
        "actual_output_times": actual_output_times,
        "aida_dataset_downloads": downloaded_count,
        "local_map_points": local_map_points,
        "grid_step_degrees": float(grid_step),
        "upstream_interpreter": (
            f"breid-phys/aida-ionosphere {UPSTREAM_AIDA_VERSION}"
        ),
    }

    if aida_frames:
        frames = list(aida_frames)
        if not indices_frame.empty:
            frames.append(indices_frame)
        combined = pd.concat(frames, ignore_index=True)
        status.source = "api"
        status.ok = True
        status.message = (
            f"Loaded {len(combined)} rows from {downloaded_count} raw AIDA "
            "state(s), with regional values calculated locally."
        )
        status.warnings.extend(warnings)
        status.metadata = metadata
        return combined, status

    if not indices_frame.empty:
        status.source = "indices"
        status.ok = False
        status.message = (
            "Global Kp/ap indices loaded, but regional AIDA data could not be calculated."
        )
        status.warnings.extend(warnings)
        status.metadata = metadata
        return indices_frame.reset_index(drop=True), status

    status.source = "none"
    status.ok = False
    status.message = "SERENE API returned no usable regional AIDA data."
    status.warnings.extend(warnings)
    status.metadata = metadata
    return pd.DataFrame(), status


def _filter_selected_variables(df: pd.DataFrame, variables: list[str]) -> pd.DataFrame:
    """Backward-compatible helper retained for callers outside the dashboard."""
    selected = set(variables)
    if "vTEC" in selected:
        selected.add("TEC")
    if "TEC" in selected:
        selected.add("vTEC")
    return df[df["variable"].isin(selected)]
