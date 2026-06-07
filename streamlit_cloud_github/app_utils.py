"""Small UI helpers for the Streamlit dashboard."""

from __future__ import annotations

from datetime import date, datetime, time


def combine_date_time_iso(date_value: date, time_value: time) -> str:
    """Combine separate Streamlit date/time values into an ISO 8601 string."""
    return datetime.combine(date_value, time_value).strftime("%Y-%m-%dT%H:%M:%S")
