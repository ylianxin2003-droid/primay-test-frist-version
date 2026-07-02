# Aviation Space Weather Dashboard Based on SERENE AIDA Data

This repository contains a Streamlit research prototype that converts SERENE
AIDA ionospheric model outputs into aviation-oriented space weather risk
information.

The main app is in `streamlit_cloud_github/app.py`.

## Aim

Convert SERENE AIDA scientific outputs into aviation-oriented risk information,
including GNSS and HF communication risk categories, maps, summary tables, and
TEST SPWX research messages.

## Main Features

- SERENE AIDA TEC and MUF3000F2 loading
- Kp/ap geomagnetic context
- GNSS risk from Vertical TEC
- HF COM risk from Post-Storm Depression
- ICAO/PECASUS-style summary table
- Categorical risk maps
- TEST SPWX research messages
- Global default grid for aviation-scale awareness
- Cached trial outputs for faster demonstration
- Live SERENE API mode for new analysis times

## Limitations

- Research prototype only
- Not for operational aviation use
- No direct radiation dose product
- No S4 / sigma-phi scintillation input from SERENE-only data
- No direct PCA / SWF product from SERENE-only data
- Forecasts may be official SERENE forecasts or clearly labelled
  dashboard-generated fallback predictions

## Cached Trial Outputs

Cached processed outputs for selected demo / validation periods can be stored in
`streamlit_cloud_github/data/trial_outputs/`. These files are intended to speed
up presentation and validation without repeating every SERENE download.

Live SERENE API loading remains available for new analysis times. Cached output
files must not contain API tokens, Streamlit secrets, raw credentials, or
personal data.
