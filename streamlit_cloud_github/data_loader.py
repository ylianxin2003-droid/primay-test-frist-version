"""Unified SERENE API data loader."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

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
        ``"AIDA"`` or ``"TOMIRIS"``.
    start_time, end_time : str, optional
        ISO 8601 timestamps passed to the API client.
    variables : list[str], optional
        Variable names to request (when supported by the API).
    region : dict, optional
        ``{"lat_min", "lat_max", "lon_min", "lon_max"}``.
    local_file : str, optional
        Ignored. Kept only for backward-compatible callers.
    grid_step : float
        Grid spacing (degrees) for API point sampling.

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

    client = SereneClient()
    r = region or {
        "lat_min": -90.0,
        "lat_max": 90.0,
        "lon_min": -180.0,
        "lon_max": 180.0,
    }
    api_frames: list[pd.DataFrame] = []

    ok, msg, raw = client.fetch_model_output(
        model=model,
        start_time=start_time or "",
        end_time=end_time or "",
        variables=variables,
        region=r,
        grid_step=grid_step,
        progress_callback=progress_callback,
    )

    if not ok:
        api_warnings.append(msg)
    elif raw is not None:
        df = client.parse_response_to_dataframe(raw, model=model)
        if variables and not df.empty and "variable" in df.columns:
            df = _filter_selected_variables(df, variables)

        if not df.empty:
            api_frames.append(df)
        else:
            api_warnings.append(msg or "API returned empty or unparseable data.")
    else:
        api_warnings.append(msg or "API returned no data.")

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
            "api_message": msg,
            "indices_message": msg_indices,
        }
        if api_warnings:
            status.warnings.extend(api_warnings)
        return df_api, status

    status.source = "none"
    status.ok = False
    status.message = "SERENE API returned no usable data."
    status.warnings.extend(api_warnings)
    return pd.DataFrame(), status


def _filter_selected_variables(df: pd.DataFrame, variables: list[str]) -> pd.DataFrame:
    selected = set(variables)
    if "vTEC" in selected:
        selected.add("TEC")
    if "TEC" in selected:
        selected.add("vTEC")
    return df[df["variable"].isin(selected)]
