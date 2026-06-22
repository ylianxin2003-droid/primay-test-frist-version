"""
Prototype ICAO-style risk alert engine.

Generates advisory messages based on ionospheric variable thresholds.
These are **academic prototype advisories** and NOT official ICAO warnings.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# ── Thresholds ──────────────────────────────────────────────────────────────
# These are illustrative academic thresholds informed by published literature
# (e.g. ICAO Doc 10100, PECASUS / SWPC advisories).  They should be tuned
# against operational feedback before any real-world use.

THRESHOLDS: dict[str, dict[str, list[float]]] = {
    # TEC (TECU)
    #   Normal < 50, Watch 50-80, Warning 80-120, Severe >= 120
    "TEC": {
        "levels": [50, 80, 120],  # [Watch, Warning, Severe] lower bounds
        "risk_label": "GNSS positioning risk",
        "unit": "TECU",
    },
    # MUF3000 depression from reference (fraction, e.g. -0.3 = 30% depressed)
    #   Normal > -0.2, Watch -0.2 to -0.4, Warning -0.4 to -0.6, Severe <= -0.6
    "MUF3000_depression": {
        "levels": [-0.4, -0.6, -0.8],  # Watch, Warning, Severe (as fraction)
        "risk_label": "HF communication risk",
        "unit": "fraction",
    },
    # foF2 depression (MHz depression below median)
    #   Normal > -1, Watch -1 to -2, Warning -2 to -4, Severe <= -4
    "foF2_depression": {
        "levels": [-1.0, -2.0, -4.0],
        "risk_label": "HF communication risk",
        "unit": "MHz",
    },
    # Generic ionospheric disturbance flag
    "ionospheric_disturbance": {
        "levels": [1, 2, 3],  # discrete levels
        "risk_label": "General ionospheric disturbance",
        "unit": "index",
    },
    # NOAA G-scale style geomagnetic storm proxy from planetary Kp.
    # Normal < 5, then G1/G2/G3/G4/G5 from Kp 5/6/7/8/9.
    "Kp": {
        "levels": [5, 6, 7, 8, 9],
        "risk_label": "Geomagnetic storm risk",
        "unit": "Kp",
    },
    # ap roughly maps to G levels: 48/80/132/207/400.
    "ap": {
        "levels": [48, 80, 132, 207, 400],
        "risk_label": "Geomagnetic storm risk",
        "unit": "ap",
    },
}

RISK_LEVELS = [
    "Normal", "Watch", "Warning", "Severe",
    "G1 Minor", "G2 Moderate", "G3 Strong", "G4 Severe", "G5 Extreme",
]

# ── Impact / interpretation templates ───────────────────────────────────────

IMPACT_TEMPLATES: dict[str, dict[str, tuple[str, str]]] = {
    "GNSS positioning risk": {
        "Normal": (
            "Nominal GNSS positioning accuracy expected.",
            "No significant ionospheric impact on GNSS signals detected in this region.",
        ),
        "Watch": (
            "Possible degradation of single-frequency GNSS positioning accuracy.",
            "Enhanced TEC values may increase GNSS range errors by several metres. "
            "Augmentation systems (SBAS/GBAS) should be monitored.",
        ),
        "Warning": (
            "Significant GNSS positioning errors possible, especially at low elevation angles.",
            "Dual-frequency receivers recommended. Range errors may exceed operational "
            "limits for precision approaches without augmentation.",
        ),
        "Severe": (
            "Severe GNSS degradation expected. Positioning may be unreliable.",
            "Ionospheric scintillation and large TEC gradients may cause loss of lock, "
            "cycle slips, and metre-level range errors even for dual-frequency receivers.",
        ),
    },
    "HF communication risk": {
        "Normal": (
            "Nominal HF communication expected on typical aeronautical frequencies.",
            "No significant ionospheric depression detected in this region.",
        ),
        "Watch": (
            "Mild depression of F2-layer critical frequency. Some HF frequencies may be affected.",
            "Operators should verify backup frequencies. Lower bands may become less reliable.",
        ),
        "Warning": (
            "Significant MUF depression expected. HF communication may be unreliable on many frequencies.",
            "Consider alternative communication methods (SATCOM, CPDLC). "
            "Monitor VOLMET broadcasts for updated propagation forecasts.",
        ),
        "Severe": (
            "Severe MUF depression. HF communication likely unavailable on most or all aeronautical bands.",
            "HF blackout conditions possible. Reliance on SATCOM / data link strongly advised. "
            "Flight crews should expect loss of HF contact and plan accordingly.",
        ),
    },
    "General ionospheric disturbance": {
        "Normal": (
            "No significant ionospheric disturbance detected.",
            "Quiet ionospheric conditions. Aviation operations nominal.",
        ),
        "Watch": (
            "Moderate ionospheric disturbance possible in this region.",
            "Monitor space weather advisories. Some impact on GNSS and HF possible.",
        ),
        "Warning": (
            "Strong ionospheric disturbance occurring or imminent.",
            "Expect degraded GNSS and HF performance across the region. "
            "Flight planning should account for potential communication and navigation issues.",
        ),
        "Severe": (
            "Extreme ionospheric storm conditions.",
            "All ionosphere-dependent aviation systems may be severely impacted. "
            "Consider operational restrictions per airline space weather procedures.",
        ),
    },
    "Geomagnetic storm risk": {
        "Normal": (
            "No significant geomagnetic storm conditions detected.",
            "Kp/ap values are below storm thresholds for this selected period.",
        ),
        "Watch": (
            "Minor to moderate geomagnetic storm conditions possible.",
            "Monitor GNSS and HF performance, especially on polar and high-latitude routes.",
        ),
        "Warning": (
            "Strong geomagnetic storm conditions likely.",
            "GNSS accuracy, scintillation risk, and HF propagation may be degraded.",
        ),
        "Severe": (
            "Severe to extreme geomagnetic storm conditions indicated.",
            "Expect elevated risk to GNSS and HF communication services; use operational backups.",
        ),
        "G1 Minor": (
            "Minor geomagnetic storm conditions indicated.",
            "Possible weak power grid fluctuations and minor HF/GNSS impacts at high latitudes.",
        ),
        "G2 Moderate": (
            "Moderate geomagnetic storm conditions indicated.",
            "HF propagation and GNSS performance may be degraded, especially at high latitudes.",
        ),
        "G3 Strong": (
            "Strong geomagnetic storm conditions indicated.",
            "GNSS accuracy, scintillation risk, and HF propagation may be degraded.",
        ),
        "G4 Severe": (
            "Severe geomagnetic storm conditions indicated.",
            "Elevated risk to GNSS and HF communication services; use operational backups.",
        ),
        "G5 Extreme": (
            "Extreme geomagnetic storm conditions indicated.",
            "Major GNSS/HF disruption is possible; operational backups and space weather procedures should be considered.",
        ),
    },
}

DISCLAIMER = (
    "This is a prototype academic advisory generated by an automated research system. "
    "It is NOT an official ICAO warning and must NOT be used for operational "
    "aviation decision-making."
)


# ── Public API ─────────────────────────────────────────────────────────────


def generate_alerts(df: pd.DataFrame) -> pd.DataFrame:
    """Generate prototype ICAO-style risk alerts from a standardised DataFrame.

    Expects a DataFrame with columns: ``time, lat, lon, variable, value, model``.

    Returns a DataFrame with columns:
        timestamp, region, alert_type, risk_level, value, threshold_info,
        reason, possible_aviation_impact, interpretation, disclaimer

    An empty DataFrame is returned if the input contains no data.
    """
    if df.empty:
        logger.info("Empty DataFrame passed to generate_alerts — no alerts generated.")
        return pd.DataFrame()

    alerts: list[dict[str, Any]] = []

    # Determine which variables in the data map to our threshold tables.
    for variable_name in df["variable"].unique():
        threshold_info = _find_threshold(variable_name)
        if threshold_info is None:
            continue

        var_df = df[df["variable"] == variable_name].copy()
        if var_df.empty:
            continue

        levels = threshold_info["levels"]
        negative_scale = all(l <= 0 for l in levels)

        # One advisory per geographic band (fast; avoids 10k+ row iteration).
        if "lat" in var_df.columns and "lon" in var_df.columns:
            var_df["_region"] = var_df.apply(
                lambda r: _region_label(r.get("lat"), r.get("lon")), axis=1,
            )
            groups = var_df.groupby("_region", sort=False)
        else:
            var_df["_region"] = "Global"
            groups = var_df.groupby("_region", sort=False)

        for _region_name, grp in groups:
            values = pd.to_numeric(grp["value"], errors="coerce").dropna()
            if values.empty:
                continue

            if negative_scale:
                extreme_idx = values.idxmin()
            else:
                extreme_idx = values.idxmax()

            row = grp.loc[extreme_idx]
            value = float(row["value"])
            risk_level = _classify_variable_risk(variable_name, value, levels)
            if risk_level == "Normal":
                continue

            alert_type = threshold_info["risk_label"]
            impacts = IMPACT_TEMPLATES.get(alert_type, {}).get(
                risk_level,
                ("Potential impact on aviation operations.", "Consult space weather advisories."),
            )
            region_label = row.get("_region", "Global")

            alerts.append({
                "timestamp": row.get("time", "unknown"),
                "region": region_label,
                "alert_type": alert_type,
                "risk_level": risk_level,
                "value": value,
                "threshold_info": _describe_threshold(
                    variable_name, levels, value, threshold_info["unit"]
                ),
                "reason": _describe_threshold(
                    variable_name, levels, value, threshold_info["unit"]
                ),
                "possible_aviation_impact": impacts[0],
                "interpretation": impacts[1],
                "disclaimer": DISCLAIMER,
            })

    if not alerts:
        logger.info("No alerts generated — all variables within Normal range.")
        return pd.DataFrame()

    alerts = _merge_geomagnetic_alerts(alerts)
    alerts_df = pd.DataFrame(alerts)
    alerts_df = alerts_df.sort_values("risk_level", key=lambda s: s.map(_risk_priority()))
    return alerts_df.reset_index(drop=True)


def generate_overall_risk(alerts: pd.DataFrame) -> tuple[str, str]:
    """Summarise the highest risk level across all generated alerts.

    Returns:
        ``(highest_risk: str, summary_message: str)``
    """
    if alerts.empty:
        return "Normal", "All monitored parameters are within normal ranges."

    if "risk_level" not in alerts.columns:
        return "Unknown", "Unable to determine risk level from alert data."

    priority = _risk_priority()
    alert_risks = alerts["risk_level"].map(priority).fillna(3)
    worst_idx = alert_risks.idxmin() if not alert_risks.empty else None

    if worst_idx is None or (isinstance(worst_idx, float) and pd.isna(worst_idx)):
        return "Normal", "All monitored parameters are within normal ranges."

    worst = alerts.iloc[worst_idx]
    worst_level = worst["risk_level"]

    count_by_type = alerts["alert_type"].value_counts().to_dict() if "alert_type" in alerts.columns else {}
    parts = [f"{count} {typ}(s)" for typ, count in count_by_type.items()]
    type_summary = "; ".join(parts) if parts else "various types"

    summary = (
        f"Loaded-sample peak risk: {worst_level}. {len(alerts)} prototype advisor"
        f"{'y' if len(alerts) == 1 else 'ies'} generated: {type_summary}."
    )

    return worst_level, summary


# ── Internal helpers ────────────────────────────────────────────────────────


def _merge_geomagnetic_alerts(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Combine Kp and ap evidence because both describe one global storm."""
    geomagnetic = [
        alert for alert in alerts
        if alert.get("alert_type") == "Geomagnetic storm risk"
    ]
    if len(geomagnetic) <= 1:
        return alerts

    priority = _risk_priority()
    worst = min(
        geomagnetic,
        key=lambda alert: priority.get(str(alert.get("risk_level")), 99),
    ).copy()
    evidence = "; ".join(str(alert.get("reason", "")) for alert in geomagnetic)
    worst["reason"] = f"Combined global geomagnetic evidence: {evidence}"
    worst["threshold_info"] = worst["reason"]
    worst["interpretation"] = (
        f"{worst.get('interpretation', '')} Kp and ap are combined because they "
        "describe the same planetary geomagnetic event."
    ).strip()

    non_geomagnetic = [
        alert for alert in alerts
        if alert.get("alert_type") != "Geomagnetic storm risk"
    ]
    return non_geomagnetic + [worst]


