"""Pure helpers for ICAO-style SERENE risk tables and categorical maps."""

from __future__ import annotations

import math

import pandas as pd


ICAO_COLORS = {
    "OK": "#2E7D32",
    "MODERATE": "#F9A825",
    "SEVERE": "#C62828",
    "UNAVAILABLE": "#95A5A6",
    "N/A": "#9E9E9E",
}

CELL_COLUMNS = [
    "indicator",
    "horizon",
    "display_value",
    "unit",
    "category",
    "color",
    "time",
    "lat",
    "lon",
    "source",
    "threshold_explanation",
    "product_state",
]

SUMMARY_COLUMNS = [
    "Indicator",
    "Latest time UTC",
    "Latest value",
    "Status",
    "Max 3h",
    "Max-3h status",
    "+3h forecast",
    "+3h status",
    "+6h forecast",
    "+6h status",
    "Source",
]

_SUPPORTED_INDICATORS = {"Vertical TEC", "Post-storm depression"}
_SUPPORTED_MAP_HORIZONS = {"Latest", "+3h", "+6h"}


def classify_tec(value):
    """Classify vertical TEC in TECU using the agreed ICAO-style bands."""
    number = _finite_float(value)
    if number is None:
        return "UNAVAILABLE"
    if number < 125:
        return "OK"
    if number < 175:
        return "MODERATE"
    return "SEVERE"


def classify_auroral_absorption(kp):
    """Classify the Kp auroral-absorption proxy."""
    number = _finite_float(kp)
    if number is None:
        return "UNAVAILABLE"
    if number < 8:
        return "OK"
    if number < 9:
        return "MODERATE"
    return "SEVERE"


def classify_kp(kp):
    """Backward-compatible short name for the Kp proxy classifier."""
    return classify_auroral_absorption(kp)


def calculate_psd_percent(current, reference):
    """Return non-negative post-storm depression percentage.

    A missing, non-finite, or non-positive reference has no meaningful
    denominator and therefore returns ``None`` instead of fabricating zero.
    """
    current_number = _finite_float(current)
    reference_number = _finite_float(reference)
    if current_number is None or reference_number is None or reference_number <= 0:
        return None
    return max(0.0, (reference_number - current_number) / reference_number * 100.0)


def classify_psd(value, kp_storm_eligible=False):
    """Classify an already-calculated PSD percentage, gated by recent Kp."""
    number = _finite_float(value)
    if number is None:
        return "UNAVAILABLE"
    if kp_storm_eligible is None:
        return "UNAVAILABLE"
    if not kp_storm_eligible:
        return "OK"
    if number >= 50:
        return "SEVERE"
    if number >= 30:
        return "MODERATE"
    return "OK"


def worst_category(values):
    """Return the most severe recognised category, ignoring unknown values."""
    priority = {"UNAVAILABLE": -1, "OK": 0, "MODERATE": 1, "SEVERE": 2}
    valid = [value for value in values if value in priority]
    return max(valid, key=priority.get) if valid else "UNAVAILABLE"


def build_categorical_cells(
    products, indicator, horizon, kp_storm_eligible=False
):
    """Build point cells for a supported spatial ICAO indicator and horizon.

    Kp and ap are deliberately excluded because they are global indices, not
    geolocated map samples.
    """
    empty = pd.DataFrame(columns=CELL_COLUMNS + ["status"])
    canonical_indicator = _canonical_indicator(indicator)
    canonical_horizon = _canonical_horizon(horizon)
    if (
        canonical_indicator not in _SUPPORTED_INDICATORS
        or canonical_horizon not in _SUPPORTED_MAP_HORIZONS
    ):
        return empty

    frame = _as_frame(products)
    if frame.empty:
        return empty
    frame = _normalise_product_columns(frame)
    if not {"indicator", "horizon", "lat", "lon"}.issubset(frame.columns):
        return empty

    work = frame[
        (frame["indicator"].map(_canonical_indicator) == canonical_indicator)
        & (frame["horizon"].map(_canonical_horizon) == canonical_horizon)
    ].copy()
    if work.empty:
        return empty
    if canonical_horizon == "Latest" and "time" in work.columns:
        parsed_time = pd.to_datetime(work["time"], errors="coerce", utc=True)
        if parsed_time.notna().any():
            work = work[parsed_time == parsed_time.max()].copy()

    work["lat"] = pd.to_numeric(work["lat"], errors="coerce")
    work["lon"] = pd.to_numeric(work["lon"], errors="coerce")
    work = work.dropna(subset=["lat", "lon"])
    if work.empty:
        return empty

    rows = []
    for _, item in work.iterrows():
        if canonical_indicator == "Vertical TEC":
            display_value = _finite_float(item.get("value"))
            category = classify_tec(display_value)
            unit = "TECU"
        else:
            display_value = _psd_value(item)
            category = classify_psd(display_value, kp_storm_eligible)
            unit = "%"
        rows.append({
            "indicator": canonical_indicator,
            "horizon": canonical_horizon,
            "display_value": _na(display_value),
            "unit": unit,
            "category": category,
            "status": category,
            "color": ICAO_COLORS[category],
            "time": item.get("time", pd.NaT),
            "lat": float(item["lat"]),
            "lon": float(item["lon"]),
            "source": _source_value(item.get("source")),
            "threshold_explanation": _threshold_explanation(
                canonical_indicator, kp_storm_eligible
            ),
            "product_state": _product_state(item, canonical_horizon),
        })
    return pd.DataFrame(rows, columns=CELL_COLUMNS + ["status"])


