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
    "Domain",
    "Indicator",
    "Moderate threshold",
    "Severe threshold",
    "Time UTC",
    "Latest value",
    "Status",
    "Alert",
    "Max-3h value",
    "Max-3h status",
    "+3h forecast",
    "+3h status",
    "+6h forecast",
    "+6h status",
    "Forecast source",
    "Source / Availability",
]

_SUPPORTED_INDICATORS = {"Vertical TEC", "Post-Storm Depression"}
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

    work = _rows_for_indicator_horizon(frame, canonical_indicator, canonical_horizon)
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
    """Return a PECASUS-style table with available and unavailable indicators."""
    product_frame = _normalise_product_columns(_as_frame(products))
    rows = [
        _unavailable_summary_row(
            "GNSS",
            "Amplitude Scintillation",
            "S4 >= 0.5",
            "S4 >= 0.8",
            "Not available from SERENE AIDA/Kp-ap inputs",
        ),
        _unavailable_summary_row(
            "GNSS",
            "Phase Scintillation",
            "sigma-phi >= 0.4",
            "sigma-phi >= 0.7",
            "Not available from SERENE AIDA/Kp-ap inputs",
        ),
        _spatial_summary_row(product_frame, "GNSS", "Vertical TEC", eligible),
        _kp_summary_row(_as_frame(indices)),
        _unavailable_summary_row(
            "HF COM",
            "Polar Cap Absorption",
            "PCA >= 2 dB",
            "PCA >= 5 dB",
            "Not available from SERENE AIDA/Kp-ap inputs",
        ),
        _unavailable_summary_row(
            "HF COM",
            "Shortwave Fadeout",
            "X-ray class >= X1",
            "X-ray class >= X10",
            "Not available from SERENE AIDA/Kp-ap inputs",
        ),
        _spatial_summary_row(product_frame, "HF COM", "Post-Storm Depression", eligible),
        _unavailable_summary_row(
            "Radiation",
            "Effective Dose FL <= 460",
            "Dose-rate threshold not supplied by SERENE",
            "Dose-rate threshold not supplied by SERENE",
            "Not available from SERENE AIDA/Kp-ap inputs",
        ),
        _unavailable_summary_row(
            "Radiation",
            "Effective Dose FL > 460",
            "Dose-rate threshold not supplied by SERENE",
            "Dose-rate threshold not supplied by SERENE",
            "Not available from SERENE AIDA/Kp-ap inputs",
        ),
    ]
    return pd.DataFrame(rows, columns=SUMMARY_COLUMNS)


def unavailable_indicator_rows():
    """List ICAO indicators that cannot currently be derived from SERENE."""
    return pd.DataFrame([
        {
            "Domain": "GNSS",
            "Indicator": "Amplitude Scintillation",
            "Source / Availability": "Not available from SERENE AIDA/Kp-ap inputs",
        },
        {
            "Domain": "GNSS",
            "Indicator": "Phase Scintillation",
            "Source / Availability": "Not available from SERENE AIDA/Kp-ap inputs",
        },
        {
            "Domain": "HF COM",
            "Indicator": "Polar Cap Absorption",
            "Source / Availability": "Not available from SERENE AIDA/Kp-ap inputs",
        },
        {
            "Domain": "HF COM",
            "Indicator": "Shortwave Fadeout",
            "Source / Availability": "Not available from SERENE AIDA/Kp-ap inputs",
        },
        {
            "Domain": "Radiation",
            "Indicator": "Effective Dose FL <= 460",
            "Source / Availability": "Not available from SERENE AIDA/Kp-ap inputs",
        },
        {
            "Domain": "Radiation",
            "Indicator": "Effective Dose FL > 460",
            "Source / Availability": "Not available from SERENE AIDA/Kp-ap inputs",
        },
    ])


def build_overall_risk_cards(summary):
    """Return top-line domain and overall status from the PECASUS table."""
    frame = _as_frame(summary)
    if frame.empty or not {"Domain", "Status"}.issubset(frame.columns):
        return {
            "GNSS Risk": "UNAVAILABLE",
            "HF COM Risk": "UNAVAILABLE",
            "Radiation Risk": "UNAVAILABLE",
            "Overall Risk": "UNAVAILABLE",
        }
    cards = {}
    for domain, label in (
        ("GNSS", "GNSS Risk"),
        ("HF COM", "HF COM Risk"),
        ("Radiation", "Radiation Risk"),
    ):
        statuses = frame.loc[frame["Domain"] == domain, "Status"].tolist()
        cards[label] = _worst_available_or_unavailable(statuses)
    cards["Overall Risk"] = _worst_available_or_unavailable(cards.values())
    return cards


