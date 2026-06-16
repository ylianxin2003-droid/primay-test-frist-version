"""Forecast-specific Plotly visualisations."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from forecast_engine import FORECAST_RISK_COLORS, aggregate_forecast_for_map


def create_risk_forecast_map(
    forecast: pd.DataFrame,
    horizon: str = "Now",
    title: str | None = None,
) -> go.Figure:
    """Create a weather-style colour-coded risk map."""
    mapped = aggregate_forecast_for_map(forecast, horizon=horizon)
    if mapped.empty:
        fig = go.Figure()
        fig.add_annotation(
            text=f"No mappable forecast risk data for {horizon}.",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
        )
        fig.update_layout(template="plotly_white", height=520)
        return fig

    fig = px.scatter_geo(
        mapped,
        lat="lat",
        lon="lon",
        color="risk_level",
        size="marker_size",
        hover_name="driver",
        hover_data={
            "lat": ":.2f",
            "lon": ":.2f",
            "risk_level": True,
            "risk_probability_pct": ":.1f",
            "confidence_pct": ":.1f",
            "predicted_value": ":.2f",
            "marker_size": False,
        },
        color_discrete_map=FORECAST_RISK_COLORS,
        category_orders={"risk_level": ["Normal", "Watch", "Warning", "Severe"]},
        title=title or f"Risk forecast map ({horizon})",
        projection="natural earth",
    )
    fig.update_traces(
        marker=dict(
            line=dict(width=0.8, color="rgba(30, 30, 30, 0.55)"),
            opacity=0.82,
        )
    )
    fig.update_geos(
        showcoastlines=True,
        coastlinecolor="gray",
        showland=True,
        landcolor="rgb(236, 238, 240)",
        showocean=True,
        oceancolor="rgb(226, 238, 248)",
    )
    fig.update_layout(
        template="plotly_white",
        height=560,
        legend_title_text="Forecast risk",
        margin=dict(l=0, r=0, t=55, b=0),
    )
    return fig