def _find_threshold(variable_name: str) -> dict[str, Any] | None:
    """Match a variable name to its threshold definition."""
    # Direct match
    if variable_name in THRESHOLDS:
        return THRESHOLDS[variable_name]

    # Case-insensitive
    name_lower = variable_name.lower()
    for key, info in THRESHOLDS.items():
        if key.lower() == name_lower:
            return info

    # Partial match for known patterns
    if "tec" in name_lower and "dep" not in name_lower:
        return THRESHOLDS.get("TEC")
    if "muf" in name_lower and "dep" in name_lower:
        return THRESHOLDS.get("MUF3000_depression")
    if "fof2" in name_lower and "dep" in name_lower:
        return THRESHOLDS.get("foF2_depression")
    if "disturb" in name_lower:
        return THRESHOLDS.get("ionospheric_disturbance")
    if name_lower == "kp":
        return THRESHOLDS.get("Kp")
    if name_lower == "ap":
        return THRESHOLDS.get("ap")

    return None


def _classify_risk(value: float, levels: list[float]) -> str:
    """Classify a numeric value into a risk level.

    ``levels`` is ``[Watch_lower, Warning_lower, Severe_lower]``.
    For positive-scaling variables (e.g. TEC) the intervals are:
        Normal: value < levels[0]
        Watch:  levels[0] <= value < levels[1]
        Warning: levels[1] <= value < levels[2]
        Severe: value >= levels[2]

    For negative-scaling (depression) variables where the thresholds are
    all non-positive, we treat smaller (more negative) as worse.
    """
    all_non_positive = all(l <= 0 for l in levels)

    if not all_non_positive:
        # Positive scaling — higher = worse
        if value < levels[0]:
            return "Normal"
        if value < levels[1]:
            return "Watch"
        if value < levels[2]:
            return "Warning"
        return "Severe"

    # Negative scaling — more negative = worse
    if value > levels[0]:
        return "Normal"
    if value > levels[1]:
        return "Watch"
    if value > levels[2]:
        return "Warning"
    return "Severe"


