"""Unified SERENE API data loader."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from aida_grid import AidaGridError, estimate_target_points, sample_aida_hdf5
from serene_client import SereneClient

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
    """Load ionospheric data from SERENE API endpoints only.

    Parameters
    ----------
    source : str
        Only ``"api"`` is supported. Other values return no data.
    model : str
        Must be ``"AIDA"``. Other model families are not supported here.
    start_time, end_time : str, optional
        ISO 8601 timestamps passed to the API client.
    variables : list[str], optional
        Variable names to request (when supported by the API).
    region : dict, optional
        ``{"lat_min", "lat_max", "lon_min", "lon_max"}``.
    local_file : str, optional
        Ignored. Kept only for backward-compatible callers.
    grid_step : float
        Exact local sampling spacing in degrees, applied after one HDF5 download.

    Returns
    -------
    tuple[pd.DataFrame, LoadStatus]
        Standardised data and a status object describing the outcome.
    """
    del local_file
    status = LoadStatus()
    api_warnings: list[str] = []

    if source != "api":
        status.source = "none"
        status.ok = False
        status.message = "Only SERENE API data mode is supported."
        return pd.DataFrame(), status

    if model != "AIDA":
        status.source = "none"
        status.ok = False
        status.message = "Only the verified SERENE AIDA model is supported."
        return pd.DataFrame(), status

    client = SereneClient()
    r = region or {
        "lat_min": -90.0,
        "lat_max": 90.0,
        "lon_min": -180.0,
        "lon_max": 180.0,
    }
    api_frames: list[pd.DataFrame] = []
    requested_times = list(dict.fromkeys(value for value in (start_time, end_time) if value))
    if not requested_times:
        requested_times = [pd.Timestamp.now(tz="UTC").isoformat()]

    parsed_times = [pd.to_datetime(value, errors="coerce", utc=True) for value in requested_times]
    current_year = pd.Timestamp.now(tz="UTC").year
    historical = any(not pd.isna(value) and value.year < current_year for value in parsed_times)
    cadence = "final" if historical else "ultra"
    tolerance = pd.Timedelta(hours=24) if historical else pd.Timedelta(minutes=15)
    local_map_points = estimate_target_points(r, grid_step)

    ok_catalog, catalog_message, catalog = client.fetch_aida_catalog(cadence, "assimilation")
    selected_outputs = []
    if ok_catalog:
        for requested in requested_times:
            output = client.select_nearest_aida_output(catalog, requested, tolerance)
            if output is None:
                api_warnings.append(
                    f"No {cadence} AIDA output is close enough to requested time {requested}."
                )
            else:
                selected_outputs.append(output)
    else:
        api_warnings.append(catalog_message)

    unique_outputs = {
        output.download_path: output
        for output in selected_outputs
    }
    downloaded_outputs = []
    total_outputs = max(len(unique_outputs), 1)
    for index, output in enumerate(unique_outputs.values(), start=1):
        if progress_callback:
            progress_callback(index, total_outputs)
        ok_download, download_message, payload = client.download_aida_output(output)
        if not ok_download or payload is None:
            api_warnings.append(download_message)
            continue
        try:
            frame = sample_aida_hdf5(
                payload,
                region=r,
                step=grid_step,
                variables=variables,
                timestamp=output.timestamp,
                model="AIDA",
            )
        except AidaGridError as exc:
            api_warnings.append(str(exc))
            continue
        if not frame.empty:
            api_frames.append(frame)
            downloaded_outputs.append(output)

    ok_indices, msg_indices, indices_df = client.fetch_kp_ap_indices(
        start_time=start_time,
        end_time=end_time,
    )
    if ok_indices and not indices_df.empty:
        api_frames.append(indices_df)
    else:
        api_warnings.append(msg_indices)

    if api_frames:
        df_api = pd.concat(api_frames, ignore_index=True)
        status.source = "api"
        status.ok = True
        status.message = f"API connected — {len(df_api)} rows loaded from SERENE."
        status.metadata = {
            "model": model,
            "cadence": cadence,
            "catalog_message": catalog_message,
            "indices_message": msg_indices,
            "requested_times": requested_times,
            "actual_output_times": [item.timestamp.isoformat() for item in downloaded_outputs],
            "aida_output_ids": [item.output_id for item in downloaded_outputs],
            "aida_dataset_downloads": len(downloaded_outputs),
            "local_map_points": local_map_points,
            "grid_step_degrees": float(grid_step),
        }
        if api_warnings:
            status.warnings.extend(api_warnings)
        return df_api, status

    status.source = "none"
    status.ok = False
    status.message = "SERENE API returned no usable data."
    status.warnings.extend(api_warnings)
    status.metadata = {
        "model": model,
        "cadence": cadence,
        "catalog_message": catalog_message,
        "indices_message": msg_indices,
        "requested_times": requested_times,
        "actual_output_times": [item.timestamp.isoformat() for item in downloaded_outputs],
        "aida_output_ids": [item.output_id for item in downloaded_outputs],
        "aida_dataset_downloads": len(downloaded_outputs),
        "local_map_points": local_map_points,
        "grid_step_degrees": float(grid_step),
    }
    return pd.DataFrame(), status


def _filter_selected_variables(df: pd.DataFrame, variables: list[str]) -> pd.DataFrame:
    selected = set(variables)
    if "vTEC" in selected:
        selected.add("TEC")
    if "TEC" in selected:
        selected.add("vTEC")
    return df[df["variable"].isin(selected)]
