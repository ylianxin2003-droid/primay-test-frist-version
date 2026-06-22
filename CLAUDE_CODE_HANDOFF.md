# Dashboard Project Handoff

## Project purpose

This repository contains a Streamlit research prototype for aviation space-weather monitoring. It downloads SERENE AIDA raw HDF5 states once per requested output time, uses Benjamin Reid's official `aida-ionosphere` interpreter locally, and combines regional ionospheric parameters with global Kp/ap context.

## Current behaviour

- AIDA regional archive dates are restricted to 2024-09-28 or later.
- Historical event table values are verified peak Kp/ap values from the SERENE index resource.
- Historical load ranges stop five minutes before the displayed interval boundary so the following three-hour Kp/ap period is not included.
- Kp and ap are combined into one global geomagnetic advisory.
- Kp/ap never create regional map cells.
- Alert charts support Normal, Watch, Warning, Severe, and NOAA G1–G5 labels.
- Regional forecast maps fit the selected AIDA points and use fixed-size markers.
- `Now` on a forecast means the latest loaded AIDA state, not necessarily present wall-clock time.

## Scientific limitations

- Absolute TEC thresholds are illustrative prototype thresholds, not an operational ICAO warning method.
- TEC gradients, anomalies, variability, and scintillation are more directly related to GNSS degradation than absolute TEC alone.
- AIDA currently supplies absolute foF2 and MUF3000F2. Depression risks require a quiet-time or historical baseline and are not yet calculated.
- Forecast probability and confidence are heuristic outputs from persistence or a short linear trend; they are not statistically calibrated probabilities.
- The dashboard samples requested start/end AIDA states rather than reconstructing every five-minute state in a long interval.

## Local setup

Use Python 3.11, matching Streamlit Cloud:

```bash
cd streamlit_cloud_github
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app.py
```

Create `.streamlit/secrets.toml` locally or configure environment variables using `.env.example`. Never commit or paste the SERENE API token.

## Verification

```bash
cd streamlit_cloud_github
python -m unittest discover -s tests -v
python -m compileall -q .
```

The deployed app is <https://dashboard-project-2026.streamlit.app/>.

