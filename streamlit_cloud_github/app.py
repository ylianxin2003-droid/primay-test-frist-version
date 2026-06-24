"""Aviation space-weather monitoring and risk forecast dashboard."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from aida_grid import estimate_target_points
from app_utils import (
    AIDA_ARCHIVE_START,
    advisory_metadata_for_load,
    build_data_preview,
    combine_date_time_iso,
    default_time_range,
    historical_risk_windows,
    mappable_variable_options,
    parse_select_range_to_widgets,
    validate_requested_window,
)
from config import SERENE_API_TOKEN, reload_config, validate_config
from data_loader import IcaoProductBundle, LoadStatus, load_icao_products
from icao_message import generate_icao_message
from icao_risk import (
    build_categorical_cells,
    build_icao_summary,
    unavailable_indicator_rows,
)
from icao_visualisation import create_icao_category_map
from serene_client import SereneClient
from visualisation import (
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
        "icao_bundle": IcaoProductBundle(),
        "icao_summary": pd.DataFrame(),
        "advisory_sequence": 0,
        "advisory_generated_time": None,
        "advisory_number": None,
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
    params["model"] = "AIDA"
    st.sidebar.caption("Verified model: AIDA")

    _default_start, default_end = default_time_range()
    selected_date = st.session_state.get("end_date")
    if selected_date is not None and selected_date < AIDA_ARCHIVE_START:
        st.session_state.end_date = AIDA_ARCHIVE_START
    st.sidebar.markdown("#### Analysis time")
    st.sidebar.caption("Default end time is 15 minutes behind UTC to allow AIDA publication.")
    st.sidebar.caption(
        "The selected analysis time anchors the product; its preceding "
        "three-hour window is loaded automatically."
    )
    st.sidebar.caption("AIDA regional archive begins at 2024-09-28 00:00 UTC.")

    analysis_date_col, analysis_time_col = st.sidebar.columns(2)
    with analysis_date_col:
        end_date = st.date_input(
            "Analysis date",
            value=default_end.date(),
            min_value=AIDA_ARCHIVE_START,
            key="end_date",
        )
    with analysis_time_col:
        end_clock = st.time_input(
            "Analysis time UTC",
            value=default_end.time(),
            step=timedelta(minutes=1),
            key="end_time_clock",
        )

    params["end_time"] = combine_date_time_iso(end_date, end_clock)
    params["start_time"] = (
        pd.Timestamp(params["end_time"]) - pd.Timedelta(hours=3)
    ).isoformat()
    params["variables"] = ["TEC", "MUF3000F2"]
    st.sidebar.caption(f"Analysis ISO time: {params['end_time']}")
    st.sidebar.caption("Fixed ICAO inputs: TEC and MUF3000F2 from SERENE AIDA.")

    st.sidebar.markdown("#### Region selection")
    with st.sidebar.expander("Bounding box and grid step", expanded=True):
        lat_min = st.number_input("Lat min", value=45.0, min_value=-90.0, max_value=90.0)
        lat_max = st.number_input("Lat max", value=60.0, min_value=-90.0, max_value=90.0)
        lon_min = st.number_input("Lon min", value=-15.0, min_value=-180.0, max_value=180.0)
        lon_max = st.number_input("Lon max", value=15.0, min_value=-180.0, max_value=180.0)
        params["grid_step"] = st.slider("Grid step (degrees)", 2.0, 30.0, 5.0, 1.0)
        local_points = estimate_target_points(
            {
                "lat_min": lat_min,
                "lat_max": lat_max,
                "lon_min": lon_min,
                "lon_max": lon_max,
            },
            params["grid_step"],
        )
        st.caption(
            f"Local map points: {local_points:,}. One raw AIDA state is downloaded "
            "per output time; this grid is calculated locally."
        )

    params["region"] = {
        "lat_min": lat_min,
        "lat_max": lat_max,
        "lon_min": lon_min,
        "lon_max": lon_max,
    }

    st.sidebar.markdown("---")
    if st.sidebar.button("Test SERENE API connection", width="stretch"):
        with st.spinner("Testing connection..."):
            ok, msg = SereneClient().test_connection()
            st.session_state.api_connected = ok
            st.session_state.api_message = msg
        if ok:
            st.sidebar.success(msg)
        else:
            st.sidebar.warning(msg)

    if st.sidebar.button("Load / Refresh data", type="primary", width="stretch"):
        _do_load(params)

    st.sidebar.caption("Prototype research system, not for operational aviation decisions.")
    return params


def _do_load(params: dict) -> None:
    progress_bar = st.progress(0.0, text="Preparing...")
    progress_state = {"done": 0, "total": 1}

    def _on_api_progress(done: int, total: int, label: str = "AIDA data") -> None:
        progress_state["done"] = done
        progress_state["total"] = max(total, 1)
        progress_bar.progress(
            done / progress_state["total"],
            text=f"{label}: {done}/{total}...",
        )

    cleared = advisory_metadata_for_load(
        False,
        st.session_state.advisory_sequence,
        pd.Timestamp.now(tz="UTC"),
    )
    st.session_state.advisory_generated_time = cleared["generated_time"]
    st.session_state.advisory_number = cleared["number"]

    try:
        validation_error = validate_requested_window(
            params["start_time"], params["end_time"]
        )
        if validation_error:
            failed_status = LoadStatus(
                source="none", ok=False, message=validation_error
            )
            st.session_state.data = pd.DataFrame()
            st.session_state.status = failed_status
            st.session_state.icao_bundle = IcaoProductBundle(status=failed_status)
            st.session_state.icao_summary = pd.DataFrame()
            return
        bundle = load_icao_products(
            analysis_time=params["end_time"],
            variables=["TEC", "MUF3000F2"],
            region=params.get("region"),
            grid_step=params.get("grid_step", 5.0),
            progress_callback=_on_api_progress,
        )
        progress_bar.progress(1.0, text="Generating ICAO-style research products...")
        latest = pd.DataFrame()
        if not bundle.products.empty:
            latest = bundle.products[
                bundle.products["product_kind"] == "analysis"
            ].copy()
        frames = [frame for frame in (latest, bundle.indices) if not frame.empty]
        st.session_state.data = (
            pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        )
        st.session_state.status = bundle.status
        st.session_state.icao_bundle = bundle
        st.session_state.icao_summary = build_icao_summary(
            bundle.products,
            bundle.indices,
            eligible=bundle.kp_storm_eligible,
        )
        if bundle.status.ok:
            generated = pd.Timestamp.now(tz="UTC")
            advisory = advisory_metadata_for_load(
                True, st.session_state.advisory_sequence, generated
            )
            st.session_state.advisory_sequence = advisory["sequence"]
            st.session_state.advisory_generated_time = advisory["generated_time"]
            st.session_state.advisory_number = advisory["number"]
        st.session_state.alerts = pd.DataFrame()
    finally:
        progress_bar.empty()


def _source_label(status: LoadStatus) -> str:
    return {
        "api": "SERENE API",
        "indices": "SERENE global indices only",
        "none": "No data",
    }.get(status.source, status.source)


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
    c1, c2, c3, c4, c5 = st.columns(5)

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
    with c4:
        st.metric(
            "AIDA raw datasets downloaded",
            int(status.metadata.get("aida_dataset_downloads", 0))
            + int(status.metadata.get("analysis_downloads", 0))
            + int(status.metadata.get("forecast_downloads", 0)),
        )
    with c5:
        st.metric(
            "Local map points",
            f"{int(status.metadata.get('local_map_points', 0)):,}",
        )

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
        width="stretch",
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
        "Each raw AIDA state is downloaded once per output time and interpreted by "
        "the official AIDA package; all requested map points are calculated locally. "
        "No local sample dataset is used."
    )
    st.subheader("ICAO-style SERENE-only products")
    st.info(
        "The category map, summary table, and research messages appear after "
        "SERENE analysis and official forecast products are loaded."
    )
    with st.expander("Quick start"):
        st.markdown(
            """
            1. Configure SERENE_API_BASE_URL and SERENE_API_TOKEN.
            2. Test the SERENE API connection.
            3. Load API data for an analysis time and selected region.
            4. Inspect Latest, Max-3h, +3h, and +6h products.
            """
        )


def _render_icao_products(params: dict) -> None:
    """Render the primary SERENE-only ICAO-style research products."""
    bundle: IcaoProductBundle = st.session_state.icao_bundle
    summary = st.session_state.icao_summary
    st.subheader("ICAO-style SERENE-only products")
    st.caption(
        "Latest and Max-3h values use SERENE AIDA analyses; prediction columns "
        "use official AIDA +3h/+6h forecasts. Spatial values are regional maxima."
    )
    st.caption(
        "Categories use ICAO thresholds: TEC 125/175 TECU, auroral absorption "
        "proxy Kp 8/9, and PSD 30%/50% with a prior-96h Kp≥6 eligibility gate."
    )
    if bundle.kp_storm_eligible is None:
        st.warning("PSD status unavailable: complete 96-hour SERENE Kp history is missing.")
    elif bundle.kp_storm_eligible:
        st.info("PSD storm gate active: SERENE Kp reached at least 6 in the prior 96 hours.")
    else:
        st.info("PSD storm gate inactive: SERENE Kp remained below 6 in the prior 96 hours.")
    if summary.empty:
        st.info("Load SERENE data to create the ICAO-style table and maps.")
        return

    st.dataframe(summary, width="stretch", hide_index=True)

    indicator = st.selectbox(
        "Categorical regional indicator",
        ["Vertical TEC", "Post-storm depression"],
    )
    horizon = st.radio(
        "Official product horizon",
        ["Latest", "+3h", "+6h"],
        horizontal=True,
    )
    cells = build_categorical_cells(
        bundle.products,
        indicator,
        horizon,
        kp_storm_eligible=bundle.kp_storm_eligible,
    )
    st.plotly_chart(
        create_icao_category_map(cells, f"{indicator} — {horizon}"),
        width="stretch",
    )
    st.caption("Global Kp/ap are excluded from regional map cells.")

    st.markdown("#### Indicators unavailable from the SERENE-only source")
    unavailable = unavailable_indicator_rows()
    st.dataframe(unavailable, width="stretch", hide_index=True)
    st.caption("Not available from SERENE means no zero or OK value is fabricated.")

    if bundle.status.ok:
        _render_research_messages(summary, params)
    else:
        st.info("Research messages require a successful SERENE AIDA analysis state.")


def _render_research_messages(summary: pd.DataFrame, params: dict) -> None:
    st.markdown("#### Automated text-based SWX research messages")
    analysis_time = st.session_state.status.metadata.get(
        "analysis_time", params["end_time"]
    )
    generated_time = (
        st.session_state.advisory_generated_time or pd.Timestamp.now(tz="UTC")
    )
    advisory_number = st.session_state.advisory_number or f"{generated_time.year}/001"
    loaded_region = st.session_state.status.metadata.get(
        "loaded_region", params["region"]
    )
    tec = _summary_row(summary, "Vertical TEC")
    psd = _summary_row(summary, "Post-storm depression")
    kp = _summary_row(summary, "Kp auroral absorption proxy")

    if tec is not None and tec["Status"] in {"OK", "MODERATE", "SEVERE"}:
        gnss = generate_icao_message(
            effect="GNSS",
            observed_time=analysis_time,
            observed_category=tec["Status"],
            region=loaded_region,
            forecasts={
                180: _available_category(tec["+3h status"]),
                360: _available_category(tec["+6h status"]),
            },
            generated_time=generated_time,
            advisory_number=advisory_number,
        )
        st.code(gnss, language="text")
        st.download_button(
            "Download GNSS research message",
            data=gnss,
            file_name="serene_gnss_research_advisory.txt",
            mime="text/plain",
        )
    else:
        st.info("GNSS research message unavailable because SERENE TEC is unavailable.")

    hf_observed = _worst_available_category([
        psd["Status"] if psd is not None else None,
        kp["Status"] if kp is not None else None,
    ])
    if hf_observed is None:
        st.info("HF COM research message unavailable because SERENE inputs are unavailable.")
        return
    hf = generate_icao_message(
        effect="HF COM",
        observed_time=analysis_time,
        observed_category=hf_observed,
        region=loaded_region,
        forecasts={
            180: _available_category(psd["+3h status"]) if psd is not None else None,
            360: _available_category(psd["+6h status"]) if psd is not None else None,
        },
        generated_time=generated_time,
        advisory_number=advisory_number,
    )
    st.code(hf, language="text")
    st.download_button(
        "Download HF COM research message",
        data=hf,
        file_name="serene_hf_com_research_advisory.txt",
        mime="text/plain",
    )


def _summary_row(summary: pd.DataFrame, indicator: str) -> pd.Series | None:
    rows = summary[summary["Indicator"] == indicator]
    return None if rows.empty else rows.iloc[0]


def _available_category(value: object) -> str | None:
    return str(value) if value in {"OK", "MODERATE", "SEVERE"} else None


def _worst_available_category(values: list[object]) -> str | None:
    priority = {"OK": 0, "MODERATE": 1, "SEVERE": 2}
    available = [str(value) for value in values if value in priority]
    return max(available, key=priority.get) if available else None


def _render_data_views(df: pd.DataFrame, alerts: pd.DataFrame) -> None:
    st.subheader("Data preview")
    st.dataframe(build_data_preview(df, alerts).head(100), width="stretch")

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
        st.plotly_chart(create_time_series_plot(df, variable=selected_time_var), width="stretch")
    with col_map:
        st.subheader("Raw variable map")
        st.plotly_chart(create_map_plot(df, variable=selected_map_var), width="stretch")

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


def _render_global_indices(df: pd.DataFrame) -> None:
    """Show Kp/ap as planetary context without creating geographic map cells."""
    if "variable" not in df.columns:
        return
    global_indices = df[df["variable"].isin(["Kp", "ap"])].copy()
    if global_indices.empty:
        return

    st.subheader("Global geomagnetic context")
    st.caption(
        "Kp and ap are planetary indices. They provide global storm context and are "
        "not assigned to regional map cells."
    )
    columns = st.columns(2)
    for column, variable in zip(columns, ("Kp", "ap")):
        values = pd.to_numeric(
            global_indices.loc[global_indices["variable"] == variable, "value"],
            errors="coerce",
        ).dropna()
        with column:
            st.metric(f"Peak {variable}", f"{values.max():.1f}" if not values.empty else "N/A")
    st.plotly_chart(create_time_series_plot(global_indices), width="stretch")


def _render_main(params: dict) -> None:
    st.title("Aviation Space Weather Dashboard")
    st.caption("SERENE-only ICAO-style research monitoring and official AIDA forecasts.")

    _render_cloud_api_hint()
    _render_connection_panel()
    _render_historical_windows()
    st.markdown("---")

    bundle: IcaoProductBundle = st.session_state.icao_bundle
    if st.session_state.data.empty and bundle.products.empty:
        _render_empty_state()
        return

    df = st.session_state.data
    alerts = st.session_state.alerts
    _render_icao_products(params)
    st.markdown("---")
    _render_global_indices(df)
    st.markdown("---")
    if not df.empty:
        _render_data_views(df, alerts)


def main() -> None:
    _init_state()
    _apply_pending_time_range()
    params = _render_sidebar()
    _render_main(params)


if __name__ == "__main__":
    main()
