"""Short-horizon aviation space-weather risk forecasting.

The functions in this module turn live SERENE API samples into a weather-style
forecast product. They do not persist data; every forecast is derived from the
DataFrame currently held in the Streamlit session after an API refresh.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from alert_engine import THRESHOLDS, _classify_variable_risk, _find_threshold


FORECAST_HORIZONS: tuple[tuple[str, int], ...] = (
    ("Now", 0),
    ("+1h", 1),
    ("+3h", 3),
    ("+6h", 6),
)

FORECAST_RISK_COLORS: dict[str, str] = {
    "Normal": "#2ecc71",
    "Watch": "#f1c40f",
    "Warning": "#e67e22",
    "Severe": "#e74c3c",
}


def generate_risk_forecast(df: pd.DataFrame) -> pd.DataFrame:
    """Create point-level risk forecasts for all mappable SERENE variables.

    Returns columns suitable for map and table display:
    ``horizon, horizon_hours, lat, lon, risk_level, risk_probability,
    risk_score, confidence, driver, predicted_value, explanation``.
    """
    if df.empty or "variable" not in df.columns or "value" not in df.columns:
        return pd.DataFrame()

    work = df.copy()
    work["value"] = pd.to_numeric(work["value"], errors="coerce")
    if "time" in work.columns:
        work["time"] = pd.to_datetime(work["time"], errors="coerce", utc=True)
    else:
        work["time"] = pd.NaT

    global_baseline = _global_geomagnetic_baseline(work)
    point_forecasts = _point_variable_forecasts(work)
    if not point_forecasts:
        return pd.DataFrame()

    forecast = pd.DataFrame(point_forecasts)
    if global_baseline:
        forecast = _apply_global_baseline(forecast, global_baseline)

    forecast = forecast.sort_values(
        ["horizon_hours", "risk_score", "risk_probability"],
        ascending=[True, False, False],
    )
    return forecast.reset_index(drop=True)


def aggregate_forecast_for_map(forecast: pd.DataFrame, horizon: str = "Now") -> pd.DataFrame:
    """Collapse variable-level forecasts to the highest-risk map cell."""
    if forecast.empty:
        return pd.DataFrame()

    work = forecast[forecast["horizon"] == horizon].copy()
    if work.empty:
        return pd.DataFrame()

    for col in ("lat", "lon", "risk_score", "risk_probability", "confidence"):
        work[col] = pd.to_numeric(work[col], errors="coerce")
    work = work.dropna(subset=["lat", "lon", "risk_score"])
    if work.empty:
        return pd.DataFrame()

    idx = work.groupby(["lat", "lon"], sort=False)["risk_score"].idxmax()
    mapped = work.loc[idx].copy()
    mapped["marker_size"] = 8 + (mapped["risk_probability"].clip(0, 1) * 22)
    mapped["risk_probability_pct"] = (mapped["risk_probability"] * 100).round(1)
    mapped["confidence_pct"] = (mapped["confidence"] * 100).round(1)
    return mapped.reset_index(drop=True)


def forecast_summary(forecast: pd.DataFrame) -> tuple[str, str]:
    """Return highest forecast risk and a concise explanation."""
    if forecast.empty:
        return "Normal", "No mappable API samples are available for forecast risk scoring."

    priority = {"Severe": 0, "Warning": 1, "Watch": 2, "Normal": 3}
    scores = forecast["risk_level"].map(priority).fillna(3)
    worst = forecast.loc[scores.idxmin()]
    severe_count = int((forecast["risk_level"] == "Severe").sum())
    warning_count = int((forecast["risk_level"] == "Warning").sum())
    watch_count = int((forecast["risk_level"] == "Watch").sum())
    message = (
        f"Forecast highest risk is {worst['risk_level']} at {worst['horizon']} "
        f"near {float(worst['lat']):.1f}, {float(worst['lon']):.1f}. "
        f"Cells: {severe_count} severe, {warning_count} warning, {watch_count} watch."
    )
    return str(worst["risk_level"]), message


def _point_variable_forecasts(work: pd.DataFrame) -> list[dict[str, Any]]:
    if "lat" not in work.columns or "lon" not in work.columns:
        return []

    spatial = work.copy()
    spatial["lat"] = pd.to_numeric(spatial["lat"], errors="coerce")
    spatial["lon"] = pd.to_numeric(spatial["lon"], errors="coerce")
    spatial = spatial.dropna(subset=["lat", "lon", "value"])
    if spatial.empty:
        return []

    rows: list[dict[str, Any]] = []
    grouped = spatial.groupby(["lat", "lon", "variable"], sort=False)
    for (lat, lon, variable), grp in grouped:
        threshold = _find_threshold(str(variable))
        if threshold is None:
            continue

        grp = grp.sort_values("time")
        latest = grp.iloc[-1]
        latest_value = float(latest["value"])
        slope_per_hour = _estimate_slope_per_hour(grp)
        confidence_base = _confidence_from_samples(grp)

        for horizon, hours in FORECAST_HORIZONS:
            predicted = latest_value + slope_per_hour * hours
            risk_level = _normalise_map_risk(
                _classify_variable_risk(str(variable), predicted, threshold["levels"])
            )
            risk_score = _risk_score(str(variable), predicted, threshold["levels"])
            probability = _risk_probability(risk_score, hours, slope_per_hour, threshold["levels"])
            confidence = max(0.2, confidence_base - hours * 0.04)
            rows.append({
                "horizon": horizon,
                "horizon_hours": hours,
                "time": latest.get("time", pd.NaT),
                "lat": float(lat),
                "lon": float(lon),
                "variable": str(variable),
                "driver": str(variable),
                "observed_value": latest_value,
                "predicted_value": float(predicted),
                "risk_level": risk_level,
                "risk_score": round(float(risk_score), 2),
                "risk_probability": round(float(probability), 3),
                "confidence": round(float(confidence), 3),
                "explanation": _explain_forecast(
                    str(variable), predicted, risk_level, probability, confidence
                ),
            })

    return rows


def _global_geomagnetic_baseline(work: pd.DataFrame) -> dict[str, Any] | None:
    global_rows = work[work["variable"].isin(["Kp", "ap"])].dropna(subset=["value"])
    if global_rows.empty:
        return None

    candidates: list[dict[str, Any]] = []
    for variable, grp in global_rows.groupby("variable", sort=False):
        threshold = THRESHOLDS.get(str(variable))
        if threshold is None:
            continue
        latest = grp.sort_values("time").iloc[-1]
        value = float(latest["value"])
        score = _risk_score(str(variable), value, threshold["levels"])
        candidates.append({
            "variable": str(variable),
            "value": value,
            "risk_score": score,
            "risk_level": _normalise_map_risk(
                _classify_variable_risk(str(variable), value, threshold["levels"])
            ),
        })

    if not candidates:
        return None
    return max(candidates, key=lambda row: row["risk_score"])


def _apply_global_baseline(forecast: pd.DataFrame, baseline: dict[str, Any]) -> pd.DataFrame:
    out = forecast.copy()
    baseline_score = float(baseline["risk_score"])
    stronger = baseline_score > out["risk_score"]
    out.loc[stronger, "risk_score"] = baseline_score
    out.loc[stronger, "risk_level"] = baseline["risk_level"]
    out.loc[stronger, "driver"] = f"{baseline['variable']} global storm baseline"
    out.loc[stronger, "risk_probability"] = np.maximum(
        out.loc[stronger, "risk_probability"],
        _risk_probability(baseline_score, 0, 0.0, THRESHOLDS[str(baseline["variable"])]["levels"]),
    )
    out.loc[stronger, "explanation"] = (
        f"Global {baseline['variable']}={baseline['value']:.2f} raises the regional "
        f"storm baseline to {baseline['risk_level']}."
    )
    return out


def _estimate_slope_per_hour(grp: pd.DataFrame) -> float:
    timed = grp.dropna(subset=["time", "value"]).copy()
    if len(timed) < 2:
        return 0.0

    latest_time = timed["time"].max()
    hours = (timed["time"] - latest_time).dt.total_seconds() / 3600.0
    values = pd.to_numeric(timed["value"], errors="coerce")
    valid = hours.notna() & values.notna()
    if valid.sum() < 2 or hours[valid].nunique() < 2:
        return 0.0

    slope, _intercept = np.polyfit(hours[valid], values[valid], 1)
    return float(np.clip(slope, -50.0, 50.0))


def _confidence_from_samples(grp: pd.DataFrame) -> float:
    sample_count = len(grp)
    has_time_series = grp["time"].notna().sum() >= 2 if "time" in grp.columns else False
    confidence = 0.55 + min(sample_count, 10) * 0.025
    if has_time_series:
        confidence += 0.15
    return min(confidence, 0.9)


def _risk_score(variable: str, value: float, levels: list[float]) -> float:
    if variable.lower() in ("kp", "ap"):
        if value < levels[0]:
            return max(0.0, 20.0 * value / max(levels[0], 1))
        for idx, threshold in enumerate(levels):
            if value < threshold:
                lower = levels[idx - 1]
                span = max(threshold - lower, 1e-9)
                return 20.0 + idx * 16.0 + (value - lower) / span * 16.0
        return 100.0

    negative_scale = all(level <= 0 for level in levels)
    if negative_scale:
        converted = -value
        converted_levels = [-level for level in levels]
        return _positive_risk_score(converted, converted_levels)
    return _positive_risk_score(value, levels)


def _positive_risk_score(value: float, levels: list[float]) -> float:
    watch, warning, severe = levels[:3]
    if value < watch:
        return max(0.0, 35.0 * value / max(watch, 1e-9))
    if value < warning:
        return 35.0 + (value - watch) / max(warning - watch, 1e-9) * 25.0
    if value < severe:
        return 60.0 + (value - warning) / max(severe - warning, 1e-9) * 25.0
    return min(100.0, 85.0 + (value - severe) / max(abs(severe), 1.0) * 15.0)


def _risk_probability(
    risk_score: float,
    horizon_hours: int,
    slope_per_hour: float,
    levels: list[float],
) -> float:
    trend_bonus = min(abs(slope_per_hour) / max(abs(levels[0]), 1.0), 0.15)
    horizon_uncertainty = min(horizon_hours * 0.015, 0.08)
    probability = risk_score / 100.0 + trend_bonus - horizon_uncertainty
    return float(np.clip(probability, 0.02, 0.98))


def _normalise_map_risk(risk: str) -> str:
    if risk in {"G4 Severe", "G5 Extreme", "Severe"}:
        return "Severe"
    if risk in {"G3 Strong", "Warning"}:
        return "Warning"
    if risk in {"G1 Minor", "G2 Moderate", "Watch"}:
        return "Watch"
    return "Normal"


def _explain_forecast(
    variable: str,
    predicted: float,
    risk_level: str,
    probability: float,
    confidence: float,
) -> str:
    return (
        f"{variable} forecast value {predicted:.2f} gives {risk_level} risk "
        f"with {probability * 100:.1f}% probability "
        f"and {confidence * 100:.1f}% confidence."
    )