def build_icao_summary(products, indices, eligible=False):
    """Return the fixed ICAO summary table using regional spatial maxima."""
    product_frame = _normalise_product_columns(_as_frame(products))
    rows = [
        _spatial_summary_row(product_frame, "Vertical TEC", eligible),
        _spatial_summary_row(product_frame, "Post-storm depression", eligible),
        _kp_summary_row(_as_frame(indices)),
    ]
    return pd.DataFrame(rows, columns=SUMMARY_COLUMNS)


def unavailable_indicator_rows():
    """List ICAO indicators that cannot currently be derived from SERENE."""
    return pd.DataFrame({
        "Indicator": [
            "Amplitude scintillation S4",
            "Phase scintillation sigma-phi",
            "Polar-cap absorption",
            "Shortwave fadeout",
        ],
        "Availability": ["Not available from SERENE"] * 4,
    })


def _spatial_summary_row(frame, indicator, eligible):
    values = {}
    sources = []
    for horizon in ("Latest", "Max3h", "+3h", "+6h"):
        selected = _regional_max(frame, indicator, horizon)
        values[horizon] = selected
        if selected is not None:
            sources.append(_source_value(selected.get("source")))

    latest = values["Latest"]
    latest_value = _indicator_value(latest, indicator)
    max3 = _indicator_value(values["Max3h"], indicator)
    plus3 = _indicator_value(values["+3h"], indicator)
    plus6 = _indicator_value(values["+6h"], indicator)
    classifier = classify_tec if indicator == "Vertical TEC" else (
        lambda value: classify_psd(value, eligible)
    )
    return {
        "Indicator": indicator,
        "Latest time UTC": _format_utc(latest.get("time")) if latest is not None else "N/A",
        "Latest value": _na(latest_value),
        "Status": classifier(latest_value) if latest_value is not None else "N/A",
        "Max 3h": _na(max3),
        "Max-3h status": classifier(max3) if max3 is not None else "N/A",
        "+3h forecast": _na(plus3),
        "+3h status": classifier(plus3) if plus3 is not None else "N/A",
        "+6h forecast": _na(plus6),
        "+6h status": classifier(plus6) if plus6 is not None else "N/A",
        "Source": ", ".join(dict.fromkeys(sources)) if sources else "N/A",
    }


def _kp_summary_row(frame):
    row = None
    max3_value = None
    if not frame.empty:
        work = frame.copy()
        variable_column = "variable" if "variable" in work.columns else "indicator"
        if variable_column in work.columns and "value" in work.columns:
            work = work[work[variable_column].astype(str).str.casefold() == "kp"].copy()
            work["value"] = pd.to_numeric(work["value"], errors="coerce")
            work = work.dropna(subset=["value"])
            if not work.empty:
                if "time" in work.columns:
                    work["_parsed_time"] = pd.to_datetime(
                        work["time"], errors="coerce", utc=True
                    )
                    row = work.sort_values("_parsed_time", na_position="first").iloc[-1]
                    latest_time = row.get("_parsed_time")
                    if pd.notna(latest_time):
                        window_start = latest_time - pd.Timedelta(hours=3)
                        window = work[
                            work["_parsed_time"].between(
                                window_start, latest_time, inclusive="both"
                            )
                        ]
                        if not window.empty:
                            max3_value = _finite_float(window["value"].max())
                else:
                    row = work.iloc[-1]
    value = _finite_float(row.get("value")) if row is not None else None
    return {
        "Indicator": "Kp auroral absorption proxy",
        "Latest time UTC": _format_utc(row.get("time")) if row is not None else "N/A",
        "Latest value": _na(value),
        "Status": classify_auroral_absorption(value) if value is not None else "N/A",
        "Max 3h": _na(max3_value),
        "Max-3h status": (
            classify_auroral_absorption(max3_value)
            if max3_value is not None else "N/A"
        ),
        "+3h forecast": "N/A",
        "+3h status": "N/A",
        "+6h forecast": "N/A",
        "+6h status": "N/A",
        "Source": _source_value(row.get("source")) if row is not None else "N/A",
    }


