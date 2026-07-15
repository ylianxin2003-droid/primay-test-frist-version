# Trace Integration Technical Note

## Purpose

Supervisor feedback asked for stronger engineering context by demonstrating how
Post-Storm Depression (PSD) affects HF communications. The dashboard now
implements a route-level MUF-based coverage proxy. This note records what would
be required to move from the proxy to an experimental Trace ray-tracing mode.

This is a research planning note. It does not claim that the dashboard currently
produces Trace ray paths.

## Trace Capability Summary

Trace documentation describes `hfpytrace` as a Python-first workflow for
ionospheric density modelling, PHaRLAP coupling, and 2D/3D HF ray-path analysis:

- Home: https://pytrace.readthedocs.io/en/latest/
- Installation: https://pytrace.readthedocs.io/en/latest/user/install/
- Configuration: https://pytrace.readthedocs.io/en/latest/user/configuration/
- Examples: https://pytrace.readthedocs.io/en/latest/examples/
- API overview: https://pytrace.readthedocs.io/en/latest/dev/

The documentation marks Trace as beta software. Installation guidance targets a
clean Python 3.11 environment and `pip install hfpytrace`. Optional mapping
workflows may require `cartopy`.

The repository also includes `streamlit_cloud_github/trace_poc_probe.py`. This
is a dependency and input-readiness probe only. It does not generate Trace ray
paths and should not be presented as a propagation result.

## Required Inputs For Trace-Style Ray Tracing

Based on the Trace configuration and API documentation, an experimental 2D or
3D run would need:

- transmitter/origin latitude, longitude and launch height
- target endpoint, route bearing, or receiver search area
- HF operating frequency in MHz/Hz
- elevation angle range for ray launch
- azimuth/bearing range for 3D fan or homing workflows
- altitude grid start, end and step
- route/path axis or 3D geographic ionosphere grid
- electron density as a function of altitude and route position
- geomagnetic field grid
- collision/neutral atmosphere model if absorption or PHaRLAP workflows are used
- ray-control settings such as number of hops, threshold, Earth radius and max
  ground range

Trace examples often use IRI, NRLMSISE and IGRF/geomagnetic helpers to build
those inputs before tracing.

## Mapping From Current AIDA Outputs

Current dashboard inputs:

- AIDA `MUF3000F2`
- AIDA `TEC` / `vTEC`
- AIDA `foF2`, `NmF2`, `hmF2` when requested by lower-level adapters
- SERENE Kp/ap as global context
- derived 30-day same-UTC MUF reference and `psd_percent`

Current dashboard route-level output:

- quiet/background MUF grid
- storm/current MUF grid
- PSD percentage per grid cell
- nearest-grid MUF values sampled along a great-circle route
- route availability and degraded segment metrics

Potential Trace mapping:

- `foF2`, `NmF2`, and `hmF2` may help parameterise a simplified F-layer profile.
- `MUF3000F2` is useful for engineering interpretation but is not itself an
  altitude-resolved electron-density profile.
- `TEC` is vertically integrated and cannot alone define a ray-tracing density
  profile.
- AIDA raw HDF5 states may contain richer information, but the current dashboard
  only exposes calculated surface/grid products through `AIDAState.calc()`.

## Missing Information

Full Trace integration is not implemented yet because the current dashboard does
not have a verified converter from SERENE/AIDA raw state to Trace's required
altitude-resolved profile/grid format.

Key missing pieces:

- confirmed AIDA access to electron density versus altitude along a route
- conversion from AIDA coordinates and units to Trace profile/grid conventions
- validation that the converted profile is physically meaningful
- collision/neutral atmosphere inputs for absorption-sensitive runs
- agreed elevation/azimuth sweep ranges for the UK-to-North-Atlantic case
- runtime limits suitable for Streamlit Cloud

## Dependency And Runtime Considerations

- Trace targets Python 3.11. The Streamlit deployment should stay on Python 3.11
  if Trace is added later.
- `hfpytrace` and optional geospatial dependencies should not be added to the
  production dashboard until a small local proof of concept works.
- Some PHaRLAP workflows may add external or platform-specific complexity.
- Trace is beta, so API names and configuration fields may change.

## Feasibility Decision

Full Trace ray tracing is technically plausible but not ready for direct
integration in the dashboard without an AIDA-to-Trace density-profile adapter.

Current decision:

- keep the improved MUF/PSD route-level proxy in the dashboard
- label it as a simplified MUF-based coverage proxy
- document Trace as Phase 2 experimental work
- do not generate fake ray paths or claim operational propagation modelling

## Minimal Proof-Of-Concept Steps

1. Install `hfpytrace` in a clean Python 3.11 virtual environment.
2. Run `python trace_poc_probe.py` to confirm whether `hfpytrace` is importable
   and to list the missing AIDA-to-Trace inputs.
3. Run a documented Trace IRI 2D example without SERENE/AIDA input.
4. Extract or construct one route-aligned altitude electron-density slice from
   an AIDA raw state.
5. Confirm units, coordinate convention and grid shape.
6. Run one quiet and one storm profile through a fixed frequency/elevation
   sweep.
7. Compare outputs: ray paths, turning altitude, landing points, ground range
   and target reachability.
8. Only then expose an "Experimental Trace integration" section in Streamlit.

Until those steps are complete, dashboard output must remain:

> Research prototype only. Not suitable for operational aviation
> decision-making.
