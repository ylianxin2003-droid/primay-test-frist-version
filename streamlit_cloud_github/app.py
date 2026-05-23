"""
Aviation Space Weather Monitoring & ICAO-style Risk Alert Dashboard.

Run::

    streamlit run app.py
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from alert_engine import DISCLAIMER, generate_alerts, generate_overall_risk
from config import SERENE_API_TOKEN, reload_config, validate_config
from data_loader import LoadStatus, load_data, resolve_local_file
from serene_client import MAX_GRID_POINTS, SereneClient
from visualisation import (
    create_alert_summary,
    create_alert_timeline,
    create_map_plot,
    create_time_series_plot,
)

st.set_page_config(
    page_title="Aviation Space Weather Dashboard",
    page_icon="🛩️",
    layout="wide",
    initial_sidebar_state="expanded",
)

reload_config()  # Load Streamlit Cloud secrets after st is initialised

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

if "data" not in st.session_state:
    st.session_state.data = pd.DataFrame()
if "status" not in st.session_state:
    st.session_state.status = LoadStatus()
if "alerts" not in st.session_state:
    st.session_state.alerts = pd.DataFrame()
if "api_connected" not in st.session_state:
    st.session_state.api_connected = None
if "api_message" not in st.session_state:
    st.session_state.api_message = "Not tested yet."
if "config_warnings" not in st.session_state:
    st.session_state.config_warnings = validate_config()

# Auto-load bundled sample data on first visit (works without SERENE API).
if "bootstrap_done" not in st.session_state:
    _boot_df, _boot_status = load_data(source="local")
    if not _boot_df.empty:
        st.session_state.data = _boot_df
        st.session_state.status = _boot_status
        st.session_state.alerts = generate_alerts(_boot_df)
    st.session_state.bootstrap_done = True


def _render_cloud_api_hint() -> None:
    """Explain why SERENE API may be unavailable on Streamlit Cloud."""
    if SERENE_API_TOKEN:
        return
    st.info(
        "**SERENE API 未配置。** 当前展示的是仓库内的样例数据（可正常演示）。\n\n"
        "若要在云端使用实时 API：Streamlit Cloud → 你的应用 → **Settings → Secrets**，粘贴：\n\n"
        "```toml\n"
        "SERENE_API_BASE_URL = \"https://spaceweather.bham.ac.uk\"\n"
        "SERENE_API_TOKEN = \"你的token\"\n"
        "SERENE_API_TIMEOUT = \"30\"\n"
        "SERENE_AUTH_SCHEME = \"Token\"\n"
        "```\n\n"
        "保存后点击 **Reboot app**。"
    )


def _render_sidebar() -> dict:
    st.sidebar.markdown("# 🛩️ SERENE AIDA")
    st.sidebar.markdown("*Aviation Space Weather Monitor*")
    st.sidebar.markdown("---")

    params: dict = {}

    if st.session_state.config_warnings:
        with st.sidebar.expander("Configuration issues", expanded=True):
            for msg in st.session_state.config_warnings:
                st.warning(msg)

    params["source"] = st.sidebar.selectbox(
        "Data source",
        ["local", "api"],
        format_func=lambda s: "SERENE API" if s == "api" else "Local sample file",
        help="Local file loads instantly. SERENE API calls /api/calc/ per grid point.",
    )

    params["model"] = st.sidebar.selectbox("Model", ["AIDA", "TOMIRIS"])

    now = datetime.now(timezone.utc)
    st.sidebar.markdown("#### Time range")
    params["start_time"] = st.sidebar.text_input(
        "Start datetime (ISO 8601)",
        value=(now - timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%S"),
    )
    params["end_time"] = st.sidebar.text_input(
        "End datetime (ISO 8601)",
        value=now.strftime("%Y-%m-%dT%H:%M:%S"),
    )

    avail_vars = ["TEC", "MUF3000", "foF2", "MUF3000_depression", "foF2_depression"]
    selected_vars = st.sidebar.multiselect(
        "Variable selection",
        options=avail_vars,
        default=["TEC"],
    )
    params["variables"] = selected_vars or None

    st.sidebar.markdown("#### Region selection (API mode)")
    with st.sidebar.expander("Bounding box & grid step", expanded=params["source"] == "api"):
        lat_min = st.number_input("Lat min", value=45.0, min_value=-90.0, max_value=90.0)
        lat_max = st.number_input("Lat max", value=60.0, min_value=-90.0, max_value=90.0)
        lon_min = st.number_input("Lon min", value=-15.0, min_value=-180.0, max_value=180.0)
        lon_max = st.number_input("Lon max", value=15.0, min_value=-180.0, max_value=180.0)
        params["grid_step"] = st.slider("Grid step (degrees)", 2.0, 30.0, 5.0, 1.0)
        est_n, _, _ = SereneClient.estimate_grid_points(
            lat_min, lat_max, lon_min, lon_max, params["grid_step"], params["grid_step"],
        )
        st.caption(
            f"≈ {est_n} API call(s) (max {MAX_GRID_POINTS}). "
            "Global region can take many minutes."
        )

    params["region"] = {
        "lat_min": lat_min,
        "lat_max": lat_max,
        "lon_min": lon_min,
        "lon_max": lon_max,
    }

    params["local_file"] = st.sidebar.text_input(
        "Local fallback file path",
        value=str(resolve_local_file()),
    )

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

    st.sidebar.markdown("---")
    if st.sidebar.button("Load / Refresh data", type="primary", use_container_width=True):
        _do_load(params)

    st.sidebar.caption(
        "Prototype research system — not for operational aviation decision-making."
    )
    return params


def _do_load(params: dict) -> None:
    progress_bar = st.progress(0.0, text="Preparing…")
    progress_state = {"done": 0, "total": 1}

    def _on_api_progress(done: int, total: int) -> None:
        progress_state["done"] = done
        progress_state["total"] = max(total, 1)
        progress_bar.progress(
            done / progress_state["total"],
            text=f"SERENE API: point {done}/{total}…",
        )

    try:
        df, status = load_data(
            source=params["source"],
            model=params["model"],
            start_time=params.get("start_time"),
            end_time=params.get("end_time"),
            variables=params.get("variables"),
            region=params.get("region"),
            local_file=params.get("local_file"),
            grid_step=params.get("grid_step", 5.0),
            progress_callback=_on_api_progress if params["source"] == "api" else None,
        )
        progress_bar.progress(1.0, text="Generating advisories…")
        st.session_state.data = df
        st.session_state.status = status
        st.session_state.alerts = generate_alerts(df) if not df.empty else pd.DataFrame()
    finally:
        progress_bar.empty()


def _source_label(status: LoadStatus) -> str:
    mapping = {
        "api": "SERENE API",
        "local": "Local sample file",
        "local_fallback": "Local sample file (API fallback)",
        "none": "No data",
    }
    return mapping.get(status.source, status.source)


def _render_connection_panel() -> None:
    st.subheader("SERENE API & data status")

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.session_state.api_connected is True:
            st.success(f"API: {st.session_state.api_message}")
        elif st.session_state.api_connected is False:
            st.warning(f"API: {st.session_state.api_message}")
        else:
            st.info("API: not tested — use sidebar **Test SERENE API connection**.")

    status: LoadStatus = st.session_state.status
    with c2:
        st.metric("Current data source", _source_label(status))

    with c3:
        st.metric("Rows loaded", f"{len(st.session_state.data):,}")

    if status.message:
        if status.source == "local_fallback":
            st.warning(status.message)
        elif status.ok:
            st.info(status.message)
        else:
            st.error(status.message)

    for warn in status.warnings:
        st.warning(warn)


def _render_main(params: dict) -> None:
    st.title("Aviation Space Weather Dashboard")
    st.caption(
        "ICAO-style prototype risk monitor — SERENE real-time data & AIDA/TOMIRIS models"
    )

    _render_cloud_api_hint()
    _render_connection_panel()
    st.markdown("---")

    if st.session_state.data.empty:
        st.info(
            "Select a data source in the sidebar and click **Load / Refresh data** "
            "to begin. If SERENE API fails, the dashboard automatically uses the "
            "local fallback file without crashing."
        )
        with st.expander("Quick start"):
            st.markdown(
                """
                1. Copy `.env.example` to `.env` and set `SERENE_API_BASE_URL` and
                   `SERENE_API_TOKEN` (auth uses official `Token` scheme by default).
                2. Click **Test SERENE API connection**, then **Load / Refresh data**.
                4. Advisories shown here are **prototype advisories**, not official ICAO warnings.
                """
            )
        return

    df = st.session_state.data
    alerts = st.session_state.alerts

    # ── ICAO-style risk alert panel ─────────────────────────────────────────
    st.subheader("ICAO-style prototype risk advisories")
    overall, summary = generate_overall_risk(alerts)
    emoji = {"Normal": "🟢", "Watch": "🟡", "Warning": "🟠", "Severe": "🔴"}
    st.markdown(f"**Overall risk:** {emoji.get(overall, '⚪')} {overall}")
    st.caption(summary)
    st.caption(DISCLAIMER)

    if alerts.empty:
        st.success("No active prototype advisories — parameters within normal range.")
    else:
        col_a, col_b = st.columns(2)
        with col_a:
            st.plotly_chart(
                create_alert_summary(alerts),
                use_container_width=True,
                key="alert_summary_chart",
            )
        with col_b:
            st.plotly_chart(
                create_alert_timeline(alerts),
                use_container_width=True,
                key="alert_timeline_chart",
            )
        show_cols = [
            c for c in (
                "timestamp", "region", "alert_type", "risk_level",
                "reason", "possible_aviation_impact", "interpretation",
            )
            if c in alerts.columns
        ]
        st.dataframe(alerts[show_cols], use_container_width=True, height=220)

    st.markdown("---")

    # ── Visualisations ──────────────────────────────────────────────────────
    st.subheader("Data preview")
    st.dataframe(df.head(100), use_container_width=True)

    var_options = sorted(df["variable"].dropna().unique()) if "variable" in df.columns else []
    selected_var = st.selectbox("Variable for plots", var_options or [None])

    col_ts, col_map = st.columns(2)
    with col_ts:
        st.subheader("Time series")
        st.plotly_chart(
            create_time_series_plot(df, variable=selected_var),
            use_container_width=True,
            key="overview_time_series",
        )
    with col_map:
        st.subheader("Map / scatter (lat/lon)")
        st.plotly_chart(
            create_map_plot(df, variable=selected_var),
            use_container_width=True,
            key="overview_map",
        )

    with st.expander("Detailed tabs (GNSS / HF / raw data)"):
        tab_gnss, tab_hf, tab_raw = st.tabs(["GNSS", "HF Communication", "Raw data"])

        with tab_gnss:
            gnss_vars = [v for v in var_options if "tec" in v.lower()]
            for i, var in enumerate(gnss_vars or var_options[:1]):
                st.plotly_chart(
                    create_map_plot(df, variable=var, title=f"GNSS — {var}"),
                    use_container_width=True,
                    key=f"gnss_map_{var}_{i}",
                )

        with tab_hf:
            hf_vars = [v for v in var_options if "muf" in v.lower() or "fof2" in v.lower()]
            for i, var in enumerate(hf_vars or var_options[:1]):
                st.plotly_chart(
                    create_map_plot(df, variable=var, title=f"HF — {var}"),
                    use_container_width=True,
                    key=f"hf_map_{var}_{i}",
                )

        with tab_raw:
            st.json({
                "source": st.session_state.status.source,
                "message": st.session_state.status.message,
                "warnings": st.session_state.status.warnings,
                "metadata": st.session_state.status.metadata,
            })
            st.download_button(
                "Download CSV",
                data=df.to_csv(index=False),
                file_name=f"space_weather_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
            )


def main() -> None:
    params = _render_sidebar()
    _render_main(params)


if __name__ == "__main__":
    main()
