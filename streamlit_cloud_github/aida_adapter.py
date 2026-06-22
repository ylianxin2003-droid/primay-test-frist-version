"""Boundary around Benjamin Reid's official AIDA scientific interpreter.

Upstream source (MIT License): https://github.com/breid-phys/aida-ionosphere
The upstream package reads raw AIDA states and performs the scientific model
calculation; this module only adapts its output to the dashboard schema.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd

from aida_grid import (
    AidaGridError,
    normalise_aida_variables,
    target_axis,
)


UPSTREAM_AIDA_VERSION = "v0.1.3"
UPSTREAM_AIDA_SOURCE = "https://github.com/breid-phys/aida-ionosphere"


def _official_state_factory() -> Any:
    """Create the interpreter lazily so the page can show dependency errors."""
    try:
        import aida
    except ImportError as exc:
        raise AidaGridError(
            "The official breid-phys/aida-ionosphere package is not installed."
        ) from exc
    return aida.AIDAState()


def calculate_aida_grid(
    payload: bytes,
    region: dict[str, float],
    step: float,
    variables: list[str] | None,
    state_factory: Callable[[], Any] | None = None,
) -> pd.DataFrame:
    """Calculate an exact regional grid from one raw AIDA state response."""
    target_lats = target_axis(region["lat_min"], region["lat_max"], step)
    target_lons = target_axis(region["lon_min"], region["lon_max"], step)
    if target_lats[0] < -90 or target_lats[-1] > 90:
        raise AidaGridError("Latitude bounds must be within -90 and 90 degrees.")
    if target_lons[0] < -180 or target_lons[-1] > 180:
        raise AidaGridError("Longitude bounds must be within -180 and 180 degrees.")
    selected = normalise_aida_variables(variables)

    factory = state_factory or _official_state_factory
    state = factory()
    try:
        with tempfile.NamedTemporaryFile(suffix=".h5") as handle:
            handle.write(payload)
            handle.flush()
            state.readFile(handle.name)
    except AidaGridError:
        raise
    except Exception as exc:
        raise AidaGridError(
            f"Official AIDA interpreter could not read the raw state: {exc}"
        ) from exc

    # Scientific grid-call contract follows the upstream "Example 3: Maps":
    # https://github.com/breid-phys/aida-ionosphere#example-3-maps
    try:
        output = state.calc(
            lat=target_lats,
            lon=target_lons,
            grid="3D",
            TEC="TEC" in selected,
            MUF3000="MUF3000F2" in selected,
            collapse_particles=True,
            as_dict=True,
        )
    except Exception as exc:
        raise AidaGridError(f"Official AIDA grid calculation failed: {exc}") from exc

    output_time = _normalise_state_time(state.Time)
    upstream_names = {"MUF3000F2": "MUF3000"}
    rows: list[dict[str, object]] = []
    expected_shape = (len(target_lons), len(target_lats))
    for variable in selected:
        field = upstream_names.get(variable, variable)
        if field not in output:
            raise AidaGridError(f"Official AIDA output is missing requested field: {field}")
        values = np.asarray(output[field], dtype=float)
        if values.shape != expected_shape:
            raise AidaGridError(
                f"AIDA field {field} has shape {values.shape}; expected {expected_shape}."
            )
        for lon_index, lon in enumerate(target_lons):
            for lat_index, lat in enumerate(target_lats):
                rows.append({
                    "time": output_time,
                    "lat": float(lat),
                    "lon": float(lon),
                    "variable": variable,
                    "value": float(values[lon_index, lat_index]),
                    "model": "AIDA",
                    "source": (
                        "SERENE raw API + breid-phys/aida-ionosphere "
                        f"{UPSTREAM_AIDA_VERSION}"
                    ),
                })

    return pd.DataFrame(rows)


def _normalise_state_time(value: object) -> pd.Timestamp:
    """Convert the upstream AIDA epoch or datetime scalar to UTC."""
    scalar = np.asarray(value).squeeze()
    if np.asarray(scalar).size != 1:
        raise AidaGridError("Official AIDA state time must be a scalar.")
    try:
        if np.issubdtype(np.asarray(scalar).dtype, np.datetime64):
            parsed = pd.to_datetime(scalar, errors="coerce", utc=True)
        else:
            parsed = pd.to_datetime(float(scalar), unit="s", errors="coerce", utc=True)
    except (TypeError, ValueError, OverflowError) as exc:
        raise AidaGridError(f"Invalid official AIDA state time: {value}") from exc
    if pd.isna(parsed):
        raise AidaGridError(f"Invalid official AIDA state time: {value}")
    return parsed