def _regional_max(frame, indicator, horizon):
    if frame.empty or not {"indicator", "horizon"}.issubset(frame.columns):
        return None
    work = frame[
        (frame["indicator"].map(_canonical_indicator) == indicator)
        & (frame["horizon"].map(_canonical_horizon) == horizon)
    ].copy()
    if work.empty:
        return None
    if horizon == "Latest" and "time" in work.columns:
        parsed_time = pd.to_datetime(work["time"], errors="coerce", utc=True)
        if parsed_time.notna().any():
            work = work[parsed_time == parsed_time.max()].copy()
    work["_risk_value"] = work.apply(
        lambda row: _indicator_value(row, indicator), axis=1
    )
    work["_risk_value"] = pd.to_numeric(work["_risk_value"], errors="coerce")
    work = work.dropna(subset=["_risk_value"])
    if work.empty:
        return None
    return work.loc[work["_risk_value"].idxmax()]


def _indicator_value(row, indicator):
    if row is None:
        return None
    if indicator == "Post-storm depression":
        return _psd_value(row)
    return _finite_float(row.get("value"))


def _psd_value(row):
    if "psd_percent" in row:
        return _finite_float(row.get("psd_percent"))
    for column in ("display_value", "value"):
        if column in row and pd.notna(row.get(column)):
            return _finite_float(row.get(column))
    if "current" in row and "reference" in row:
        return calculate_psd_percent(row.get("current"), row.get("reference"))
    return None


def _normalise_product_columns(frame):
    if frame.empty:
        return frame.copy()
    work = frame.copy()
    if "indicator" not in work.columns and "variable" in work.columns:
        variable_names = work["variable"].astype(str)
        work["indicator"] = variable_names.map({
            "TEC": "Vertical TEC",
            "vTEC": "Vertical TEC",
            "MUF3000F2": "Post-storm depression",
            "MUF3000": "Post-storm depression",
        }).fillna(variable_names)
    if "horizon" not in work.columns:
        if "product_kind" in work.columns:
            product_kinds = work["product_kind"].astype(str)
            work["horizon"] = product_kinds.map({
                "analysis": "Latest",
                "rolling": "Max3h",
                "forecast_180": "+3h",
                "forecast_360": "+6h",
            }).fillna(product_kinds)
        else:
            work["horizon"] = "Latest"
    return work


def _canonical_indicator(value):
    text = str(value).strip().casefold()
    if text in {"vertical tec", "tec", "vtec"}:
        return "Vertical TEC"
    if text in {"post-storm depression", "post storm depression", "psd"}:
        return "Post-storm depression"
    return str(value).strip()


def _canonical_horizon(value):
    text = str(value).strip().casefold().replace(" ", "")
    aliases = {
        "latest": "Latest",
        "now": "Latest",
        "max3h": "Max3h",
        "+3h": "+3h",
        "+6h": "+6h",
    }
    return aliases.get(text, str(value).strip())


def _as_frame(value):
    if isinstance(value, pd.DataFrame):
        return value.copy()
    if value is None:
        return pd.DataFrame()
    try:
        return pd.DataFrame(value)
    except (TypeError, ValueError):
        return pd.DataFrame()


def _finite_float(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _format_utc(value):
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        return "N/A"
    return parsed.strftime("%Y-%m-%d %H:%M UTC")


def _source_value(value):
    if value is None or pd.isna(value) or not str(value).strip():
        return "SERENE"
    return str(value)


def _threshold_explanation(indicator, kp_storm_eligible):
    if indicator == "Vertical TEC":
        return "OK <125 TECU; MODERATE 125 to <175 TECU; SEVERE >=175 TECU"
    if kp_storm_eligible is None:
        gate = "eligibility unavailable"
    else:
        gate = "eligible" if kp_storm_eligible else "not eligible"
    return (
        "Requires Kp >=6 in prior 96h "
        f"({gate}); OK <30%; MODERATE 30 to <50%; SEVERE >=50%"
    )


def _product_state(item, horizon):
    product_kind = str(item.get("product_kind", "")).strip().casefold()
    if product_kind.startswith("forecast_") or horizon in {"+3h", "+6h"}:
        return "official forecast"
    return "analysis"


def _na(value):
    return "N/A" if value is None else value
