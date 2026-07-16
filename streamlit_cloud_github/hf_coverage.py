"""HF coverage demonstration derived from SERENE AIDA MUF data.

The functions in this module are intentionally lightweight. They demonstrate
how Post-Storm Depression can reduce usable HF coverage for a selected
frequency, but they do not perform full ray tracing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
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

TRANSMITTER_PRESETS = {
    "UK transmitter": DEFAULT_UK_TRANSMITTER,
}

TARGET_PRESETS = {
    "North Atlantic corridor": {"name": "North Atlantic corridor", "lat": 51.0, "lon": -32.0},
    "New York JFK": {"name": "New York JFK", "lat": 40.6413, "lon": -73.7781},
}

DEFAULT_SWEEP_FREQUENCIES = [5.0, 7.5, 10.0, 12.5, 15.0, 17.5, 20.0]

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
    "risk_category",
]

_COVERAGE_COLORS = {
    "Usable in both": "#2E7D32",
    "Degraded during storm": "#EF6C00",
    "Unusable in both": "#607D8B",
    "Improved during storm": "#1565C0",
}


@dataclass(frozen=True)
class HfEngineeringCase:
    """Container for the route-level HF engineering case study."""

    grid: pd.DataFrame
    route: pd.DataFrame
    summary: dict
    transmitter: dict
    target: dict


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


def latest_muf_comparison_grid(
    data: pd.DataFrame,
    assumed_psd_percent: float = 30.0,
) -> tuple[pd.DataFrame, str]:
    """Return quiet/storm MUF grid, preferring AIDA reference values when present."""
    empty_columns = [
        "lat",
        "lon",
        "quiet_muf_mhz",
        "storm_muf_mhz",
        "psd_percent",
        "time",
    ]
    if data is None or data.empty or "variable" not in data.columns:
        return pd.DataFrame(columns=empty_columns), "Unavailable"

    work = data[data["variable"].astype(str).isin(_MUF_VARIABLES)].copy()
    if work.empty or not {"lat", "lon", "value"}.issubset(work.columns):
        return pd.DataFrame(columns=empty_columns), "Unavailable"

    for column in ("lat", "lon", "value"):
        work[column] = pd.to_numeric(work[column], errors="coerce")
    work = work.dropna(subset=["lat", "lon", "value"])
    if work.empty:
        return pd.DataFrame(columns=empty_columns), "Unavailable"

    if "product_kind" in work.columns:
        analysis = work[work["product_kind"].astype(str) == "analysis"].copy()
        if not analysis.empty:
            work = analysis
    if "time" in work.columns:
        parsed_times = pd.to_datetime(work["time"], errors="coerce", utc=True)
        if parsed_times.notna().any():
            work = work.loc[parsed_times == parsed_times.max()].copy()

    comparison_mode = "Assumed PSD demonstration"
    if "reference_value" in work.columns:
        work["reference_value"] = pd.to_numeric(work["reference_value"], errors="coerce")
        has_reference = work["reference_value"].gt(0).any()
    else:
        work["reference_value"] = pd.NA
        has_reference = False

    result = work[["lat", "lon", "value", "reference_value"]].copy()
    if "time" in work.columns:
        result["time"] = work["time"]
    else:
        result["time"] = pd.NaT

    if has_reference:
        result["quiet_muf_mhz"] = result["reference_value"]
        result["storm_muf_mhz"] = result["value"]
        comparison_mode = "AIDA quiet vs storm comparison"
    else:
        psd = min(max(float(assumed_psd_percent), 0.0), 95.0)
        result["quiet_muf_mhz"] = result["value"]
        result["storm_muf_mhz"] = (result["value"] * (1.0 - psd / 100.0)).clip(lower=0.0)

    result["psd_percent"] = _psd_series(result["storm_muf_mhz"], result["quiet_muf_mhz"])
    result = result.dropna(subset=["quiet_muf_mhz", "storm_muf_mhz"])
    return result[empty_columns].reset_index(drop=True), comparison_mode


def build_hf_engineering_case(
    data: pd.DataFrame,
    frequency_mhz: float = 10.0,
    transmitter: dict | None = None,
    target: dict | None = None,
    route_samples: int = 33,
    assumed_psd_percent: float = 30.0,
) -> HfEngineeringCase:
    """Build regional and route-level HF communication impact metrics."""
    frequency = max(float(frequency_mhz), 0.1)
    transmitter = transmitter or DEFAULT_UK_TRANSMITTER
    target = target or TARGET_PRESETS["New York JFK"]
    grid, comparison_mode = latest_muf_comparison_grid(data, assumed_psd_percent)
    route = great_circle_route(transmitter, target, samples=route_samples)

    if grid.empty:
        return HfEngineeringCase(
            grid=pd.DataFrame(columns=[*_CASE_COLUMNS, "psd_percent"]),
            route=route,
            summary=_empty_engineering_summary(frequency, comparison_mode),
            transmitter=transmitter,
            target=target,
        )

    evaluated_grid = _evaluate_grid_for_frequency(grid, frequency)
    sampled_route = sample_route_from_grid(route, evaluated_grid)
    route_evaluation = _evaluate_route_for_frequency(sampled_route, frequency)
    summary = _engineering_summary(evaluated_grid, route_evaluation, frequency, comparison_mode)
    return HfEngineeringCase(
        grid=evaluated_grid,
        route=route_evaluation,
        summary=summary,
        transmitter=transmitter,
        target=target,
    )


def build_frequency_sweep(
    case: HfEngineeringCase,
    frequencies: Iterable[float] | None = None,
) -> pd.DataFrame:
    """Evaluate regional and route availability over a frequency set."""
    frequencies = list(frequencies or DEFAULT_SWEEP_FREQUENCIES)
    rows = []
    for frequency in frequencies:
        evaluated_grid = _evaluate_grid_for_frequency(case.grid, float(frequency))
        sampled_route = sample_route_from_grid(case.route[["lat", "lon"]], evaluated_grid)
        route_evaluation = _evaluate_route_for_frequency(sampled_route, float(frequency))
        summary = _engineering_summary(
            evaluated_grid,
            route_evaluation,
            float(frequency),
            case.summary.get("comparison_mode", "Unknown"),
        )
        rows.append({
            "frequency_mhz": float(frequency),
            "quiet_regional_coverage_pct": summary["quiet_usable_grid_pct"],
            "storm_regional_coverage_pct": summary["storm_usable_grid_pct"],
            "regional_coverage_loss_pct_points": summary["regional_coverage_loss_pct_points"],
            "relative_regional_reduction_pct": summary["relative_regional_reduction_pct"],
            "quiet_route_availability_pct": summary["quiet_route_available_pct"],
            "storm_route_availability_pct": summary["storm_route_available_pct"],
            "route_classification": summary["route_status"],
        })
    sweep = pd.DataFrame(rows)
    if sweep.empty:
        return sweep
    best_index = sweep["storm_route_availability_pct"].astype(float).idxmax()
    sweep["highest_storm_route_availability_in_research_case"] = False
    sweep.loc[best_index, "highest_storm_route_availability_in_research_case"] = True
    sweep["label"] = ""
    sweep.loc[best_index, "label"] = "Highest storm route availability in this research comparison"
    return sweep


def great_circle_route(
    transmitter: dict,
    target: dict,
    samples: int = 33,
) -> pd.DataFrame:
    """Return approximate great-circle points between transmitter and target."""
    samples = max(int(samples), 2)
    lat1 = math.radians(float(transmitter["lat"]))
    lon1 = math.radians(float(transmitter["lon"]))
    lat2 = math.radians(float(target["lat"]))
    lon2 = math.radians(float(target["lon"]))
    central = _central_angle(lat1, lon1, lat2, lon2)
    points = []
    for index in range(samples):
        fraction = index / (samples - 1)
        if central == 0:
            lat = lat1
            lon = lon1
        else:
            a = math.sin((1.0 - fraction) * central) / math.sin(central)
            b = math.sin(fraction * central) / math.sin(central)
            x = a * math.cos(lat1) * math.cos(lon1) + b * math.cos(lat2) * math.cos(lon2)
            y = a * math.cos(lat1) * math.sin(lon1) + b * math.cos(lat2) * math.sin(lon2)
            z = a * math.sin(lat1) + b * math.sin(lat2)
            lat = math.atan2(z, math.sqrt(x * x + y * y))
            lon = math.atan2(y, x)
        points.append({
            "route_index": index,
            "lat": math.degrees(lat),
            "lon": ((math.degrees(lon) + 540.0) % 360.0) - 180.0,
        })
    route = pd.DataFrame(points)
    route["route_waypoint"] = ""
    if len(route) >= 3:
        mid_index = int(round((len(route) - 1) / 2))
        route.loc[0, "route_waypoint"] = str(transmitter.get("name", "Transmitter"))
        route.loc[mid_index, "route_waypoint"] = "North Atlantic corridor"
        route.loc[len(route) - 1, "route_waypoint"] = str(target.get("name", "Target"))
    distances = [0.0]
    for index in range(1, len(route)):
        previous = route.iloc[index - 1]
        current = route.iloc[index]
        distances.append(
            distances[-1] + haversine_km(previous["lat"], previous["lon"], current["lat"], current["lon"])
        )
    route["distance_km"] = distances
    return route


def sample_route_from_grid(route: pd.DataFrame, grid: pd.DataFrame) -> pd.DataFrame:
    """Attach nearest-grid MUF values to each route point."""
    if route.empty or grid.empty:
        return route.copy()
    required = {"lat", "lon", "quiet_muf_mhz", "storm_muf_mhz"}
    if not required.issubset(grid.columns):
        return route.copy()
    rows = []
    grid_work = grid.copy()
    for _, point in route.iterrows():
        distances = (
            (grid_work["lat"].astype(float) - float(point["lat"])) ** 2
            + (grid_work["lon"].astype(float) - float(point["lon"])) ** 2
        )
        nearest = grid_work.loc[distances.idxmin()]
        row = point.to_dict()
        row.update({
            "nearest_grid_lat": float(nearest["lat"]),
            "nearest_grid_lon": float(nearest["lon"]),
            "quiet_muf_mhz": float(nearest["quiet_muf_mhz"]),
            "storm_muf_mhz": float(nearest["storm_muf_mhz"]),
            "psd_percent": float(nearest.get("psd_percent", 0.0)),
        })
        rows.append(row)
    return pd.DataFrame(rows)


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    """Distance in kilometres between two geographic points."""
    radius_km = 6371.0
    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    dphi = math.radians(float(lat2) - float(lat1))
    dlambda = math.radians(float(lon2) - float(lon1))
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    return 2.0 * radius_km * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))


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
    case["risk_category"] = case["coverage_change"].map(_risk_category_from_coverage)

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
    target: dict | None = None,
    route: Iterable[dict] | None = None,
    title: str | None = None,
    map_mode: str = "change",
) -> object:
    """Create a North Atlantic map for the HF coverage demonstration."""
    import plotly.graph_objects as go

    transmitter = transmitter or DEFAULT_UK_TRANSMITTER
    target = target or TARGET_PRESETS["New York JFK"]
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

    work = case.copy()
    if map_mode == "quiet":
        work["map_category"] = work["quiet_available"].map(
            {True: "Quiet usable", False: "Quiet unusable"}
        )
        colors = {"Quiet usable": "#2E7D32", "Quiet unusable": "#607D8B"}
    elif map_mode == "storm":
        work["map_category"] = work["storm_available"].map(
            {True: "Storm usable", False: "Storm unusable"}
        )
        colors = {"Storm usable": "#2E7D32", "Storm unusable": "#C62828"}
    else:
        work["map_category"] = work["coverage_change"]
        colors = _COVERAGE_COLORS

    for label, color in colors.items():
        subset = work[work["map_category"] == label]
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

    route_line_mode = "lines+markers"
    if "route_waypoint" in route_frame.columns:
        waypoint_text = route_frame["route_waypoint"].fillna("")
    else:
        waypoint_text = route_frame.get("name", route_frame.get("route_index", ""))
    if {"storm_available", "quiet_available"}.issubset(route_frame.columns):
        route_frame = route_frame.copy()
        route_frame["route_degraded"] = (
            route_frame["quiet_available"].astype(bool)
            & ~route_frame["storm_available"].astype(bool)
        )
        degraded = route_frame[route_frame["route_degraded"]]
    else:
        degraded = pd.DataFrame()

    fig.add_trace(
        go.Scattergeo(
            lat=route_frame["lat"],
            lon=route_frame["lon"],
            mode=route_line_mode,
            name="Illustrative UK-North Atlantic-New York route",
            line={"color": "#0D47A1", "width": 2, "dash": "dash"},
            marker={"size": 7, "color": "#0D47A1"},
            text=waypoint_text,
            hovertemplate="route point<br>lat=%{lat:.1f}, lon=%{lon:.1f}<extra></extra>",
        )
    )
    if not degraded.empty:
        fig.add_trace(
            go.Scattergeo(
                lat=degraded["lat"],
                lon=degraded["lon"],
                mode="markers",
                name="Degraded route sample",
                marker={"size": 10, "color": "#D84315", "symbol": "x"},
                hovertemplate="degraded route sample<br>lat=%{lat:.1f}, lon=%{lon:.1f}<extra></extra>",
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
    fig.add_trace(
        go.Scattergeo(
            lat=[float(target["lat"])],
            lon=[float(target["lon"])],
            mode="markers+text",
            name=target["name"],
            text=["Target"],
            textposition="top center",
            marker={"size": 14, "color": "#4A148C", "symbol": "circle"},
            hovertemplate=f"{target['name']}<extra></extra>",
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
        return "Improved during storm"
    return "Unusable in both"


def _risk_category_from_coverage(label: str) -> str:
    if label == "Degraded during storm":
        return "MODERATE"
    if label == "Unusable in both":
        return "SEVERE"
    return "OK"


def _evaluate_grid_for_frequency(grid: pd.DataFrame, frequency: float) -> pd.DataFrame:
    work = grid.copy()
    if work.empty:
        return work
    work["selected_frequency_mhz"] = float(frequency)
    work["quiet_available"] = pd.to_numeric(work["quiet_muf_mhz"], errors="coerce") >= frequency
    work["storm_available"] = pd.to_numeric(work["storm_muf_mhz"], errors="coerce") >= frequency
    work["coverage_change"] = work.apply(_coverage_label, axis=1)
    work["risk_category"] = work["coverage_change"].map(_risk_category_from_coverage)
    return work


def _evaluate_route_for_frequency(route: pd.DataFrame, frequency: float) -> pd.DataFrame:
    work = route.copy()
    if work.empty or not {"quiet_muf_mhz", "storm_muf_mhz"}.issubset(work.columns):
        return work
    work["selected_frequency_mhz"] = float(frequency)
    work["quiet_available"] = pd.to_numeric(work["quiet_muf_mhz"], errors="coerce") >= frequency
    work["storm_available"] = pd.to_numeric(work["storm_muf_mhz"], errors="coerce") >= frequency
    work["coverage_change"] = work.apply(_coverage_label, axis=1)
    work["risk_category"] = work["coverage_change"].map(_risk_category_from_coverage)
    if "distance_km" not in work.columns:
        distances = [0.0]
        for index in range(1, len(work)):
            previous = work.iloc[index - 1]
            current = work.iloc[index]
            distances.append(
                distances[-1] + haversine_km(previous["lat"], previous["lon"], current["lat"], current["lon"])
            )
        work["distance_km"] = distances
    return work


def _engineering_summary(
    grid: pd.DataFrame,
    route: pd.DataFrame,
    frequency: float,
    comparison_mode: str,
) -> dict:
    total_grid = len(grid)
    quiet_grid_count = int(grid["quiet_available"].sum()) if total_grid else 0
    storm_grid_count = int(grid["storm_available"].sum()) if total_grid else 0
    quiet_grid_pct = quiet_grid_count / total_grid * 100.0 if total_grid else 0.0
    storm_grid_pct = storm_grid_count / total_grid * 100.0 if total_grid else 0.0
    regional_loss = max(0.0, quiet_grid_pct - storm_grid_pct)
    relative_reduction = regional_loss / quiet_grid_pct * 100.0 if quiet_grid_pct else 0.0

    total_route = len(route)
    quiet_route_count = int(route["quiet_available"].sum()) if total_route and "quiet_available" in route else 0
    storm_route_count = int(route["storm_available"].sum()) if total_route and "storm_available" in route else 0
    quiet_route_pct = quiet_route_count / total_route * 100.0 if total_route else 0.0
    storm_route_pct = storm_route_count / total_route * 100.0 if total_route else 0.0
    degraded_points = int((route.get("coverage_change", pd.Series(dtype=str)) == "Degraded during storm").sum())
    longest_segment, first_coord, last_coord = _longest_degraded_segment(route)
    return {
        "frequency_mhz": float(frequency),
        "comparison_mode": comparison_mode,
        "total_grid_cells": total_grid,
        "quiet_usable_grid_pct": quiet_grid_pct,
        "storm_usable_grid_pct": storm_grid_pct,
        "regional_coverage_loss_pct_points": regional_loss,
        "relative_regional_reduction_pct": relative_reduction,
        "quiet_route_available_pct": quiet_route_pct,
        "storm_route_available_pct": storm_route_pct,
        "route_coverage_loss_pct_points": max(0.0, quiet_route_pct - storm_route_pct),
        "relative_route_reduction_pct": (
            max(0.0, quiet_route_pct - storm_route_pct) / quiet_route_pct * 100.0
            if quiet_route_pct else 0.0
        ),
        "degraded_route_points": degraded_points,
        "longest_degraded_segment_km": longest_segment,
        "first_degraded_coordinate": first_coord,
        "last_degraded_coordinate": last_coord,
        "route_status": _route_status(storm_route_pct),
        "interpretation": _engineering_interpretation(
            frequency,
            quiet_grid_pct,
            storm_grid_pct,
            quiet_route_pct,
            storm_route_pct,
            longest_segment,
        ),
    }


def _empty_engineering_summary(frequency: float, comparison_mode: str) -> dict:
    return {
        "frequency_mhz": float(frequency),
        "comparison_mode": comparison_mode,
        "total_grid_cells": 0,
        "quiet_usable_grid_pct": 0.0,
        "storm_usable_grid_pct": 0.0,
        "regional_coverage_loss_pct_points": 0.0,
        "relative_regional_reduction_pct": 0.0,
        "quiet_route_available_pct": 0.0,
        "storm_route_available_pct": 0.0,
        "route_coverage_loss_pct_points": 0.0,
        "relative_route_reduction_pct": 0.0,
        "degraded_route_points": 0,
        "longest_degraded_segment_km": 0.0,
        "first_degraded_coordinate": None,
        "last_degraded_coordinate": None,
        "route_status": "unavailable",
        "interpretation": "No spatial MUF3000F2 grid is available. Research prototype only. Not suitable for operational aviation decision-making.",
    }


def _longest_degraded_segment(route: pd.DataFrame) -> tuple[float, tuple[float, float] | None, tuple[float, float] | None]:
    if route.empty or "coverage_change" not in route.columns:
        return 0.0, None, None
    longest = 0.0
    best_first = None
    best_last = None
    current_start = None
    current_end = None
    for index, row in route.reset_index(drop=True).iterrows():
        if row["coverage_change"] == "Degraded during storm":
            if current_start is None:
                current_start = index
            current_end = index
        elif current_start is not None:
            segment, first, last = _segment_distance(route, current_start, current_end)
            if segment > longest:
                longest, best_first, best_last = segment, first, last
            current_start = None
            current_end = None
    if current_start is not None:
        segment, first, last = _segment_distance(route, current_start, current_end)
        if segment > longest:
            longest, best_first, best_last = segment, first, last
    return longest, best_first, best_last


def _segment_distance(route: pd.DataFrame, start: int, end: int) -> tuple[float, tuple[float, float], tuple[float, float]]:
    work = route.reset_index(drop=True)
    first = work.iloc[start]
    last = work.iloc[end]
    if start == end:
        distance = 0.0
    elif "distance_km" in work.columns:
        distance = float(last["distance_km"] - first["distance_km"])
    else:
        distance = haversine_km(first["lat"], first["lon"], last["lat"], last["lon"])
    return distance, (float(first["lat"]), float(first["lon"])), (float(last["lat"]), float(last["lon"]))


def _route_status(storm_route_pct: float) -> str:
    if storm_route_pct >= 99.9:
        return "fully usable"
    if storm_route_pct >= 50.0:
        return "partially degraded"
    return "mostly unavailable"


def _engineering_interpretation(
    frequency: float,
    quiet_grid_pct: float,
    storm_grid_pct: float,
    quiet_route_pct: float,
    storm_route_pct: float,
    longest_segment_km: float,
) -> str:
    return (
        f"At {frequency:.1f} MHz, modelled usable regional coverage decreases "
        f"from {quiet_grid_pct:.0f}% under quiet/background conditions to "
        f"{storm_grid_pct:.0f}% during the selected storm case. Route availability "
        f"decreases from {quiet_route_pct:.0f}% to {storm_route_pct:.0f}%, with "
        f"the longest degraded segment extending approximately {longest_segment_km:.0f} km. "
        "This supports engineering decision support by translating risk categories "
        "into possible HF communication coverage loss and route-level impact. "
        "Research prototype only. Not suitable for operational aviation decision-making."
    )


def _central_angle(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return math.acos(
        min(
            1.0,
            max(
                -1.0,
                math.sin(lat1) * math.sin(lat2)
                + math.cos(lat1) * math.cos(lat2) * math.cos(lon2 - lon1),
            ),
        )
    )


def _psd_series(storm: pd.Series, quiet: pd.Series) -> pd.Series:
    storm_values = pd.to_numeric(storm, errors="coerce")
    quiet_values = pd.to_numeric(quiet, errors="coerce")
    psd = ((quiet_values - storm_values) / quiet_values).clip(lower=0) * 100.0
    psd = psd.where(quiet_values.gt(0))
    return psd