def _spatial_summary_row(frame, domain, indicator, eligible):
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
    latest_status = classifier(latest_value) if latest_value is not None else "UNAVAILABLE"
    max3_status = classifier(max3) if max3 is not None else "UNAVAILABLE"
    plus3_status = classifier(plus3) if plus3 is not None else "UNAVAILABLE"
    plus6_status = classifier(plus6) if plus6 is not None else "UNAVAILABLE"
    return {
        "Domain": domain,
        "Indicator": indicator,
        "Moderate threshold": _moderate_threshold(indicator),
        "Severe threshold": _severe_threshold(indicator),
        "Time UTC": _format_utc(latest.get("time")) if latest is not None else "N/A",
        "Latest value": _na(latest_value),
        "Status": latest_status,
        "Alert": _alert_icon(latest_status),
        "Max-3h value": _na(max3),
        "Max-3h status": max3_status,
        "+3h forecast": _na(plus3),
        "+3h status": plus3_status,
        "+6h forecast": _na(plus6),
        "+6h status": plus6_status,
        "Forecast source": _summary_forecast_source(
            values["+3h"], values["+6h"]
        ),
        "Source / Availability": (
            ", ".join(dict.fromkeys(sources))
            if sources else _availability_note(indicator, eligible)
        ),
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
    status = classify_auroral_absorption(value) if value is not None else "UNAVAILABLE"
    max3_status = (
        classify_auroral_absorption(max3_value)
        if max3_value is not None else "UNAVAILABLE"
    )
    return {
        "Domain": "HF COM",
        "Indicator": "Auroral Absorption",
        "Moderate threshold": "Kp >= 8 global proxy",
        "Severe threshold": "Kp >= 9 global proxy",
        "Time UTC": _format_utc(row.get("time")) if row is not None else "N/A",
        "Latest value": _na(value),
        "Status": status,
        "Alert": _alert_icon(status),
        "Max-3h value": _na(max3_value),
        "Max-3h status": max3_status,
        "+3h forecast": "N/A",
        "+3h status": "UNAVAILABLE",
        "+6h forecast": "N/A",
        "+6h status": "UNAVAILABLE",
        "Forecast source": "Unavailable",
        "Source / Availability": (
            _source_value(row.get("source")) + "; global Kp proxy, not regional"
            if row is not None else
            "SERENE Kp/ap unavailable; global proxy, not regional"
        ),
    }


def _unavailable_summary_row(domain, indicator, moderate, severe, availability):
    return {
        "Domain": domain,
        "Indicator": indicator,
        "Moderate threshold": moderate,
        "Severe threshold": severe,
        "Time UTC": "N/A",
        "Latest value": "N/A",
        "Status": "UNAVAILABLE",
        "Alert": _alert_icon("UNAVAILABLE"),
        "Max-3h value": "N/A",
        "Max-3h status": "UNAVAILABLE",
        "+3h forecast": "N/A",
        "+3h status": "UNAVAILABLE",
        "+6h forecast": "N/A",
        "+6h status": "UNAVAILABLE",
        "Forecast source": "Unavailable",
        "Source / Availability": availability,
    }


def _regional_max(frame, indicator, horizon):
    if frame.empty or not {"indicator", "horizon"}.issubset(frame.columns):
        return None
    work = _rows_for_indicator_horizon(frame, indicator, horizon)
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


def _rows_for_indicator_horizon(frame, indicator, horizon):
    """Return official rows when present, otherwise generated prediction rows."""
    if frame.empty or not {"indicator", "horizon"}.issubset(frame.columns):
        return pd.DataFrame()
    canonical_horizon = _canonical_horizon(horizon)
    work = frame[
        (frame["indicator"].map(_canonical_indicator) == indicator)
        & (frame["horizon"].map(_canonical_horizon) == canonical_horizon)
    ].copy()
    if not work.empty:
        if canonical_horizon in {"+3h", "+6h"}:
            work["forecast_source"] = "SERENE official forecast"
        return work
    if canonical_horizon in {"+3h", "+6h"}:
        return _fallback_prediction_rows(frame, indicator, canonical_horizon)
    return work


def _fallback_prediction_rows(frame, indicator, horizon):
    if frame.empty or not {"indicator", "horizon", "lat", "lon"}.issubset(frame.columns):
        return pd.DataFrame()
    hours = 3 if horizon == "+3h" else 6
    work = frame[
        (frame["indicator"].map(_canonical_indicator) == indicator)
        & (frame["horizon"].map(_canonical_horizon).isin(["Latest", "Max3h"]))
    ].copy()
    if "product_kind" in work.columns:
        work = work[work["product_kind"].astype(str).str.casefold() != "baseline"]
    if work.empty:
        return pd.DataFrame()
    work["lat"] = pd.to_numeric(work["lat"], errors="coerce")
    work["lon"] = pd.to_numeric(work["lon"], errors="coerce")
    work["_risk_value"] = work.apply(
        lambda row: _indicator_value(row, indicator), axis=1
    )
    work["_risk_value"] = pd.to_numeric(work["_risk_value"], errors="coerce")
    if "time" in work.columns:
        work["_parsed_time"] = pd.to_datetime(work["time"], errors="coerce", utc=True)
    else:
        work["_parsed_time"] = pd.NaT
    work = work.dropna(subset=["lat", "lon", "_risk_value"])
    if work.empty:
        return pd.DataFrame()

    rows = []
    for _, group in work.groupby(["lat", "lon"], sort=False):
        if group["_parsed_time"].notna().any():
            latest_time = group["_parsed_time"].max()
            latest_candidates = group[group["_parsed_time"] == latest_time]
            latest = latest_candidates.iloc[-1].copy()
            window_start = latest_time - pd.Timedelta(hours=3)
            window = group[
                group["_parsed_time"].between(window_start, latest_time, inclusive="both")
            ].copy()
            earlier = window[window["_parsed_time"] < latest_time]
            if not earlier.empty:
                earliest = earlier.sort_values("_parsed_time").iloc[0]
                trend_per_hour = (
                    float(latest["_risk_value"]) - float(earliest["_risk_value"])
                ) / 3.0
                predicted = float(latest["_risk_value"]) + trend_per_hour * hours
                forecast_source = "Trend-based forecast"
            else:
                predicted = float(latest["_risk_value"])
                forecast_source = "Persistence forecast"
            latest["time"] = latest_time + pd.Timedelta(hours=hours)
        else:
            latest = group.iloc[-1].copy()
            predicted = float(latest["_risk_value"])
            forecast_source = "Persistence forecast"

        latest["horizon"] = horizon
        latest["forecast_source"] = forecast_source
        latest["product_kind"] = (
            f"fallback_trend_{hours * 60}"
            if forecast_source == "Trend-based forecast"
            else f"fallback_persistence_{hours * 60}"
        )
        latest["source"] = (
            f"Dashboard-generated {forecast_source.lower()} from SERENE analysis"
        )
        if indicator == "Post-Storm Depression":
            latest["psd_percent"] = predicted
        else:
            latest["value"] = predicted
        rows.append(latest.drop(labels=["_risk_value", "_parsed_time"], errors="ignore"))
    return pd.DataFrame(rows)


def _indicator_value(row, indicator):
    if row is None:
        return None
    if indicator == "Post-Storm Depression":
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
        return "Post-Storm Depression"
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
    forecast_source = item.get("forecast_source")
    if forecast_source is not None and not pd.isna(forecast_source):
        return str(forecast_source).casefold()
    product_kind = str(item.get("product_kind", "")).strip().casefold()
    if product_kind.startswith("forecast_") or horizon in {"+3h", "+6h"}:
        return "official forecast"
    return "analysis"


def _na(value):
    return "N/A" if value is None else value


def _moderate_threshold(indicator):
    if indicator == "Vertical TEC":
        return "TEC >= 125 TECU"
    if indicator == "Post-Storm Depression":
        return "PSD >= 30%"
    return "N/A"


def _severe_threshold(indicator):
    if indicator == "Vertical TEC":
        return "TEC >= 175 TECU"
    if indicator == "Post-Storm Depression":
        return "PSD >= 50%"
    return "N/A"


def _availability_note(indicator, eligible):
    if indicator == "Post-Storm Depression":
        if eligible is None:
            return "Requires AIDA MUF3000F2 baseline and complete prior-96h Kp history"
        if not eligible:
            return "AIDA MUF3000F2-derived PSD; Kp storm gate inactive"
        return "AIDA MUF3000F2-derived PSD; Kp storm gate active"
    if indicator == "Vertical TEC":
        return "SERENE AIDA TEC unavailable for selected product"
    return "N/A"


def _alert_icon(status):
    return {
        "OK": "✓",
        "MODERATE": "⚠",
        "SEVERE": "!",
        "UNAVAILABLE": "—",
        "N/A": "—",
    }.get(str(status), "—")


def _summary_forecast_source(plus3, plus6):
    entries = []
    for label, row in (("+3h", plus3), ("+6h", plus6)):
        source = _row_forecast_source(row)
        if source != "Unavailable":
            entries.append((label, source))
    if not entries:
        return "Unavailable"
    unique_sources = list(dict.fromkeys(source for _, source in entries))
    if len(unique_sources) == 1 and len(entries) == 2:
        return unique_sources[0]
    parts = [f"{source} ({label})" for label, source in entries]
    missing_labels = {
        "+3h": plus3,
        "+6h": plus6,
    }
    for label, row in missing_labels.items():
        if row is None:
            parts.append(f"Unavailable ({label})")
    return "; ".join(parts)


def _row_forecast_source(row):
    if row is None:
        return "Unavailable"
    source = row.get("forecast_source")
    if source is None or pd.isna(source) or not str(source).strip():
        return "Unavailable"
    return str(source)


def _worst_available_or_unavailable(values):
    priority = {"OK": 0, "MODERATE": 1, "SEVERE": 2}
    available = [str(value) for value in values if str(value) in priority]
    if not available:
        return "UNAVAILABLE"
    return max(available, key=priority.get)