def _classify_variable_risk(variable_name: str, value: float, levels: list[float]) -> str:
    if variable_name.lower() in ("kp", "ap"):
        return _classify_geomagnetic_risk(value, levels)
    return _classify_risk(value, levels)


def _classify_geomagnetic_risk(value: float, levels: list[float]) -> str:
    labels = ["G1 Minor", "G2 Moderate", "G3 Strong", "G4 Severe", "G5 Extreme"]
    if value < levels[0]:
        return "Normal"
    risk = labels[0]
    for threshold, label in zip(levels, labels):
        if value >= threshold:
            risk = label
    return risk


def _risk_priority() -> dict[str, int]:
    return {
        "G5 Extreme": 0,
        "G4 Severe": 1,
        "Severe": 2,
        "G3 Strong": 3,
        "Warning": 4,
        "G2 Moderate": 5,
        "G1 Minor": 6,
        "Watch": 7,
        "Normal": 8,
    }


def _describe_threshold(
    variable_name: str,
    levels: list[float],
    value: float,
    unit: str,
) -> str:
    """Produce a human-readable description of the threshold crossing."""
    risk = _classify_variable_risk(variable_name, value, levels)
    return (
        f"{variable_name} = {value:.2f} {unit} (threshold: {risk.lower()}, "
        f"bounds: {levels})"
    )


def _region_label(lat: Any, lon: Any) -> str:
    """Create a human-readable region label from lat/lon."""
    if lat is None or lon is None or pd.isna(lat) or pd.isna(lon):
        return "Global"
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (ValueError, TypeError):
        return "Unknown region"

    lat_band = (
        "High-lat N" if lat_f > 60 else
        "Mid-lat N" if lat_f > 30 else
        "Eq" if lat_f >= -30 else
        "Mid-lat S" if lat_f >= -60 else
        "High-lat S"
    )
    lon_band = (
        "Americas" if -120 <= lon_f <= -30 else
        "Europe/Africa" if -30 <= lon_f <= 60 else
        "Asia-Pacific" if 60 <= lon_f <= 180 else
        "Pacific" if -180 <= lon_f < -120 else
        "Unknown"
    )
    return f"{lat_band} / {lon_band}"
