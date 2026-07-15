"""Aviation space-weather monitoring and risk forecast dashboard."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from aida_grid import estimate_target_points
from app_utils import (
    AIDA_ARCHIVE_START,
    AIDA_ARCHIVE_START_UTC,
    advisory_metadata_for_load,
    build_data_preview,
    combine_date_time_iso,
    default_time_range,
    historical_risk_windows,
    make_streamlit_safe_dataframe,
    mappable_variable_options,
    parse_select_range_to_widgets,
    validate_requested_window,
)
from config import SERENE_API_TOKEN, reload_config, validate_config
from data_loader import IcaoProductBundle, LoadStatus, load_icao_products
from hf_coverage import (
    DEFAULT_UK_TRANSMITTER,
    build_hf_coverage_case,
    create_hf_coverage_map,
)
from icao_message import generate_icao_message
from icao_risk import (
    FORECAST_HORIZONS,
    ICAO_COLORS,
    build_categorical_cells,
    build_icao_summary,
    build_overall_risk_cards,
)
from icao_visualisation import create_icao_category_map
from serene_client import SereneClient
from trial_cache import (
    build_trial_bundle_zip,
    load_trial_bundle,
    make_trial_cache_key,
    save_trial_bundle,
    trial_cache_path,
)
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
        "trial_cache_key": None,
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


def _inject_dashboard_css() -> None:
    """Add compact operational-style visual treatment without external assets."""
    st.markdown(
        """
        <style>
        .risk-card {
            border: 1px solid rgba(255,255,255,0.18);
            border-radius: 10px;
            padding: 0.85rem 1rem;
            background: #111827;
            min-height: 94px;
        }
        .risk-card-label {
            color: #cbd5e1;
            font-size: 0.84rem;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }
        .risk-card-status {
            font-size: 1.65rem;
            font-weight: 700;
            line-height: 1.25;
        }
        .risk-card-ok {border-left: 7px solid #2E7D32;}
        .risk-card-moderate {border-left: 7px solid #F9A825;}
        .risk-card-severe {border-left: 7px solid #C62828;}
        .risk-card-unavailable {border-left: 7px solid #95A5A6;}
        </style>
        """,
        unsafe_allow_html=True,
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

    data_loading_mode = st.sidebar.radio(
        "Data loading mode",
        ["Cached trial output", "Live SERENE API"],
        index=0,
        help=(
            "Cached trial output loads processed demo/validation results from "
            "the Git repository when available. Live SERENE API fetches new data."
        ),
    )
    params["data_loading_mode"] = data_loading_mode
    st.sidebar.info(f"Data loading mode: {data_loading_mode}")
    params["model"] = "AIDA"
    st.sidebar.caption("Verified model: AIDA")

    st.sidebar.markdown("#### Dashboard mode")
    mode = st.sidebar.radio(
        "Mode",
        ["Quick Demo", "Full ICAO-style mode"],
        index=0,
        help=(
            "Quick Demo loads the latest analysis and uses +3h/+6h prediction "
            "columns, preferring SERENE official +90 min/+3h/+6h forecasts when available and "
            "otherwise using persistence. Full ICAO-style mode also loads the "
            "3-hour observation window and 30-day MUF3000F2 baseline for PSD."
        ),
    )
    params["mode"] = mode
    params["include_three_hour_window"] = mode == "Full ICAO-style mode"
    params["include_psd_baseline"] = mode == "Full ICAO-style mode"
    if mode == "Quick Demo":
        st.sidebar.caption("Fast mode: skips Max-3h window and PSD baseline; forecast files are still requested.")
    else:
        st.sidebar.caption("Full mode: attempts Max-3h and 30-day PSD baseline and may require many SERENE downloads.")

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
    st.sidebar.caption(f"AIDA archive start: {AIDA_ARCHIVE_START_UTC.strftime('%Y-%m-%d %H:%M UTC')}.")

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

    with st.sidebar.expander("Demo / validation storm windows", expanded=False):
        st.caption(
            "These windows are only shortcuts for testing historical storm-like "
            "periods and for pretending the dashboard is running in the past."
        )
        st.caption(
            "Custom analysis time can be entered manually above; event rows only "
            "change the time after you press the shortcut button."
        )
        windows = historical_risk_windows()
        selection = st.dataframe(
            windows,
            width="stretch",
            hide_index=True,
            height=220,
            selection_mode="single-row",
            on_select="rerun",
            key="event_windows_sidebar",
        )
        if isinstance(selection, dict):
            selected_rows = selection.get("selection", {}).get("rows", [])
        else:
            selected_rows = getattr(getattr(selection, "selection", None), "rows", [])
        if st.button("Use selected event time", key="apply_event_time_sidebar"):
            _apply_selected_historical_range(selected_rows, windows)

    st.sidebar.markdown("#### Region selection")
    with st.sidebar.expander("Bounding box and grid step", expanded=True):
        lat_min = st.number_input("Lat min", value=-90.0, min_value=-90.0, max_value=90.0)
        lat_max = st.number_input("Lat max", value=90.0, min_value=-90.0, max_value=90.0)
        lon_min = st.number_input("Lon min", value=-180.0, min_value=-180.0, max_value=180.0)
        lon_max = st.number_input("Lon max", value=180.0, min_value=-180.0, max_value=180.0)
        params["grid_step"] = st.slider("Grid step (degrees)", 2.0, 30.0, 15.0, 1.0)
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
            "The default grid is global for aviation-scale awareness. Use a "
            "smaller bounding box or finer grid step for regional analysis."
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


@st.cache_data(show_spinner=False)
def _load_trial_bundle_cached(cache_key: str):
    return load_trial_bundle(cache_key)


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
        cache_key = make_trial_cache_key(
            params["end_time"],
            params["region"],
            params.get("grid_step", 15.0),
            params.get("mode", "Quick Demo"),
        )
        st.session_state.trial_cache_key = cache_key
        if params.get("data_loading_mode") == "Cached trial output":
            try:
                progress_bar.progress(0.2, text="Checking cached trial output...")
                bundle, summary, data = _load_trial_bundle_cached(cache_key)
                _set_loaded_result(bundle, summary, data)
                return
            except FileNotFoundError:
                fallback_warning = (
                    "Cached trial output not found for this selection; loading "
                    "from SERENE API instead."
                )
            except Exception as exc:
                fallback_warning = (
                    "Cached trial output could not be loaded; loading from "
                    f"SERENE API instead. Cache error: {exc}"
                )
        else:
            fallback_warning = None
        bundle = load_icao_products(
            analysis_time=params["end_time"],
            variables=["TEC", "MUF3000F2"],
            region=params.get("region"),
            grid_step=params.get("grid_step", 15.0),
            include_three_hour_window=params.get("include_three_hour_window", True),
            include_psd_baseline=params.get("include_psd_baseline", True),
            progress_callback=_on_api_progress,
        )
        progress_bar.progress(1.0, text="Generating ICAO-style research products...")
        if fallback_warning:
            bundle.status.warnings = [fallback_warning, *bundle.status.warnings]
            bundle.status.metadata["cache_key"] = cache_key
            bundle.status.metadata["cache_fallback"] = True
        data = _build_display_data(bundle)
        summary = build_icao_summary(
            bundle.products,
            bundle.indices,
            eligible=bundle.kp_storm_eligible,
        )
        _set_loaded_result(bundle, summary, data)
        st.session_state.alerts = pd.DataFrame()
    finally:
        progress_bar.empty()


def _set_loaded_result(
    bundle: IcaoProductBundle,
    summary: pd.DataFrame,
    data: pd.DataFrame,
) -> None:
    st.session_state.data = data
    st.session_state.status = bundle.status
    st.session_state.icao_bundle = bundle
    st.session_state.icao_summary = summary
    if bundle.status.ok:
        generated = pd.Timestamp.now(tz="UTC")
        advisory = advisory_metadata_for_load(
            True, st.session_state.advisory_sequence, generated
        )
        st.session_state.advisory_sequence = advisory["sequence"]
        st.session_state.advisory_generated_time = advisory["generated_time"]
        st.session_state.advisory_number = advisory["number"]


def _build_display_data(bundle: IcaoProductBundle) -> pd.DataFrame:
    """Return all product rows used by raw preview and time-series views."""
    frames = [
        frame for frame in (bundle.products, bundle.indices)
        if frame is not None and not frame.empty
    ]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _source_label(status: LoadStatus) -> str:
    return {
        "api": "Live SERENE API",
        "trial_cache": "Cached trial output",
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
    c1, c2, c3, c4 = st.columns(4)

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
            "Total official AIDA downloads",
            int(status.metadata.get(
                "total_official_aida_downloads",
                int(status.metadata.get("aida_dataset_downloads", 0))
                + int(status.metadata.get("analysis_downloads", 0))
                + int(status.metadata.get("forecast_downloads", 0)),
            )),
        )

    s1, s2, s3, s4, s5 = st.columns(5)
    with s1:
        st.metric("Rolling/analysis states", int(status.metadata.get("rolling_analysis_downloads", 0)))
    with s2:
        st.metric("Official forecast states", int(status.metadata.get("forecast_downloads", 0)))
    with s3:
        st.metric("PSD baseline states", int(status.metadata.get("baseline_downloads", 0)))
    with s4:
        st.metric("Kp/ap index status", str(status.metadata.get("kp_ap_index_status", "not requested")))
    with s5:
        st.metric("Local map points", f"{int(status.metadata.get('local_map_points', 0)):,}")

    if status.message:
        if status.ok:
            st.info(status.message)
        else:
            st.error(status.message)
    for warn in status.warnings:
        st.warning(warn)

    if status.metadata:
        st.caption(
            "Each AIDA raw state is downloaded once per output time, then all "
            "selected regional grid points are calculated locally."
        )


def _render_demo_validation_windows() -> None:
    st.subheader("Demo / validation storm windows")
    st.caption(
        "Custom analysis time can be entered manually in the sidebar; event rows "
        "only change the time after you press the shortcut button."
    )
    windows = historical_risk_windows()
    selection = st.dataframe(
        windows,
        width="stretch",
        hide_index=True,
        height=260,
        selection_mode="single-row",
        on_select="rerun",
        key="event_windows_main",
    )
    if isinstance(selection, dict):
        selected_rows = selection.get("selection", {}).get("rows", [])
    else:
        selected_rows = getattr(getattr(selection, "selection", None), "rows", [])
    if st.button("Use selected event time", key="apply_event_time_main"):
        _apply_selected_historical_range(selected_rows, windows)


def _render_empty_state() -> None:
    st.info(
        "Click Load / Refresh data in the sidebar to load cached trial output "
        "when available, or fetch Live SERENE API data for new analysis times. "
        "Each raw AIDA state is downloaded once per output time and interpreted by "
        "the official AIDA package; all requested map points are calculated locally. "
        "Cached trial outputs store processed research results for demonstration."
    )
    st.subheader("ICAO-style SERENE-only products")
    st.info(
        "The category map, summary table, and research messages appear after "
        "SERENE analysis and prediction products are loaded."
    )
    with st.expander("Quick start"):
        st.markdown(
            """
            1. Configure SERENE_API_BASE_URL and SERENE_API_TOKEN.
            2. Test the SERENE API connection.
            3. Load API data for an analysis time and selected region.
            4. Inspect Latest, Max-3h, +90 min, +3h, and +6h products.
            """
        )


def _render_overall_risk_cards(summary: pd.DataFrame) -> None:
    st.subheader("Overall risk status")
    cards = build_overall_risk_cards(summary)
    columns = st.columns(4)
    for column, (label, status) in zip(columns, cards.items()):
        css_status = str(status).casefold().replace(" ", "-")
        with column:
            st.markdown(
                f"""
                <div class="risk-card risk-card-{css_status}">
                    <div class="risk-card-label">{label}</div>
                    <div class="risk-card-status">{status}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    st.caption(
        "Worst available status is used for supported GNSS and HF COM indicators: "
        "OK < MODERATE < SEVERE."
    )


def _style_pecasus_table(summary: pd.DataFrame):
    summary = make_streamlit_safe_dataframe(summary)
    status_columns = [
        column for column in [
            "Status",
            "Latest status",
            "Max-3h status",
            "+90 min status",
            "+3h status",
            "+6h status",
        ] if column in summary.columns
    ]

    def _status_cell(value: object) -> str:
        status = str(value)
        color = ICAO_COLORS.get(status, "#95A5A6")
        text = "#ffffff" if status != "MODERATE" else "#111827"
        return f"background-color: {color}; color: {text}; font-weight: 700;"

    def _cell_style(_: object) -> str:
        return (
            "background-color: #0b1220; color: #e5e7eb; "
            "border: 1px solid #334155;"
        )

    styler = summary.style.applymap(_cell_style)
    for column in status_columns:
        styler = styler.applymap(_status_cell, subset=[column])
    return styler


def _render_pecasus_summary_table() -> None:
    summary = st.session_state.icao_summary
    st.subheader("ICAO/PECASUS-style summary table")
    st.caption(
        "This table includes only SERENE-supported, derived, or proxy indicators. "
        "UNAVAILABLE is shown only when a supported input could not be loaded; no OK values are fabricated. "
        "Each forecast horizon has its own source column to distinguish SERENE official forecasts "
        "from dashboard-generated persistence or trend-based predictions."
    )
    if summary.empty:
        st.info("Load SERENE data to create the PECASUS-style table.")
        return
    st.dataframe(_style_pecasus_table(summary), width="stretch", hide_index=True)


def _render_categorical_risk_map() -> None:
    bundle: IcaoProductBundle = st.session_state.icao_bundle
    st.subheader("Categorical risk map")
    st.caption(
        "Regional category maps are only created for spatial AIDA products. "
        "Global Kp/ap are excluded from regional map cells because they are "
        "planetary indices."
    )
    map_col, horizon_col = st.columns([2, 2])
    with map_col:
        indicator = st.selectbox(
            "Risk category map",
            ["Vertical TEC", "Post-Storm Depression"],
            key="risk_category_map_indicator",
        )
    with horizon_col:
        horizon = st.radio(
            "Prediction horizon",
            ["Latest", *FORECAST_HORIZONS.keys()],
            horizontal=True,
            key="risk_category_map_horizon",
        )
    cells = build_categorical_cells(
        bundle.products,
        indicator,
        horizon,
        kp_storm_eligible=bundle.kp_storm_eligible,
    )
    st.plotly_chart(
        create_icao_category_map(cells, f"{indicator} risk category — {horizon}"),
        width="stretch",
    )
    if indicator == "Post-Storm Depression":
        if bundle.kp_storm_eligible is None:
            st.warning("PSD map unavailable: complete 96-hour Kp history is missing.")
        elif bundle.kp_storm_eligible:
            st.info("PSD storm gate active: Kp reached at least 6 in the prior 96 hours.")
        else:
            st.info("PSD storm gate inactive: PSD risk is reported as OK until a Kp≥6 storm gate is met.")


def _render_raw_value_maps(df: pd.DataFrame) -> None:
    st.subheader("Raw variable maps")
    st.caption(
        "Raw AIDA maps use latest analysis values and continuous colour scales. "
        "These are data-value maps, not warning category maps."
    )
    map_df = df
    if "product_kind" in df.columns:
        analysis_rows = df[df["product_kind"] == "analysis"].copy()
        if not analysis_rows.empty:
            map_df = analysis_rows
    options = [
        variable for variable in ["TEC", "vTEC", "MUF3000F2", "MUF3000"]
        if variable in set(map_df.get("variable", pd.Series(dtype=str)).astype(str))
    ]
    if not options:
        options = mappable_variable_options(map_df)
    if not options:
        st.info("No SERENE AIDA variables with latitude/longitude are available for raw maps.")
        return
    selected_map_var = st.selectbox("Raw value map", options, key="raw_value_map_variable")
    st.plotly_chart(create_map_plot(map_df, variable=selected_map_var), width="stretch")
    if selected_map_var in {"MUF3000F2", "MUF3000"}:
        st.caption(
            "MUF3000F2 is shown only as a raw value. PSD risk is derived from its "
            "percentage depression relative to the 30-day same-UTC baseline."
        )


def _render_hf_propagation_case_study(df: pd.DataFrame) -> None:
    st.subheader("HF propagation case study")
    st.caption(
        "Engineering demonstration inspired by Trace HF ray-tracing workflows. "
        "This uses MUF3000F2 and an assumed PSD depression to show how HF coverage "
        "may change. It is a MUF-threshold demonstration, not an operational "
        "ray-tracing product."
    )

    control_col, psd_col, source_col = st.columns([1, 1, 1.2])
    with control_col:
        frequency_mhz = st.slider(
            "HF frequency for coverage demo (MHz)",
            3.0,
            30.0,
            10.0,
            0.5,
            key="hf_case_frequency_mhz",
        )
    with psd_col:
        psd_percent = st.slider(
            "Storm MUF depression used in demo (%)",
            0.0,
            70.0,
            30.0,
            5.0,
            key="hf_case_psd_percent",
            help=(
                "This is a user-controlled engineering assumption for showing "
                "the communication impact of Post-Storm Depression."
            ),
        )
    with source_col:
        st.metric("Transmitter", DEFAULT_UK_TRANSMITTER["name"])
        st.caption("Illustrative UK-to-North-Atlantic route.")

    case, coverage_summary = build_hf_coverage_case(
        df,
        frequency_mhz=frequency_mhz,
        psd_percent=psd_percent,
    )
    if case.empty:
        st.info(coverage_summary["message"])
        return

    metric_cols = st.columns(4)
    metric_cols[0].metric("Quiet usable cells", f"{coverage_summary['quiet_available_pct']:.0f}%")
    metric_cols[1].metric("Storm usable cells", f"{coverage_summary['storm_available_pct']:.0f}%")
    metric_cols[2].metric("Degraded cells", f"{coverage_summary['degraded_count']:,}")
    metric_cols[3].metric("PSD assumption", f"{coverage_summary['psd_percent']:.0f}%")

    st.plotly_chart(
        create_hf_coverage_map(
            case,
            DEFAULT_UK_TRANSMITTER,
            title=(
                "UK-to-North-Atlantic HF coverage demo at "
                f"{coverage_summary['frequency_mhz']:.1f} MHz"
            ),
        ),
        width="stretch",
    )
    st.dataframe(
        case.head(80),
        width="stretch",
        hide_index=True,
    )
    with st.expander("How to interpret this HF case study"):
        st.markdown(
            """
            MUF is the maximum usable frequency supported by the ionosphere for
            a simplified path assumption. If the selected HF frequency is above
            the local MUF, that frequency is treated as not usable in this
            demonstration.

            PSD lowers the assumed storm-time MUF. A cell marked degraded was
            usable before the PSD assumption but becomes unusable after the
            assumed depression.

            Trace can support a more physical HF ray-tracing workflow in future
            work. This dashboard section is a stable engineering demonstration
            of the PSD communication effect, not a full propagation solver.
            """
        )


def _render_research_messages(summary: pd.DataFrame, params: dict) -> None:
    st.subheader("Automated text-based SPWX research messages")
    st.caption(
        "Messages are generated with STATUS: TEST and RESEARCH PROTOTYPE wording. "
        "They are not official ICAO advisories."
    )
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
    psd = _summary_row(summary, "Post-Storm Depression")
    kp = _summary_row(summary, "Auroral Absorption")

    if tec is not None and tec["Status"] in {"OK", "MODERATE", "SEVERE"}:
        gnss = generate_icao_message(
            effect="GNSS",
            observed_time=analysis_time,
            observed_category=tec["Status"],
            region=loaded_region,
            forecasts={
                90: _available_category(tec["+90 min status"]),
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
        st.caption(
            "GNSS message is currently generated from Vertical TEC only because "
            "SERENE does not provide amplitude or phase scintillation inputs."
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
            90: _available_category(psd["+90 min status"]) if psd is not None else None,
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
    st.caption(
        "HF COM message is generated from Post-Storm Depression and the global "
        "Kp auroral-absorption proxy only because PCA and SWF inputs are not "
        "available from SERENE."
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
    st.subheader("API/data metadata and raw data preview")

    var_options = sorted(df["variable"].dropna().unique()) if "variable" in df.columns else []
    if var_options:
        selected_time_var = st.selectbox(
            "Variable for bottom time-series preview", var_options, key="bottom_time_series_variable"
        )
        st.subheader("Time series")
        st.plotly_chart(create_time_series_plot(df, variable=selected_time_var), width="stretch")
    else:
        st.info("No variables are available for time-series preview.")

    st.dataframe(build_data_preview(df, alerts).head(100), width="stretch")

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


def _render_trial_cache_export(params: dict) -> None:
    status: LoadStatus = st.session_state.status
    bundle: IcaoProductBundle = st.session_state.icao_bundle
    if not status.ok or bundle.products.empty:
        return
    cache_key = st.session_state.trial_cache_key or make_trial_cache_key(
        params["end_time"],
        params["region"],
        params.get("grid_step", 15.0),
        params.get("mode", "Quick Demo"),
    )
    with st.expander("Cached trial output tools", expanded=False):
        st.caption(
            "Use this locally after a successful Live SERENE API load to write "
            "processed trial outputs into the repository. Streamlit Cloud runtime "
            "writes are temporary; download the ZIP there, extract it under "
            "streamlit_cloud_github/data/trial_outputs/, and commit the files."
        )
        st.code(str(trial_cache_path(cache_key)), language="text")
        try:
            cache_zip = build_trial_bundle_zip(
                cache_key,
                bundle,
                st.session_state.icao_summary,
                st.session_state.data,
            )
        except Exception as exc:
            st.warning(f"Could not prepare cached trial output ZIP: {exc}")
        else:
            st.download_button(
                "Download cached trial output ZIP",
                data=cache_zip,
                file_name=f"{cache_key}.zip",
                mime="application/zip",
                key="download_trial_cache_zip",
            )
        if st.button("Save current result as cached trial output", key="save_trial_cache"):
            try:
                saved_path = save_trial_bundle(
                    cache_key,
                    bundle,
                    st.session_state.icao_summary,
                    st.session_state.data,
                )
            except Exception as exc:
                st.error(f"Could not save cached trial output: {exc}")
            else:
                _load_trial_bundle_cached.clear()
                st.success(f"Saved cached trial output to {saved_path}")


def _forecast_audit_source(summary: pd.DataFrame, source_column: str) -> str:
    if summary.empty or source_column not in summary.columns:
        return "Unavailable"
    sources = [
        str(value) for value in summary[source_column].dropna().tolist()
        if str(value) and str(value) != "Unavailable"
    ]
    if any(value == "SERENE official forecast" for value in sources):
        return "SERENE official forecast"
    if any(value == "Dashboard-generated trend-based forecast" for value in sources):
        return "Dashboard-generated trend-based forecast"
    if any(value == "Dashboard-generated persistence forecast" for value in sources):
        return "Dashboard-generated persistence forecast"
    return "Unavailable"


def _render_forecast_request_audit(summary: pd.DataFrame) -> None:
    status: LoadStatus = st.session_state.status
    audit_rows = status.metadata.get("forecast_request_audit", [])
    if not audit_rows:
        return
    source_columns = {
        90: "+90 min source",
        180: "+3h source",
        360: "+6h source",
    }
    rows = []
    for item in audit_rows:
        period = int(item.get("forecast_parameter", 0))
        rows.append({
            "Selected analysis time": item.get("analysis_time", "N/A"),
            "Forecast valid time": item.get("valid_time", "N/A"),
            "SERENE forecast parameter": period,
            "Latency": item.get("latency", "N/A"),
            "Downloaded from SERENE": bool(item.get("downloaded_from_serene", False)),
            "Forecast source": _forecast_audit_source(
                summary, source_columns.get(period, "")
            ),
            "Request message": item.get("message", ""),
        })
    with st.expander("Forecast request audit", expanded=False):
        st.dataframe(
            make_streamlit_safe_dataframe(pd.DataFrame(rows)),
            width="stretch",
            hide_index=True,
        )
        st.caption(
            "The forecast valid time is the analysis time plus the horizon. "
            "The SERENE API request sends that valid time with forecast parameters "
            "90, 180, or 360 minutes. If the official file is unavailable, the "
            "dashboard labels any fallback category as dashboard-generated."
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


def _render_explanation_panels() -> None:
    st.subheader("Method and limitations")
    with st.expander("Method and limitations"):
        st.markdown(
            """
            SERENE provides AIDA current, historical, and forecast model output.
            The dashboard downloads raw AIDA states once per requested output time,
            then calculates regional grid values locally with the official
            `breid-phys/aida-ionosphere` interpreter.

            The default grid is global for aviation-scale awareness. Users can
            still choose a smaller bounding box or finer grid step for regional
            analysis.

            TEC and MUF3000F2 come from AIDA. Risk categories are classified
            locally using prototype thresholds. Post-Storm Depression is a
            research proxy derived from MUF3000F2 relative depression against a
            30-day same-UTC baseline when Full ICAO-style mode loads it.

            Kp/ap are global planetary indices and are not plotted as regional
            map cells. Official SERENE forecast data and dashboard-generated
            fallback predictions are distinguished in the summary table, map
            hover metadata, and forecast request audit.

            Cached trial outputs may be used for selected demo / validation
            periods to avoid repeated SERENE downloads during presentations.
            Live SERENE API loading is still available for new analysis times.
            Cached outputs are only for research demonstration and validation.

            This is an academic prototype and not for operational aviation decisions.
            """
        )
    with st.expander("What SERENE AIDA provides"):
        st.markdown(
            """
            SERENE AIDA provides ionospheric model outputs on a geographic grid.
            This dashboard currently uses AIDA TEC/vTEC and MUF3000F2, plus
            SERENE Kp/ap indices as global geomagnetic context.

            The +90 min, +3h and +6h columns are prediction outputs. They may
            come from official SERENE AIDA forecasts when available, or from
            transparent dashboard-side fallback methods such as persistence or
            trend-based extrapolation.
            """
        )
    with st.expander("Which ICAO/PECASUS-style indicators this dashboard uses"):
        st.markdown(
            """
            Available, derived, or proxied from SERENE-only inputs:

            - Vertical TEC: directly from AIDA TEC/vTEC.
            - Post-Storm Depression: derived from AIDA MUF3000F2 against a
              same-UTC 30-day baseline when Full ICAO-style mode loads it.
            - Auroral Absorption: shown only as a global Kp-based proxy.
            """
        )
    with st.expander("How Vertical TEC risk is classified"):
        st.markdown(
            """
            TEC category thresholds are applied to each grid cell:

            - OK: TEC < 125 TECU
            - MODERATE: 125 <= TEC < 175 TECU
            - SEVERE: TEC >= 175 TECU
            """
        )
    with st.expander("How Post-Storm Depression is calculated from MUF3000F2"):
        st.markdown(
            """
            MUF3000F2 is not classified by its absolute MHz value. The dashboard
            first calculates:

            `PSD % = max(0, (reference_MUF3000F2 - current_MUF3000F2) / reference_MUF3000F2 * 100)`

            The reference is the existing 30-day same-UTC AIDA baseline when it
            can be loaded. PSD thresholds are:

            - OK: PSD < 30%
            - MODERATE: 30% <= PSD < 50%
            - SEVERE: PSD >= 50%

            PSD is only activated when Kp reached at least 6 during the previous
            96 hours. If Kp history is incomplete, PSD is UNAVAILABLE. If the Kp
            storm gate is inactive, PSD is shown as OK with that limitation stated.
            """
        )
    with st.expander("Why Kp/ap are not plotted as regional risk cells"):
        st.markdown(
            """
            Kp and ap are global planetary geomagnetic indices. They are useful
            as storm context and as a global HF proxy, but they do not contain
            latitude/longitude grid cells. Mapping them as regional cells would
            falsely imply spatial information that is not present in the data.
            """
        )
    with st.expander("Research prototype disclaimer"):
        st.warning(
            "This is an academic research prototype and must not be used for real "
            "operational aviation decision-making. It is not an official ICAO or "
            "PECASUS warning system."
        )


def _render_main(params: dict) -> None:
    st.title("Aviation Space Weather Dashboard")
    st.caption(
        "SERENE-only ICAO-style research monitoring. Forecast source: SERENE "
        "official forecast when available; otherwise dashboard-generated forecast."
    )

    _render_cloud_api_hint()

    bundle: IcaoProductBundle = st.session_state.icao_bundle
    if st.session_state.data.empty and bundle.products.empty:
        _render_empty_state()
        st.markdown("---")
        _render_connection_panel()
        return

    df = st.session_state.data
    alerts = st.session_state.alerts
    summary = st.session_state.icao_summary

    _render_overall_risk_cards(summary)
    st.markdown("---")
    _render_pecasus_summary_table()
    st.markdown("---")
    _render_categorical_risk_map()
    st.markdown("---")
    if bundle.status.ok:
        _render_research_messages(summary, params)
    else:
        st.info("Research messages require a successful SERENE AIDA analysis state.")
    st.markdown("---")
    if not df.empty:
        _render_raw_value_maps(df)
        st.markdown("---")
        _render_hf_propagation_case_study(df)
        st.markdown("---")
    _render_global_indices(df)
    st.markdown("---")
    _render_explanation_panels()
    st.markdown("---")
    _render_connection_panel()
    st.markdown("---")
    _render_trial_cache_export(params)
    st.markdown("---")
    _render_forecast_request_audit(summary)
    st.markdown("---")
    if not df.empty:
        _render_data_views(df, alerts)


def main() -> None:
    _init_state()
    _apply_pending_time_range()
    _inject_dashboard_css()
    params = _render_sidebar()
    _render_main(params)


if __name__ == "__main__":
    main()
