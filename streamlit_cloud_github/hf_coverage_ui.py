"""Streamlit UI for the HF communication engineering case study."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from data_loader import LoadStatus
from hf_coverage import (
    DEFAULT_SWEEP_FREQUENCIES,
    TARGET_PRESETS,
    TRANSMITTER_PRESETS,
    build_frequency_sweep,
    build_hf_engineering_case,
    create_hf_coverage_map,
)


def _source_label(status: LoadStatus) -> str:
    """Return the reader-facing label for a loaded data source."""
    return {
        "api": "Live SERENE API",
        "trial_cache": "Cached trial output",
        "indices": "SERENE global indices only",
        "none": "No data",
    }.get(status.source, status.source)


def render_hf_propagation_case_study(df: pd.DataFrame) -> None:
    """Render the HF communication impact and decision-support case study."""
    st.subheader("Engineering Impact: HF Communication Coverage")
    st.caption(
        "Phase 1 uses a simplified MUF-based coverage proxy to connect PSD/MUF "
        "changes to possible HF communication impact. Phase 2 is an experimental "
        "Trace HF ray-tracing integration path; no ray paths are fabricated here. "
        "This is not an operational HF communication coverage product."
    )

    mode_col, source_col = st.columns([1.3, 1])
    with mode_col:
        st.info(
            "Phase 1: MUF-based coverage proxy / MUF-threshold demonstration. "
            "Phase 2: experimental Trace ray-tracing integration status is documented below."
        )
    with source_col:
        status: LoadStatus = st.session_state.status
        st.metric("Data source", _source_label(status))
        st.caption(
            "AIDA quiet vs storm comparison is used when `reference_value` exists; "
            "otherwise the manual PSD slider is used as fallback."
        )

    control_col, psd_col, tx_col, target_col = st.columns(4)
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
            "Fallback storm MUF depression (%)",
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
    with tx_col:
        tx_preset = st.selectbox(
            "Transmitter preset",
            ["UK transmitter", "Custom transmitter"],
            key="hf_transmitter_preset",
        )
    with target_col:
        target_preset = st.selectbox(
            "Target preset",
            ["North Atlantic corridor", "New York JFK", "Custom target"],
            index=1,
            key="hf_target_preset",
        )

    transmitter = dict(TRANSMITTER_PRESETS["UK transmitter"])
    if tx_preset == "Custom transmitter":
        tx_custom_col1, tx_custom_col2 = st.columns(2)
        with tx_custom_col1:
            transmitter["lat"] = st.number_input(
                "Custom transmitter latitude", -90.0, 90.0, 52.0, 0.1,
                key="hf_custom_tx_lat",
            )
        with tx_custom_col2:
            transmitter["lon"] = st.number_input(
                "Custom transmitter longitude", -180.0, 180.0, -1.5, 0.1,
                key="hf_custom_tx_lon",
            )
        transmitter["name"] = "Custom transmitter"

    target = dict(TARGET_PRESETS["North Atlantic corridor"])
    if target_preset == "New York JFK":
        target = dict(TARGET_PRESETS["New York JFK"])
    elif target_preset == "Custom target":
        target_custom_col1, target_custom_col2 = st.columns(2)
        with target_custom_col1:
            target["lat"] = st.number_input(
                "Custom target latitude", -90.0, 90.0, 40.6, 0.1,
                key="hf_custom_target_lat",
            )
        with target_custom_col2:
            target["lon"] = st.number_input(
                "Custom target longitude", -180.0, 180.0, -73.8, 0.1,
                key="hf_custom_target_lon",
            )
        target["name"] = "Custom target"

    time_cols = st.columns(3)
    status = st.session_state.status
    with time_cols[0]:
        st.text_input(
            "Quiet/background analysis time",
            value="AIDA 30-day same-UTC reference" if "reference_value" in df.columns else "Manual PSD fallback",
            disabled=True,
            key="hf_quiet_time_display",
        )
    with time_cols[1]:
        st.text_input(
            "Storm analysis time",
            value=str(status.metadata.get("analysis_time", "loaded analysis time")),
            disabled=True,
            key="hf_storm_time_display",
        )
    with time_cols[2]:
        st.text_input(
            "Coverage data mode",
            value=_source_label(status),
            disabled=True,
            key="hf_data_mode_display",
        )

    engineering_case = build_hf_engineering_case(
        df,
        frequency_mhz=frequency_mhz,
        transmitter=transmitter,
        target=target,
        route_samples=33,
        assumed_psd_percent=psd_percent,
    )
    if engineering_case.grid.empty:
        st.info("No spatial MUF3000F2 grid is available for the HF communication case study.")
        return

    summary = engineering_case.summary
    metric_cols = st.columns(4)
    metric_cols[0].metric("Selected frequency", f"{summary['frequency_mhz']:.1f} MHz")
    metric_cols[1].metric("Quiet coverage", f"{summary['quiet_usable_grid_pct']:.0f}%")
    metric_cols[2].metric("Storm coverage", f"{summary['storm_usable_grid_pct']:.0f}%")
    metric_cols[3].metric("Coverage loss", f"{summary['regional_coverage_loss_pct_points']:.0f} pp")
    route_cols = st.columns(5)
    route_cols[0].metric("Quiet route availability", f"{summary['quiet_route_available_pct']:.0f}%")
    route_cols[1].metric("Storm route availability", f"{summary['storm_route_available_pct']:.0f}%")
    route_cols[2].metric("Route coverage reduction", f"{summary['route_coverage_loss_pct_points']:.0f} pp")
    route_cols[3].metric("Degraded route points", int(summary["degraded_route_points"]))
    route_cols[4].metric("Longest degraded segment", f"{summary['longest_degraded_segment_km']:.0f} km")
    st.caption(f"Comparison mode: {summary['comparison_mode']}")

    st.markdown("**Engineering interpretation**")
    st.info(summary["interpretation"])

    quiet_tab, storm_tab, change_tab, route_tab, sweep_tab = st.tabs([
        "Quiet map",
        "Storm map",
        "Coverage change",
        "Route samples",
        "Frequency sweep",
    ])
    with quiet_tab:
        st.plotly_chart(
            create_hf_coverage_map(
                engineering_case.grid,
                transmitter,
                target,
                route=engineering_case.route.to_dict("records"),
                title=f"Quiet/background potential HF coverage at {summary['frequency_mhz']:.1f} MHz",
                map_mode="quiet",
            ),
            width="stretch",
        )
    with storm_tab:
        st.plotly_chart(
            create_hf_coverage_map(
                engineering_case.grid,
                transmitter,
                target,
                route=engineering_case.route.to_dict("records"),
                title=f"Storm-time potential HF coverage at {summary['frequency_mhz']:.1f} MHz",
                map_mode="storm",
            ),
            width="stretch",
        )
    with change_tab:
        st.plotly_chart(
            create_hf_coverage_map(
                engineering_case.grid,
                transmitter,
                target,
                route=engineering_case.route.to_dict("records"),
                title=f"Coverage change at {summary['frequency_mhz']:.1f} MHz",
                map_mode="change",
            ),
            width="stretch",
        )
    with route_tab:
        st.dataframe(engineering_case.route, width="stretch", hide_index=True)
    with sweep_tab:
        sweep = build_frequency_sweep(engineering_case, DEFAULT_SWEEP_FREQUENCIES)
        st.caption("Research comparison only. This table does not recommend operational frequencies.")
        st.dataframe(sweep, width="stretch", hide_index=True)
        best = sweep[sweep["highest_storm_route_availability_in_research_case"]]
        if not best.empty:
            row = best.iloc[0]
            st.info(
                f"{row['frequency_mhz']:.1f} MHz has the highest storm route "
                "availability in this research comparison. This is not an "
                "operational frequency recommendation."
            )

    with st.expander("How to interpret this HF case study"):
        st.markdown(
            """
            MUF is the maximum usable frequency supported by the ionosphere for
            a simplified path assumption. If the selected HF frequency is above
            the local MUF, that frequency is treated as not usable in this
            demonstration.

            When AIDA `reference_value` is available, the quiet/background side
            uses the real AIDA same-UTC baseline and the storm side uses the
            loaded analysis MUF3000F2. The PSD percentage is calculated as:

            `PSD % = max(0, (quiet_MUF - storm_MUF) / quiet_MUF * 100)`

            If that reference is missing, the manual PSD slider is used only as
            a fallback demonstration mode and is labelled as an assumption.

            Trace can support a more physical HF ray-tracing workflow in future
            work. This dashboard section is a stable engineering demonstration
            of the PSD communication effect, not a full propagation solver.

            Research prototype only. Not suitable for operational aviation
            decision-making.
            """
        )
    with st.expander("Trace integration status"):
        st.markdown(
            """
            Phase 2 is reserved for experimental Trace ray-tracing integration.
            The current dashboard does not generate Trace ray paths. The technical
            note in `docs/Trace_Integration_Report.md` records the required inputs,
            AIDA mapping, and remaining blockers. The optional
            `prototypes/hfpytrace_uk_north_atlantic_poc.py` script records a
            standalone feasibility probe; it is not a dashboard propagation
            product.
            """
        )
