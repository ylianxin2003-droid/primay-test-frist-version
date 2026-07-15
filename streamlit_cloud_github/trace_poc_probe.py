"""Small Trace readiness probe for the HF communication case study.

This script intentionally does not create ray paths. It checks whether the
optional Trace package is importable and prints the engineering inputs still
needed before the Streamlit dashboard can expose experimental ray tracing.
"""

from __future__ import annotations

import importlib.util
import json
import platform


REQUIRED_AIDA_TO_TRACE_INPUTS = [
    "route-aligned electron density versus altitude",
    "altitude grid definition and units",
    "frequency and launch elevation sweep",
    "geomagnetic field grid",
    "validated coordinate conversion",
]


def trace_environment_status() -> dict:
    """Return dependency and input-readiness status for a Trace proof of concept."""
    spec = importlib.util.find_spec("hfpytrace")
    return {
        "python_version": platform.python_version(),
        "hfpytrace_importable": spec is not None,
        "current_dashboard_mode": "MUF/PSD route-level proxy",
        "trace_mode_status": "not enabled",
        "missing_inputs": REQUIRED_AIDA_TO_TRACE_INPUTS,
        "scientific_guardrail": (
            "Do not expose ray paths until an AIDA-to-Trace electron-density "
            "profile adapter has been validated."
        ),
    }


def main() -> int:
    print(json.dumps(trace_environment_status(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
