"""Aviation space-weather monitoring and risk forecast dashboard."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from alert_engine import DISCLAIMER, generate_alerts, generate_overall_risk
from app_utils import (
    build_data_preview,
    combine_date_time_iso,
    generate_historical_risk_alerts,
    historical_risk_windows,
    mappable_variable_options,
    parse_select_range_to_widgets,
)
from config import SERENE_API_TOKEN, reload_config, validate_config
from data_loader import LoadStatus, load_data
from forecast_engine import FORECAST_HORIZONS, forecast_summary, generate_risk_forecast
from forecast_visualisation import create_risk_forecast_map
from serene_client import MAX_GRID_POINTS, SereneClient
from visualisation import (
    create_alert_summary,
    create_alert_timeline,
    create_map_plot,
    create_time_series_plot,
)


st.set_page_config(
    page_title="Aviation Space Weather Dashboard",
    page_icon="SW",
    layout="wide",
    initial_sidebar_state="expanded",
)

reload_config()
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


def _init_state() -> None:
    defaults = {
        "data": pd.DataFrame(),
        "status": LoadStatus(),
        "alerts": pd.DataFrame(),
        "forecast": pd.DataFrame(),
        "api_connected": None,
        "api_message": "Not tested yet.",
        "config_warnings": validate_config(),
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _render_cloud_api_hint() -> None:
    if SERENE_API_TOKEN:
        return
    st.info(
        "SERENE API is not configured. This app is API-only and does not load "
        "local sample datasets. Add SERENE_API_BASE_URL, SERENE_API_TOKEN, "
        "SERENE_API_TIMEOUT, and SERENE_AUTH_SCHEME in Streamlit Cloud Secrets, "
        "then reboot the app."
    )


def _render_sidebar() -> dict:
    st.sidebar.markdown("# SERENE AIDA")
    st.sidebar.markdown("*Aviation Space Weather Monitor*")
    st.sidebar.markdown("---")

    params: dict = {"source": "api"}

    if st.session_state.config_warnings:
        with st.sidebar.expander("Configuration issues", expanded=True):
            for msg in st.session_state.config_warnings:
                st.warning(msg)

    st.sidebar.info("Data source: SERENE API")
    params["model"] = st.sidebar.selectbox("Model", ["AIDA", "TOMIRIS"])

    now = datetime.now(timezone.utc).replace(microsecond=0)
    default_start = now - timedelta(hours=6)
    st.sidebar.markdown("#### Time range")

    start_date_col, start_time_col = st.sidebar.columns(2)
    with start_date_col:
        start_date = st.date_input("Start date", value=default_start.date(), key="start_date")
    with start_time_col:
        start_clock = st.time_input(
            "Start time",
            value=default_start.time(),
            step=timedelta(minutes=1),
            key="start_time_clock",
        )

    end_date_col, end_time_col = st.sidebar.columns(2)
    with end_date_col:
        end_date = st.date_input("End date", value=now.date(), key="end_date")
    with end_time_col:
        end_clock = st.time_input(
            "End time",
            value=now.time(),
            step=timedelta(minutes=1),
            key="end_time_clock",
        )

    params["start_time"] = combine_date_time_iso(start_date, start_clock)
    params["end_time"] = combine_date_time_iso(end_date, end_clock)
    st.sidebar.caption(f"ISO range: {params['start_time']} to {params['end_time']}")

    avail_vars = ["vTEC", "TEC", "MUF3000", "foF2", "MUF3000_depression", "foF2_depression"]
    selected_vars = st.sidebar.multiselect(
        "Variable selection",
        options=avail_vars,
        default=["TEC"],
    )
    params["variables"] = selected_vars or None

    st.sidebar.markdown("#### Region selection")
    with st.sidebar.expander("Bounding box and grid step", expanded=True):
        lat_min = st.number_input("Lat min", value=45.0, min_value=-90.0, max_value=90.0)
        lat_max = st.number_input("Lat max", value=60.0, min_value=-90.0, max_value=90.0)
        lon_min = st.number_input("Lon min", value=-15.0, min_value=-180.0, max_value=180.0)
        lon_max = st.number_input("Lon max", value=15.0, min_value=-180.0, max_value=180.0)
        params["grid_step"] = st.slider("Grid step (degrees)", 2.0, 30.0, 5.0, 1.0)
        est_n, _, _ = SereneClient.estimate_grid_points(
            lat_min,
            lat_max,
            lon_min,
            lon_max,
            params["grid_step"],
            params["grid_step"],
        )
        st.caption(f"About {est_n} API call(s), capped at {MAX_GRID_POINTS}.")

    params["region"] = {
        "lat_min": lat_min,
        "lat_max": lat_max,
        "lon_min": lon_min,
        "lon_max": lon_max,
    }

    st.sidebar.markdown("---")
    if st.sidebar.button("Test SERENE API connection", use_container_width=True):
        with st.spinner("Testing connection..."):
            ok, msg = SereneClient().test_connection()
            st.session_state.api_connected = ok
            st.session_state.api_message = msg
        if ok:
            st.sidebar.success(msg)
        else:
            st.sidebar.warning(msg)

    if st.sidebar.button("Load / Refresh data", type="primary", use_container_width=True):
        _do_load(params)

    st.sidebar.caption("Prototype research system, not for operational aviation decisions.")
    return params


def _do_load(params: dict) -> None:
    progress_bar = st.progress(0.0, text="Preparing...")
    progress_state = {"done": 0, "total": 1}

    def _on_api_progress(done: int, total: int) -> None:
        progress_state["done"] = done
        progress_state["total"] = max(total, 1)
        progress_bar.progress(
            done / progress_state["total"],
            text=f"SERENE API: point {done}/{total}...",
        )

    try:
        df, status = load_data(
            source=params["source"],
            model=params["model"],
            start_time=params.get("start_time"),
            end_time=params.get("end_time"),
            variables=params.get("variables"),
            region=params.get("region"),
            grid_step=params.get("grid_step", 5.0),
            progress_callback=_on_api_progress,
        )
        progress_bar.progress(1.0, text="Generating advisories and forecasts...")
        st.session_state.data = df
        st.session_state.status = status

        data_alerts = generate_alerts(df) if not df.empty else pd.DataFrame()
        has_serene_indices = (
            not df.empty
            and "variable" in df.columns
            and df["variable"].isin(["Kp", "ap"]).any()
        )
        historical_alerts = (
            pd.DataFrame()
            if has_serene_indices
            else generate_historical_risk_alerts(params.get("start_time"), params.get("end_time"))
        )
        st.session_state.alerts = pd.concat([data_alerts, historical_alerts], ignore_index=True)
        st.session_state.forecast = generate_risk_forecast(df) if not df.empty else pd.DataFrame()
    finally:
        progress_bar.empty()


def _source_label(status: LoadStatus) -> str:
    return {"api": "SERENE API", "none": "No data"}.get(status.source, status.source)


def _apply_selected_historical_range(selected_rows: list[int], windows: pd.DataFrame) -> None:
    if not selected_rows:
        return
    row_index = selected_rows[0]
    if row_index >= len(windows):
        return
    parsed = parse_select_range_to_widgets(str(windows.iloc[row_index]["Select range"]))
    if parsed is None:
        return
    if any(st.session_state.get(key) != value for key, value in parsed.items()):
        st.session_state.pending_time_range_widgets = parsed
        st.rerun()


def _apply_pending_time_range() -> None:
    pending = st.session_state.pop("pending_time_range_widgets", None)
    if not pending:
        return
    for key, value in pending.items():
        st.session_state[key] = value


def _render_connection_panel() -> None:
    st.subheader("SERENE API and data status")
    c1, c2, c3 = st.columns(3)

    with c1:
        if st.session_state.api_connected is True:
            st.success(f"API: {st.session_state.api_message}")
        elif st.session_state.api_connected is False:
            st.warning(f"API: {st.session_state.api_message}")
        else:
            st.info("API: not tested. Use the sidebar button.")

    status: LoadStatus = st.session_state.status
    with c2:
        st.metric("Current data source", _source_label(status))
    with c3:
        st.metric("Rows loaded", f"{len(st.session_state.data):,}")

    if status.message:
        if status.ok:
            st.info(status.message)
        else:
            st.error(status.message)
    for warn in status.warnings:
        st.warning(warn)


def _render_historical_windows() -> None:
    st.subheader("Historical risk windows")
    windows = historical_risk_windows()
    selection = st.dataframe(
        windows,
        use_container_width=True,
        hide_index=True,
        height=260,
        selection_mode="single-row",
        on_select="rerun",
    )
    if isinstance(selection, dict):
        selected_rows = selection.get("selection", {}).get("rows", [])
    else:
        selected_rows = getattr(getattr(selection, "selection", None), "rows", [])
    _apply_selected_historical_range(selected_rows, windows)


def _render_empty_state() -> None:
    st.info(
        "Click Load / Refresh data in the sidebar to fetch live SERENE API data. "
        "No local sample data is loaded or stored by the app."
    )
    st.subheader("Risk forecast map")
    st.info(
        "Forecast risk maps will appear here after SERENE API samples are loaded. "
        "The forecast uses the current API response only."
    )
    with st.expander("Quick start"):
        st.markdown(
            """
            1. Configure SERENE_API_BASE_URL and SERENE_API_TOKEN.
            2. Test the SERENE API connection.
            3. Load API data for a selected region and time range.
            4. Use the risk forecast map to inspect storm-like risk areas.
            """
        )


def _render_alerts(alerts: pd.DataFrame) -> None:
    st.subheader("ICAO-style prototype risk advisories")
    overall, summary = generate_overall_risk(alerts)
    st.metric("Current advisory risk", overall)
    st.caption(summary)
    st.caption(DISCLAIMER)

    if alerts.empty:
        st.success("No active prototype advisories. Parameters are within normal range.")
        return

    if overall in {"G5 Extreme", "G4 Severe", "Severe"}:
        st.error(f"Active prototype warning: {overall}")
    else:
        st.warning(f"Active prototype advisory: {overall}")

    col_a, col_b = st.columns(2)
    with col_a:
        st.plotly_chart(create_alert_summary(alerts), use_container_width=True)
    with col_b:
        st.plotly_chart(create_alert_timeline(alerts), use_container_width=True)

    show_cols = [
        c
        for c in (
            "timestamp",
            "region",
            "alert_type",
            "risk_level",
            "reason",
            "possible_aviation_impact",
            "interpretation",
        )
        if c in alerts.columns
    ]
    st.dataframe(alerts[show_cols], use_container_width=True, height=220)


def _render_forecast() -> None:
    forecast = st.session_state.forecast
    st.subheader("Risk forecast map")
    forecast_level, forecast_message = forecast_summary(forecast)
    st.metric("Forecast highest risk", forecast_level)
    st.caption(forecast_message)

    if forecast.empty:
        st.info("No mappable forecast risk data is available for the current API response.")
        return

    horizon_options = [label for label, _hours in FORECAST_HORIZONS]
    selected_horizon = st.radio("Forecast horizon", horizon_options, horizontal=True)
    st.plotly_chart(
        create_risk_forecast_map(forecast, horizon=selected_horizon),
        use_container_width=True,
    )

    forecast_cols = [
        "horizon",
        "lat",
        "lon",
        "risk_level",
        "risk_probability",
        "confidence",
        "driver",
        "predicted_value",
        "explanation",
    ]
    st.dataframe(forecast[forecast_cols].head(100), use_container_width=True, height=260)


def _render_data_views(df: pd.DataFrame, alerts: pd.DataFrame) -> None:
    st.subheader("Data preview")
    st.dataframe(build_data_preview(df, alerts).head(100), use_container_width=True)

    var_options = sorted(df["variable"].dropna().unique()) if "variable" in df.columns else []
    map_var_options = mappable_variable_options(df)
    selected_time_var = st.selectbox("Variable for time series", var_options or [None])

    if map_var_options:
        selected_map_var = st.selectbox("Variable for raw map", map_var_options)
    else:
        selected_map_var = None
        st.info("No variables with latitude/longitude are available for raw map display.")

    col_ts, col_map = st.columns(2)
    with col_ts:
        st.subheader("Time series")
        st.plotly_chart(create_time_series_plot(df, variable=selected_time_var), use_container_width=True)
    with col_map:
        st.subheader("Raw variable map")
        st.plotly_chart(create_map_plot(df, variable=selected_map_var), use_container_width=True)

    with st.expander("Raw load metadata"):
        st.json(
            {
                "source": st.session_state.status.source,
                "message": st.session_state.status.message,
                "warnings": st.session_state.status.warnings,
                "metadata": st.session_state.status.metadata,
            }
        )
        st.download_button(
            "Download current API response as CSV",
            data=df.to_csv(index=False),
            file_name=f"space_weather_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
        )


def _render_main() -> None:
    st.title("Aviation Space Weather Dashboard")
    st.caption("SERENE API-only monitoring with weather-style risk forecasting.")

    _render_cloud_api_hint()
    _render_connection_panel()
    _render_historical_windows()
    st.markdown("---")

    if st.session_state.data.empty:
        _render_empty_state()
        return

    df = st.session_state.data
    alerts = st.session_state.alerts
    _render_alerts(alerts)
    st.markdown("---")
    _render_forecast()
    st.markdown("---")
    _render_data_views(df, alerts)


def main() -> None:
    _init_state()
    _apply_pending_time_range()
    _render_sidebar()
    _render_main()


if __name__ == "__main__":
    main()
