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


@dataclass
class IcaoProductBundle:
    """SERENE-only observations, forecasts, and index context for ICAO views."""

    products: pd.DataFrame = field(default_factory=pd.DataFrame)
    indices: pd.DataFrame = field(default_factory=pd.DataFrame)
    status: LoadStatus = field(default_factory=LoadStatus)
    kp_storm_eligible: bool | None = None


AIDA_ARCHIVE_START_UTC = pd.Timestamp("2024-09-28T00:00:00Z")
PSD_REFERENCE_EXPECTED_STATES = 30
PSD_REFERENCE_MIN_STATES = 28


def three_hour_aida_times(analysis_time: str) -> list[pd.Timestamp]:
    """Return the 37 distinct five-minute AIDA states ending at analysis time."""
    end = normalise_aida_request_time(analysis_time)
    return list(pd.date_range(end=end, periods=37, freq="5min", tz="UTC"))


def psd_reference_times(analysis_time: str) -> list[pd.Timestamp]:
    """Return one same-UTC reference state for each of the previous 30 days."""
    end = normalise_aida_request_time(analysis_time)
    return [end - pd.Timedelta(days=days) for days in range(30, 0, -1)]


def load_icao_products(
    analysis_time: str,
    variables: list[str],
    region: dict[str, float],
    grid_step: float,
    include_three_hour_window: bool = True,
    include_psd_baseline: bool = True,
    progress_callback: Any | None = None,
) -> IcaoProductBundle:
    """Load observed, rolling, and official forecast SERENE AIDA products."""
    status = LoadStatus(source="none", ok=False)
    try:
        analysis = normalise_aida_request_time(analysis_time)
        local_map_points = estimate_target_points(region, grid_step)
    except (AidaGridError, KeyError, TypeError, ValueError) as exc:
        status.message = f"Invalid ICAO product request: {exc}"
        return IcaoProductBundle(status=status)

    publication_safe_now = pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=15)
    if analysis < AIDA_ARCHIVE_START_UTC:
        status.message = "AIDA analysis time must not be before 2024-09-28 00:00 UTC."
        return IcaoProductBundle(status=status)
    if analysis > publication_safe_now:
        status.message = "AIDA analysis time must not be in the unpublished future window."
        return IcaoProductBundle(status=status)

    selected_variables = list(dict.fromkeys(variables or ["TEC"]))
    requested_rolling_times = (
        three_hour_aida_times(analysis.isoformat())
        if include_three_hour_window
        else [analysis]
    )
    rolling_times = [
        requested for requested in requested_rolling_times
        if requested >= AIDA_ARCHIVE_START_UTC
    ]
    rolling_truncated = len(rolling_times) < len(requested_rolling_times)
    requested_baseline_times = (
        psd_reference_times(analysis.isoformat())
        if include_psd_baseline and "MUF3000F2" in selected_variables
        else []
    )
    baseline_times = [
        requested for requested in requested_baseline_times
        if requested >= AIDA_ARCHIVE_START_UTC
    ]
    baseline_truncated = len(baseline_times) < len(requested_baseline_times)
    client = SereneClient()
    total_requests = len(rolling_times) + len(baseline_times) + 2
    completed = 0
    analysis_downloads = 0
    forecast_downloads = 0
    warnings: list[str] = []
    if rolling_truncated:
        warnings.append(
            "The three-hour window crosses the 2024-09-28 AIDA archive boundary; "
            "pre-archive states were not requested."
        )
    if baseline_truncated:
        warnings.append(
            "A complete 30-day AIDA reference is unavailable before the "
            "2024-09-28 archive boundary; PSD is unavailable."
        )
    product_frames: list[pd.DataFrame] = []
    baseline_value_series: list[pd.Series] = []
    baseline_download_failures = 0

    def report_progress(label: str) -> None:
        if progress_callback:
            progress_callback(completed, total_requests, label)

    for requested in rolling_times:
        latency = _aida_latency(requested)
        ok, message, payload = client.download_aida_raw_output(
            requested.isoformat(), latency
        )
        completed += 1
        report_progress("3-hour AIDA observations")
        if not ok or payload is None:
            warnings.append(message)
            continue
        analysis_downloads += 1
        try:
            frame = _calculate_product_frame(
                payload, region, grid_step, selected_variables,
                product_kind="rolling", requested_time=requested,
            )
        except AidaGridError as exc:
            warnings.append(str(exc))
            continue
        if frame.empty:
            continue
        product_frames.append(frame)
        if requested == analysis:
            latest = frame.copy()
            latest["product_kind"] = "analysis"
            product_frames.append(latest)

    baseline_variables = ["MUF3000F2"]
    for requested in baseline_times:
        latency = _aida_latency(requested)
        ok, message, payload = client.download_aida_raw_output(
            requested.isoformat(), latency
        )
        completed += 1
        report_progress("30-day PSD reference")
        if not ok or payload is None:
            baseline_download_failures += 1
            logger.info("PSD baseline AIDA state unavailable: %s", message)
            continue
        analysis_downloads += 1
        try:
            frame = _calculate_product_frame(
                payload, region, grid_step, baseline_variables,
                product_kind="baseline", requested_time=requested,
            )
        except AidaGridError as exc:
            warnings.append(str(exc))
            continue
        if not frame.empty:
            values = _baseline_value_series(frame, requested)
            if not values.empty:
                baseline_value_series.append(values)

    for period in (180, 360):
        latency = _aida_latency(analysis)
        ok, message, payload = client.download_aida_forecast(
            analysis.isoformat(), latency, period
        )
        completed += 1
        report_progress(f"AIDA +{period // 60}h forecast")
        if not ok or payload is None:
            warnings.append(message)
            continue
        forecast_downloads += 1
        try:
            frame = _calculate_product_frame(
                payload, region, grid_step, selected_variables,
                product_kind=f"forecast_{period}", requested_time=analysis,
                forecast_minutes=period,
            )
        except AidaGridError as exc:
            warnings.append(f"Official AIDA +{period // 60}h forecast unavailable: {exc}")
            continue
        if not frame.empty:
            product_frames.append(frame)

    index_start = (analysis - pd.Timedelta(hours=96)).isoformat()
    ok_indices, indices_message, indices = client.fetch_kp_ap_indices(
        start_time=index_start,
        end_time=analysis.isoformat(),
    )
    if not ok_indices:
        warnings.append(indices_message)
        indices = pd.DataFrame()

    products = (
        pd.concat(product_frames, ignore_index=True)
        if product_frames else pd.DataFrame()
    )
    reference_state_count = len({
        series.name for series in baseline_value_series if not series.empty
    })
    if baseline_times:
        if reference_state_count >= PSD_REFERENCE_MIN_STATES:
            missing = PSD_REFERENCE_EXPECTED_STATES - reference_state_count
            if missing > 0:
                warnings.append(
                    f"PSD reference used {reference_state_count}/"
                    f"{PSD_REFERENCE_EXPECTED_STATES} available SERENE AIDA "
                    "states; missing reference files were skipped."
                )
        else:
            warnings.append(
                f"PSD unavailable: only {reference_state_count}/"
                f"{PSD_REFERENCE_EXPECTED_STATES} SERENE AIDA reference "
                "states were available."
            )
    reference = _build_psd_reference(baseline_value_series)
    products = _attach_psd_reference(products, reference)
    kp_values = pd.Series(dtype=float)
    if not indices.empty and "variable" in indices.columns:
        kp_values = pd.to_numeric(
            indices.loc[indices["variable"] == "Kp", "value"],
            errors="coerce",
        ).dropna()
    kp_history_complete = _kp_history_is_complete(indices, analysis)
    kp_storm_eligible = (
        bool(kp_values.max() >= 6) if kp_history_complete else None
    )
    if not kp_history_complete:
        warnings.append(
            "Complete 96-hour SERENE Kp history is unavailable; PSD status is unavailable."
        )

    has_analysis = (
        not products.empty
        and "product_kind" in products.columns
        and (products["product_kind"] == "analysis").any()
    )
    status.source = "api" if has_analysis else "none"
    status.ok = bool(has_analysis)
    status.message = (
        "Loaded SERENE AIDA observations and available official forecasts."
        if has_analysis else
        "SERENE returned no usable AIDA analysis state."
    )
    status.warnings = warnings
    status.metadata = {
        "analysis_time": analysis.isoformat(),
        "analysis_downloads": analysis_downloads,
        "forecast_downloads": forecast_downloads,
        "local_map_points": local_map_points,
        "grid_step_degrees": float(grid_step),
        "loaded_region": dict(region),
        "rolling_state_count": len(rolling_times),
        "baseline_state_count": len(baseline_times),
        "baseline_reference_states_used": reference_state_count,
        "baseline_download_failures": baseline_download_failures,
        "upstream_interpreter": (
            f"breid-phys/aida-ionosphere {UPSTREAM_AIDA_VERSION}"
        ),
    }
    return IcaoProductBundle(products, indices, status, kp_storm_eligible)


