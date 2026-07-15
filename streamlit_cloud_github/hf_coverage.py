"""HF coverage demonstration derived from SERENE AIDA MUF data.

The functions in this module are intentionally lightweight. They demonstrate
how Post-Storm Depression can reduce usable HF coverage for a selected
frequency, but they do not perform full ray tracing.
"""

from __future__ import annotations

from typing import Iterable

import pandas as pd


DEFAULT_UK_TRANSMITTER = {
    "name": "UK transmitter demo",
    "lat": 52.0,
    "lon": -1.5,
}

NORTH_ATLANTIC_ROUTE = [
    {"name": "UK", "lat": 52.0, "lon": -1.5},
    {"name": "Eastern Atlantic", "lat": 53.0, "lon": -15.0},
    {"name": "Mid Atlantic", "lat": 51.0, "lon": -32.0},
    {"name": "Western Atlantic", "lat": 46.0, "lon": -50.0},
    {"name": "North America", "lat": 41.0, "lon": -74.0},
]

_MUF_VARIABLES = {"MUF3000F2", "MUF3000"}
_CASE_COLUMNS = [
    "lat",
    "lon",
    "quiet_muf_mhz",
    "storm_muf_mhz",
    "selected_frequency_mhz",
    "quiet_available",
    "storm_available",
    "coverage_change",
]

_COVERAGE_COLORS = {
    "Usable in both": "#2E7D32",
    "Degraded during storm": "#EF6C00",
    "Not usable at selected frequency": "#607D8B",
    "Usable only after storm assumption": "#1565C0",
}


def latest_muf_grid(data: pd.DataFrame) -> pd.DataFrame:
    """Return the latest spatial MUF3000F2 analysis grid."""
    if data is None or data.empty or "variable" not in data.columns:
        return pd.DataFrame(columns=["lat", "lon", "quiet_muf_mhz", "time"])

    work = data[data["variable"].astype(str).isin(_MUF_VARIABLES)].copy()
    if work.empty or not {"lat", "lon", "value"}.issubset(work.columns):
        return pd.DataFrame(columns=["lat", "lon", "quiet_muf_mhz", "time"])

    for column in ("lat", "lon", "value"):
        work[column] = pd.to_numeric(work[column], errors="coerce")
    work = work.dropna(subset=["lat", "lon", "value"])
    if work.empty:
        return pd.DataFrame(columns=["lat", "lon", "quiet_muf_mhz", "time"])

    if "product_kind" in work.columns:
        analysis = work[work["product_kind"].astype(str) == "analysis"].copy()
        if not analysis.empty:
            work = analysis

    if "time" in work.columns:
        parsed_times = pd.to_datetime(work["time"], errors="coerce", utc=True)
        if parsed_times.notna().any():
            work = work.loc[parsed_times == parsed_times.max()].copy()

    columns = ["lat", "lon", "value"]
    if "time" in work.columns:
        columns.append("time")
    grid = work[columns].rename(columns={"value": "quiet_muf_mhz"})
    if "time" not in grid.columns:
        grid["time"] = pd.NaT
    return grid[["lat", "lon", "quiet_muf_mhz", "time"]].reset_index(drop=True)


def build_hf_coverage_case(
    data: pd.DataFrame,
    frequency_mhz: float = 10.0,
    psd_percent: float = 30.0,
) -> tuple[pd.DataFrame, dict]:
    """Build a quiet-vs-storm HF coverage demonstration from MUF3000F2."""
    frequency = max(float(frequency_mhz), 0.1)
    psd = min(max(float(psd_percent), 0.0), 95.0)
    grid = latest_muf_grid(data)

    if grid.empty:
        return pd.DataFrame(columns=_CASE_COLUMNS), {
            "total_cells": 0,
            "quiet_available_count": 0,
            "storm_available_count": 0,
            "degraded_count": 0,
            "quiet_available_pct": 0.0,
            "storm_available_pct": 0.0,
            "frequency_mhz": frequency,
            "psd_percent": psd,
            "message": "No spatial MUF3000F2 grid is available for the HF coverage case study.",
        }

    case = grid.copy()
    case["storm_muf_mhz"] = (case["quiet_muf_mhz"] * (1.0 - psd / 100.0)).clip(lower=0.0)
    case["selected_frequency_mhz"] = frequency
    case["quiet_available"] = case["quiet_muf_mhz"] >= frequency
    case["storm_available"] = case["storm_muf_mhz"] >= frequency
    case["coverage_change"] = case.apply(_coverage_label, axis=1)

    total = int(len(case))
    quiet_count = int(case["quiet_available"].sum())
    storm_count = int(case["storm_available"].sum())
    degraded_count = int((case["coverage_change"] == "Degraded during storm").sum())
    summary = {
        "total_cells": total,
        "quiet_available_count": quiet_count,
        "storm_available_count": storm_count,
        "degraded_count": degraded_count,
        "quiet_available_pct": quiet_count / total * 100.0 if total else 0.0,
        "storm_available_pct": storm_count / total * 100.0 if total else 0.0,
        "frequency_mhz": frequency,
        "psd_percent": psd,
        "message": "",
    }
    return case[_CASE_COLUMNS], summary


