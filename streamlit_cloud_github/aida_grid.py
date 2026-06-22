"""Parse and locally sample SERENE AIDA two-dimensional HDF5 products."""

from __future__ import annotations

from io import BytesIO

import h5py
import numpy as np
import pandas as pd


AIDA_VARIABLES = ("TEC", "foF2", "MUF3000F2", "NmF2", "hmF2")
_VARIABLE_ALIASES = {"vTEC": "TEC", "MUF3000": "MUF3000F2"}


class AidaGridError(ValueError):
    """Raised when an AIDA grid is missing or internally inconsistent."""


def target_axis(lower: float, upper: float, step: float) -> np.ndarray:
    """Return an ascending axis that preserves the requested spacing exactly."""
    if not np.isfinite(step) or step <= 0:
        raise AidaGridError("Grid step must be positive.")
    lo, hi = sorted((float(lower), float(upper)))
    if not np.isfinite(lo) or not np.isfinite(hi):
        raise AidaGridError("Grid bounds must be finite.")
    count = int(np.floor((hi - lo) / float(step) + 1e-9)) + 1
    return lo + np.arange(count, dtype=float) * float(step)


def estimate_target_points(region: dict[str, float], step: float) -> int:
    """Return the number of locally generated points for a region."""
    latitudes = target_axis(region["lat_min"], region["lat_max"], step)
    longitudes = target_axis(region["lon_min"], region["lon_max"], step)
    return int(len(latitudes) * len(longitudes))


def normalise_aida_variables(variables: list[str] | None) -> list[str]:
    """Return supported dashboard variable names with aliases resolved."""
    requested = variables or list(AIDA_VARIABLES)
    selected = list(dict.fromkeys(_VARIABLE_ALIASES.get(name, name) for name in requested))
    unknown = [name for name in selected if name not in AIDA_VARIABLES]
    if unknown:
        raise AidaGridError(f"Unsupported AIDA variable(s): {', '.join(unknown)}")
    return selected


def sample_aida_hdf5(
    payload: bytes,
    region: dict[str, float],
    step: float,
    variables: list[str] | None,
    timestamp: str | pd.Timestamp,
    model: str = "AIDA",
) -> pd.DataFrame:
    """Convert one global AIDA HDF5 response to locally sampled long-form rows."""
    try:
        handle = h5py.File(BytesIO(payload), "r")
    except (OSError, ValueError) as exc:
        raise AidaGridError(f"Invalid AIDA HDF5 response: {exc}") from exc

    with handle:
        for required in ("Latitudes", "Longitudes"):
            if required not in handle:
                raise AidaGridError(f"AIDA HDF5 is missing required dataset: {required}")

        source_lats = np.asarray(handle["Latitudes"], dtype=float)
        source_lons = np.asarray(handle["Longitudes"], dtype=float)
        _validate_source_axis("Latitudes", source_lats)
        _validate_source_axis("Longitudes", source_lons)

        target_lats = target_axis(region["lat_min"], region["lat_max"], step)
        target_lons = target_axis(region["lon_min"], region["lon_max"], step)
        if target_lats[0] < -90 or target_lats[-1] > 90:
            raise AidaGridError("Latitude bounds must be within -90 and 90 degrees.")
        if target_lons[0] < -180 or target_lons[-1] > 180:
            raise AidaGridError("Longitude bounds must be within -180 and 180 degrees.")

        selected = normalise_aida_variables(variables)

        output_time = pd.to_datetime(timestamp, errors="coerce", utc=True)
        if pd.isna(output_time):
            raise AidaGridError(f"Invalid AIDA output timestamp: {timestamp}")

        rows: list[dict[str, object]] = []
        expected_shape = (len(source_lons), len(source_lats))
        for variable in selected:
            if variable not in handle:
                raise AidaGridError(f"AIDA HDF5 is missing requested dataset: {variable}")
            values = np.asarray(handle[variable], dtype=float)
            if values.shape != expected_shape:
                raise AidaGridError(
                    f"AIDA dataset {variable} has shape {values.shape}; expected {expected_shape}."
                )
            for lon in target_lons:
                for lat in target_lats:
                    rows.append({
                        "time": output_time,
                        "lat": float(lat),
                        "lon": float(lon),
                        "variable": variable,
                        "value": float(_bilinear(source_lats, source_lons, values, lat, lon)),
                        "model": model,
                        "source": "SERENE AIDA param_2d API",
                    })

    return pd.DataFrame(rows)


def _validate_source_axis(name: str, axis: np.ndarray) -> None:
    if axis.ndim != 1 or len(axis) < 2 or not np.isfinite(axis).all():
        raise AidaGridError(f"AIDA dataset {name} must be a finite one-dimensional axis.")
    if not np.all(np.diff(axis) > 0):
        raise AidaGridError(f"AIDA dataset {name} must be strictly increasing.")


def _bracket(axis: np.ndarray, value: float) -> tuple[int, int, float]:
    if value < axis[0] - 1e-9 or value > axis[-1] + 1e-9:
        raise AidaGridError(f"Requested coordinate {value} is outside AIDA grid bounds.")
    upper = int(np.searchsorted(axis, value, side="right"))
    if upper == 0:
        return 0, 0, 0.0
    if upper >= len(axis):
        return len(axis) - 1, len(axis) - 1, 0.0
    lower = upper - 1
    if np.isclose(value, axis[lower]):
        return lower, lower, 0.0
    weight = (value - axis[lower]) / (axis[upper] - axis[lower])
    return lower, upper, float(weight)


def _bilinear(
    latitudes: np.ndarray,
    longitudes: np.ndarray,
    values: np.ndarray,
    latitude: float,
    longitude: float,
) -> float:
    lat_lo, lat_hi, lat_weight = _bracket(latitudes, float(latitude))

    periodic = longitudes[-1] - longitudes[0] >= 359.0 - 1e-9
    lon_value = float(longitude)
    lon_axis = longitudes
    lon_values = values
    if periodic:
        lon_value = ((lon_value - longitudes[0]) % 360.0) + longitudes[0]
        lon_axis = np.append(longitudes, longitudes[0] + 360.0)
        lon_values = np.concatenate([values, values[0:1, :]], axis=0)

    lon_lo, lon_hi, lon_weight = _bracket(lon_axis, lon_value)
    low_lat = (
        lon_values[lon_lo, lat_lo] * (1.0 - lon_weight)
        + lon_values[lon_hi, lat_lo] * lon_weight
    )
    high_lat = (
        lon_values[lon_lo, lat_hi] * (1.0 - lon_weight)
        + lon_values[lon_hi, lat_hi] * lon_weight
    )
    return float(low_lat * (1.0 - lat_weight) + high_lat * lat_weight)
