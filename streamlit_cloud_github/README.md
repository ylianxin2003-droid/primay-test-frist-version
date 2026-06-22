# Aviation Space Weather Risk Forecast Dashboard

Streamlit dissertation prototype using authenticated SERENE AIDA ionospheric
model outputs. It monitors spatial ionospheric parameters and creates
transparent, rule-based GNSS/HF risk indications.

> Academic prototype only. It is not an official ICAO advisory system and must
> not be used for operational aviation decisions.

## Data flow

```text
Streamlit Cloud Secrets
  -> authenticated SERENE AIDA output catalogue
  -> one param_2d HDF5 download per selected output time
  -> exact local bounding-box/grid sampling in memory
  -> standard DataFrame: time, lat, lon, variable, value, model
  -> threshold alerts + short-term trend/persistence forecast
  -> maps, time series, alert table and global Kp/ap context
```

Changing the map extent or grid spacing does not create extra AIDA downloads.
The full AIDA product is loaded once for each distinct output time, then any
number of requested map points is calculated locally. Start and end times that
select the same output are deduplicated.

## Supported data

- Spatial AIDA parameters: `TEC`, `foF2`, `MUF3000F2`, `NmF2`, `hmF2`.
- Global indices: `Kp` and `ap`, shown as context and time series only.
- Historical event shortcuts begin in 2024, matching the available archive.

Kp is a global three-hour index, so it is deliberately excluded from regional
risk maps. Regional maps use only spatial AIDA variables. High absolute TEC is
also not, by itself, proof of GNSS risk; gradients, anomalies, variability and
scintillation would require additional data and validation.

## Forecast method

The current forecast is a transparent research prototype, not a trained AI
model. With multiple samples it extrapolates the recent local trend to `Now`,
`+1h`, `+3h` and `+6h`, then applies documented thresholds. With one sample it
uses low-confidence persistence. Displayed probability and confidence are
heuristic indicators and are not statistically calibrated probabilities.

## Repository layout

```text
app.py                       Streamlit page and controls
config.py                    Secrets/environment configuration
serene_client.py             Authenticated catalogue/download client
aida_grid.py                 HDF5 validation and exact local interpolation
data_loader.py               Download deduplication and data assembly
alert_engine.py              Rule-based prototype alerts
forecast_engine.py           Trend/persistence risk forecast
visualisation.py             Parameter charts and maps
forecast_visualisation.py    Regional forecast map
tests/                        Automated regression tests
```

## Streamlit Cloud deployment

Add these values under **App settings -> Secrets**:

```toml
SERENE_API_BASE_URL = "https://serene.bham.ac.uk"
SERENE_API_TOKEN = "your-api-token-here"
SERENE_API_TIMEOUT = "30"
SERENE_AUTH_SCHEME = "Token"
```

The client detects a redirect to the website login form and reports it clearly:
a Chrome login session cannot authenticate Streamlit Cloud, so the supplied API
token must have permission to read the AIDA output catalogue and HDF5 download.

## Local development

```bash
pip install -r requirements.txt
cp .env.example .env
python -m streamlit run app.py
python -m unittest discover -s tests -v
```

No local scientific dataset is used as a silent fallback. A failed catalogue or
download request is shown as an API error so that a demo never presents sample
data as live SERENE data.