def _aida_latency(requested: pd.Timestamp) -> str:
    """Choose an AIDA product suitable for five-minute map requests.

    SERENE lists the ``final`` AIDA product as a daily product, while this
    dashboard requests specific five-minute states and official forecast files.
    Forecast downloads only support ultra-rapid/rapid products, so historical
    testing uses rapid rather than final to avoid invalid ``product=final``
    forecast requests and missing five-minute final raw files.
    """
    return "ultra" if requested.year == pd.Timestamp.now(tz="UTC").year else "rapid"


def _calculate_product_frame(
    payload: bytes,
    region: dict[str, float],
    grid_step: float,
    variables: list[str],
    product_kind: str,
    requested_time: pd.Timestamp,
    forecast_minutes: int = 0,
) -> pd.DataFrame:
    frame = calculate_aida_grid(payload, region, grid_step, variables)
    if frame.empty:
        return frame
    frame = frame.copy()
    frame["product_kind"] = product_kind
    frame["requested_time"] = requested_time
    frame["forecast_minutes"] = int(forecast_minutes)
    return frame


def _baseline_value_series(
    frame: pd.DataFrame,
    requested_time: pd.Timestamp,
) -> pd.Series:
    """Reduce one baseline grid to the numeric values needed for its median."""
    required = {"lat", "lon", "variable", "value"}
    if frame.empty or not required.issubset(frame.columns):
        return pd.Series(dtype=float, name=requested_time)
    work = frame.loc[
        frame["variable"] == "MUF3000F2", ["lat", "lon", "value"]
    ].copy()
    work["lat"] = pd.to_numeric(work["lat"], errors="coerce")
    work["lon"] = pd.to_numeric(work["lon"], errors="coerce")
    work["value"] = pd.to_numeric(work["value"], errors="coerce")
    work = work.dropna(subset=["lat", "lon"])
    if work.empty:
        return pd.Series(dtype=float, name=requested_time)
    values = work.groupby(["lat", "lon"], sort=False)["value"].median()
    values.name = requested_time
    return values


