#!/usr/bin/env python3
"""Standalone hfpytrace proof of concept for a UK to North Atlantic HF path.

This script is intentionally separate from the Streamlit dashboard. It can use
hfpytrace's IRI-backed 2D profile to produce a real ray path, and it includes an
experimental AIDA hook for future work. The AIDA hook is not used by default and
must not be treated as validated until dependency and unit conversions have
been checked.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np


EARTH_RADIUS_KM = 6371.0
DEFAULT_TIME = "2025-01-01T17:55:00Z"
DEFAULT_FREQUENCY_MHZ = 17.5
DEFAULT_ELEVATIONS_DEG = (5, 10, 15, 20, 25, 30, 40, 50, 60)
DEFAULT_TX = {"name": "UK transmitter", "lat": 52.0, "lon": -2.0}
DEFAULT_TARGET = {"name": "North Atlantic point", "lat": 51.0, "lon": -32.0}


@dataclass(frozen=True)
class Route:
    lats: np.ndarray
    lons: np.ndarray
    x_km: np.ndarray
    total_range_km: float


def parse_utc(value: str) -> datetime:
    """Parse an ISO timestamp and return a timezone-aware UTC datetime."""
    cleaned = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(cleaned)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def great_circle_route(
    transmitter: dict,
    target: dict,
    samples: int,
) -> Route:
    """Generate route points and cumulative distance along a great circle."""
    samples = max(int(samples), 2)
    lat1 = math.radians(float(transmitter["lat"]))
    lon1 = math.radians(float(transmitter["lon"]))
    lat2 = math.radians(float(target["lat"]))
    lon2 = math.radians(float(target["lon"]))
    central = _central_angle(lat1, lon1, lat2, lon2)
    total_range_km = EARTH_RADIUS_KM * central

    lats: list[float] = []
    lons: list[float] = []
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
        lats.append(math.degrees(lat))
        lons.append(((math.degrees(lon) + 180.0) % 360.0) - 180.0)

    return Route(
        lats=np.asarray(lats, dtype=float),
        lons=np.asarray(lons, dtype=float),
        x_km=np.linspace(0.0, total_range_km, samples),
        total_range_km=float(total_range_km),
    )


def _central_angle(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    hav = math.sin(dlat / 2.0) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    return 2.0 * math.atan2(math.sqrt(hav), math.sqrt(max(1.0 - hav, 0.0)))


def build_iri_profile(
    event_time: datetime,
    route: Route,
    altitude_step_km: float,
    route_points: int,
):
    """Build an hfpytrace RT2D profile using the package IRI helper."""
    from hfpytrace.model.rt2d import RT2DProfile
    from hfpytrace.utils import load_config_2D

    cfg = load_config_2D(None)
    cfg.event = event_time.isoformat()
    cfg.frequency = DEFAULT_FREQUENCY_MHZ
    cfg.start_height_km = 80.0
    cfg.height_incriment_km = float(altitude_step_km)
    cfg.end_height_km = 500.0
    cfg.number_of_ground_step_km = int(route_points)

    alt_km = np.arange(0.0, 500.0, float(altitude_step_km), dtype=float)
    profile = RT2DProfile(
        alt_km=alt_km,
        lats=route.lats,
        lons=route.lons,
        x_km=route.x_km,
        time=event_time,
    )
    profile.fetch_iri(cfg, workers=1)
    profile.force_zero_density_below(80.0)
    return profile


def build_aida_profile(
    event_time: datetime,
    route: Route,
    altitude_step_km: float,
    hdf5_path: Path,
):
    """Experimental AIDA electron-density adapter.

    This is provided as an integration target, not as a validated dashboard
    feature. It requires an environment where AIDA and hfpytrace can coexist.
    """
    if not hdf5_path.exists():
        raise FileNotFoundError(f"AIDA HDF5 file not found: {hdf5_path}")

    try:
        import aida
        from hfpytrace.model.rt2d import RT2DProfile
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "AIDA backend requires both aida-ionosphere and hfpytrace in one "
            "compatible Python environment. This was not available in the "
            "current local test environment."
        ) from exc

    alt_km = np.arange(0.0, 500.0 + altitude_step_km * 0.5, altitude_step_km, dtype=float)
    state = aida.AIDAState()
    state.readFile(str(hdf5_path))

    # AIDA can calculate Ne when altitude is provided. The exact output axis
    # order must be checked against each AIDA version before dashboard use.
    ne = state.calcNe(
        lat=route.lats,
        lon=route.lons,
        alt=alt_km,
        grid="2D",
    )
    # AIDA calcNe documentation describes the returned values as scaled by
    # 1e11 m^-3. Trace expects electron density in m^-3.
    ne_trace = normalise_ne_shape(ne, len(alt_km), len(route.x_km)) * 1e11

    profile = RT2DProfile(
        alt_km=alt_km,
        lats=route.lats,
        lons=route.lons,
        x_km=route.x_km,
        time=event_time,
    )
    profile.set_electron_density(ne_m3=ne_trace, source="aida")
    return profile


def normalise_ne_shape(ne: np.ndarray, nalt: int, nroute: int) -> np.ndarray:
    """Return electron density shaped as hfpytrace expects: altitude x route."""
    if ne.shape == (nalt, nroute):
        return ne
    if ne.shape == (nroute, nalt):
        return ne.T
    squeezed = np.squeeze(ne)
    if squeezed.shape == (nalt, nroute):
        return squeezed
    if squeezed.shape == (nroute, nalt):
        return squeezed.T
    raise ValueError(
        f"Unexpected AIDA Ne shape {ne.shape}; expected ({nalt}, {nroute}) "
        f"or ({nroute}, {nalt})."
    )


def trace_elevation_sweep(profile, frequency_mhz: float, elevations_deg: Iterable[float], target_range_km: float):
    """Run a fixed-frequency elevation sweep and return ray summaries."""
    from hfpytrace.model.rt2d import RT2D

    tracer = RT2D(profile=profile)
    rays = []
    for elevation in elevations_deg:
        ray = tracer.oblique_trace(
            freq_hz=float(frequency_mhz) * 1e6,
            elevation_deg=float(elevation),
            coordinate_system="spherical",
            z0_km=float(profile.alt_km[0]),
            s_max_km=7000.0,
            max_step_km=2.0,
        )
        x_end = float(np.asarray(ray.x_km)[-1])
        z_end = float(np.asarray(ray.z_km)[-1])
        target_miss = abs(x_end - target_range_km) if str(ray.status) == "ground" else None
        rays.append(
            {
                "elevation_deg": float(elevation),
                "status": str(ray.status),
                "x_end_km": x_end,
                "z_end_km": z_end,
                "x_apex_km": float(ray.x_apex_km),
                "z_apex_km": float(ray.z_apex_km),
                "group_delay_sec": float(ray.group_delay_sec),
                "target_miss_km": target_miss,
                "ray": ray,
            }
        )
    return rays


def select_best_ray(rays: list[dict]) -> dict:
    """Choose the ground-returning ray closest to the target range."""
    ground = [ray for ray in rays if ray["status"] == "ground" and ray["target_miss_km"] is not None]
    if ground:
        return min(ground, key=lambda item: item["target_miss_km"])
    return min(rays, key=lambda item: item["x_end_km"]) if rays else {}


def route_position(route: Route, x_km: float) -> dict:
    """Interpolate lat/lon for a distance along the route."""
    clipped = float(np.clip(x_km, 0.0, route.total_range_km))
    return {
        "lat": float(np.interp(clipped, route.x_km, route.lats)),
        "lon": float(np.interp(clipped, route.x_km, route.lons)),
        "route_distance_km": clipped,
    }


def write_plot(profile, best_ray: dict, output_path: Path) -> None:
    """Write a diagnostic ray-path plot."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ray = best_ray["ray"]
    ne = np.asarray(profile.ne_m3, dtype=float)
    log_ne = np.log10(np.clip(ne, 1.0, None))

    fig, ax = plt.subplots(figsize=(10, 5), constrained_layout=True)
    mesh = ax.pcolormesh(profile.x_km, profile.alt_km, log_ne, shading="auto", cmap="viridis")
    fig.colorbar(mesh, ax=ax, label="log10 electron density (m^-3)")
    ax.plot(ray.x_km, ray.z_km, color="white", linewidth=2.0, label=f"{best_ray['elevation_deg']:.1f} deg ray")
    ax.scatter([ray.x_km[-1]], [ray.z_km[-1]], color="#ffcc00", s=42, label=best_ray["status"])
    ax.set_title("hfpytrace UK to North Atlantic 17.5 MHz POC")
    ax.set_xlabel("Ground range along route (km)")
    ax.set_ylabel("Altitude (km)")
    ax.set_ylim(0, max(float(np.max(profile.alt_km)), float(np.max(ray.z_km))) + 10)
    ax.legend(loc="upper right")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=160)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=["iri", "aida"], default="iri")
    parser.add_argument("--aida-hdf5", type=Path, help="Raw SERENE/AIDA HDF5 state for --backend aida")
    parser.add_argument("--time", default=DEFAULT_TIME)
    parser.add_argument("--frequency-mhz", type=float, default=DEFAULT_FREQUENCY_MHZ)
    parser.add_argument("--route-points", type=int, default=80)
    parser.add_argument("--altitude-step-km", type=float, default=5.0)
    parser.add_argument("--output-dir", type=Path, default=Path("prototypes/output"))
    args = parser.parse_args()

    event_time = parse_utc(args.time)
    route = great_circle_route(DEFAULT_TX, DEFAULT_TARGET, args.route_points)
    if args.backend == "aida":
        if args.aida_hdf5 is None:
            raise SystemExit("--backend aida requires --aida-hdf5")
        profile = build_aida_profile(event_time, route, args.altitude_step_km, args.aida_hdf5)
    else:
        profile = build_iri_profile(event_time, route, args.altitude_step_km, args.route_points)

    rays = trace_elevation_sweep(profile, args.frequency_mhz, DEFAULT_ELEVATIONS_DEG, route.total_range_km)
    best = select_best_ray(rays)
    landing = route_position(route, best["x_end_km"]) if best else None

    args.output_dir.mkdir(parents=True, exist_ok=True)
    plot_path = args.output_dir / "hfpytrace_uk_north_atlantic_ray_path.png"
    json_path = args.output_dir / "hfpytrace_uk_north_atlantic_result.json"
    write_plot(profile, best, plot_path)

    summary = {
        "scientific_guardrail": (
            "This is a standalone hfpytrace proof of concept. IRI backend results "
            "are real ray-tracing outputs, but they are not AIDA PSD ray tracing."
        ),
        "backend": args.backend,
        "time_utc": event_time.isoformat(),
        "frequency_mhz": args.frequency_mhz,
        "transmitter": DEFAULT_TX,
        "target": DEFAULT_TARGET,
        "target_route_range_km": route.total_range_km,
        "propagation_success": bool(best and best["status"] == "ground"),
        "best_ray": {key: value for key, value in best.items() if key != "ray"},
        "landing_point": landing,
        "rays": [{key: value for key, value in ray.items() if key != "ray"} for ray in rays],
        "outputs": {
            "json": str(json_path),
            "plot": str(plot_path),
        },
    }
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