def create_hf_coverage_map(
    case: pd.DataFrame,
    transmitter: dict | None = None,
    route: Iterable[dict] | None = None,
    title: str | None = None,
) -> object:
    """Create a North Atlantic map for the HF coverage demonstration."""
    import plotly.graph_objects as go

    transmitter = transmitter or DEFAULT_UK_TRANSMITTER
    route_frame = pd.DataFrame(list(route or NORTH_ATLANTIC_ROUTE))
    fig = go.Figure()

    if case is None or case.empty:
        fig.add_annotation(
            text="No MUF3000F2 grid is available for the HF coverage case study.",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
        )
        fig.update_layout(template="plotly_white", height=520)
        return fig

    for label, color in _COVERAGE_COLORS.items():
        subset = case[case["coverage_change"] == label]
        if subset.empty:
            continue
        fig.add_trace(
            go.Scattergeo(
                lat=subset["lat"],
                lon=subset["lon"],
                mode="markers",
                name=label,
                marker={"size": 11, "color": color, "line": {"color": "white", "width": 0.7}},
                customdata=subset[[
                    "quiet_muf_mhz",
                    "storm_muf_mhz",
                    "selected_frequency_mhz",
                ]],
                hovertemplate=(
                    "lat=%{lat:.1f}, lon=%{lon:.1f}<br>"
                    "quiet MUF=%{customdata[0]:.1f} MHz<br>"
                    "storm MUF=%{customdata[1]:.1f} MHz<br>"
                    "selected frequency=%{customdata[2]:.1f} MHz<br>"
                    f"{label}<extra></extra>"
                ),
            )
        )

    fig.add_trace(
        go.Scattergeo(
            lat=route_frame["lat"],
            lon=route_frame["lon"],
            mode="lines+markers",
            name="Illustrative UK-North Atlantic route",
            line={"color": "#0D47A1", "width": 2, "dash": "dash"},
            marker={"size": 7, "color": "#0D47A1"},
            text=route_frame["name"],
            hovertemplate="%{text}<br>lat=%{lat:.1f}, lon=%{lon:.1f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scattergeo(
            lat=[float(transmitter["lat"])],
            lon=[float(transmitter["lon"])],
            mode="markers+text",
            name=transmitter["name"],
            text=["UK TX"],
            textposition="top center",
            marker={"size": 16, "color": "#B71C1C", "symbol": "star"},
            hovertemplate=f"{transmitter['name']}<extra></extra>",
        )
    )

    fig.update_geos(
        projection_type="natural earth",
        lataxis_range=[25, 70],
        lonaxis_range=[-85, 20],
        showcoastlines=True,
        coastlinecolor="gray",
        showland=True,
        landcolor="#F2F2F2",
        showocean=True,
        oceancolor="#EAF4FF",
    )
    fig.update_layout(
        title=title or "HF coverage case study",
        template="plotly_white",
        height=560,
        legend_title_text="Coverage change",
        margin={"l": 10, "r": 10, "t": 60, "b": 10},
    )
    return fig


def _coverage_label(row: pd.Series) -> str:
    if bool(row["quiet_available"]) and bool(row["storm_available"]):
        return "Usable in both"
    if bool(row["quiet_available"]) and not bool(row["storm_available"]):
        return "Degraded during storm"
    if not bool(row["quiet_available"]) and bool(row["storm_available"]):
        return "Usable only after storm assumption"
    return "Not usable at selected frequency"