def _build_psd_reference(
    baseline_values: list[pd.Series],
    expected_states: int = PSD_REFERENCE_EXPECTED_STATES,
    min_states: int = PSD_REFERENCE_MIN_STATES,
) -> pd.DataFrame:
    """Build a per-cell median from the available 30-day reference matrix."""
    non_empty = [series for series in baseline_values if not series.empty]
    required_states = min(expected_states, min_states)
    if len({series.name for series in non_empty}) < required_states:
        return pd.DataFrame(columns=["lat", "lon", "reference_value"])
    matrix = pd.concat(non_empty, axis=1)
    complete = matrix.notna().sum(axis=1) >= required_states
    if not complete.any():
        return pd.DataFrame(columns=["lat", "lon", "reference_value"])
    reference = matrix.loc[complete].median(axis=1).rename("reference_value")
    return reference.reset_index()


def _attach_psd_reference(
    products: pd.DataFrame,
    reference: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if products.empty or "product_kind" not in products.columns:
        return products
    non_baseline = products[products["product_kind"] != "baseline"].copy()
    if reference is None:
        baseline = products[
            (products["product_kind"] == "baseline")
            & (products["variable"] == "MUF3000F2")
        ]
        if "requested_time" not in baseline.columns:
            reference = pd.DataFrame()
        else:
            series = [
                _baseline_value_series(group, requested)
                for requested, group in baseline.groupby("requested_time")
            ]
            reference = _build_psd_reference(series)
    if reference.empty:
        non_baseline["reference_value"] = pd.NA
        non_baseline["psd_percent"] = pd.NA
        return non_baseline
    result = non_baseline.drop(
        columns=["reference_value", "psd_percent"], errors="ignore"
    )
    merged = result.merge(reference, on=["lat", "lon"], how="left")
    is_muf = merged["variable"] == "MUF3000F2"
    current = pd.to_numeric(merged["value"], errors="coerce")
    reference_value = pd.to_numeric(merged["reference_value"], errors="coerce")
    valid = is_muf & reference_value.gt(0) & current.notna()
    merged["psd_percent"] = pd.NA
    merged.loc[valid, "psd_percent"] = (
        ((reference_value[valid] - current[valid]) / reference_value[valid])
        .clip(lower=0)
        * 100.0
    )
    return merged


def _kp_history_is_complete(indices: pd.DataFrame, analysis: pd.Timestamp) -> bool:
    if indices.empty or not {"variable", "time", "value"}.issubset(indices.columns):
        return False
    kp = indices[indices["variable"] == "Kp"].copy()
    kp["time"] = pd.to_datetime(kp["time"], errors="coerce", utc=True)
    kp["value"] = pd.to_numeric(kp["value"], errors="coerce")
    kp = kp.dropna(subset=["time", "value"]).sort_values("time")
    if len(kp) < 32 or kp["time"].nunique() < 32:
        return False
    if kp["time"].max() < analysis - pd.Timedelta(hours=3):
        return False
    if kp["time"].min() > analysis - pd.Timedelta(hours=93):
        return False
    gaps = kp["time"].drop_duplicates().sort_values().diff().dropna()
    return bool(gaps.empty or gaps.max() <= pd.Timedelta(hours=3, minutes=5))


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
        for value in requested_times:
            try:
                parsed = normalise_aida_request_time(value)
            except ValueError:
                warnings.append(f"Invalid requested AIDA time: {value}")
                continue
            latency = _aida_latency(parsed)
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
