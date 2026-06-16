# Aviation Space Weather Risk Forecast Dashboard

Streamlit dashboard for a postgraduate dissertation prototype using live
SERENE API data and AIDA/TOMIRIS model outputs.

The app is designed as an API-only aviation space-weather monitoring and
short-horizon risk forecasting system. It does not load or store local sample
datasets. Each dashboard refresh requests data from SERENE, converts the API
response into a standard long-form table, generates prototype advisories, and
builds weather-style risk maps.

> Academic prototype only. These advisories are not official ICAO warnings and
> must not be used for operational aviation decision-making.

## Core Features

- API-only data access through SERENE `/api/calc/` and online Kp/ap resources.
- Configurable latitude/longitude bounding box and grid step for dense map
  sampling.
- ICAO-style prototype risk advisories for GNSS, HF communication, ionospheric
  disturbance, and geomagnetic storm risk.
- Weather-style risk forecast horizons: `Now`, `+1h`, `+3h`, and `+6h`.
- Colour-coded risk forecast map:
  - green = Normal
  - yellow = Watch
  - orange = Warning
  - red = Severe
- Forecast table with probability, confidence, driver variable, predicted
  value, and explanation.
- No hardcoded API token. Secrets are read from Streamlit Cloud Secrets, local
  `.env`, or environment variables.

## Research Architecture

```text
SERENE API
  -> grid sampling over selected region
  -> standardised DataFrame: time, lat, lon, variable, value, model
  -> alert_engine.py: threshold-based prototype advisories
  -> forecast_engine.py: short-horizon risk score, probability, confidence
  -> visualisation.py: time series, raw variable maps, risk forecast map
  -> app.py: Streamlit dashboard
```

The forecast layer is intentionally transparent for dissertation assessment.
It uses threshold-informed scoring plus short-term trend extrapolation when
multiple timestamps are available. If only a single API sample is available,
it falls back to persistence-style nowcasting. Kp/ap values are treated as a
global storm baseline and can raise the regional map risk.

## Repository Layout

```text
app.py                 Streamlit entry point
config.py              Secrets and environment configuration
serene_client.py       SERENE API client and response parser
data_loader.py         API-only data loading pipeline
alert_engine.py        Prototype risk advisory rules
forecast_engine.py     Short-horizon risk forecasting
visualisation.py       Plotly charts and maps
requirements.txt       Streamlit Cloud dependencies
tests/                 Unit tests for loader, maps, alerts, forecast
```

## Streamlit Cloud Deployment

1. Open [https://share.streamlit.io](https://share.streamlit.io).
2. Create a new app from this GitHub repository.
3. Use `streamlit_cloud_github/app.py` as the main file path if deploying from
   the repository root.
4. Add secrets in the Streamlit Cloud app settings:

```toml
SERENE_API_BASE_URL = "https://spaceweather.bham.ac.uk"
SERENE_API_TOKEN = "your-api-token-here"
SERENE_API_TIMEOUT = "30"
SERENE_AUTH_SCHEME = "Token"
```

5. Reboot the app after saving secrets.

## Local Development

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your SERENE token
python -m streamlit run app.py
```

Run tests:

```bash
python -m unittest discover -s tests -v
```

## Streamlit Cloud: Good Final Demo or Not?

Streamlit Cloud is a good final dissertation demo platform because it is simple
to deploy, integrates directly with GitHub, and supports secure secrets for the
SERENE API token.

Its limitations are important for the written report:

- Apps can sleep after inactivity, so open the demo before the presentation.
- Free/shared resources are limited, so very dense API grids may become slow.
- Long synchronous API batches can hit timeouts or make the UI feel frozen.
- It is less suitable for scheduled background jobs, heavy caching, or many
  simultaneous users.

Recommended dissertation setup:

- Use Streamlit Cloud for the assessed interactive demo.
- Keep a local backup run and a short screen recording for presentation safety.
- Use conservative default sampling, for example 50 API calls per refresh.
- Add a server backend only if you need high-density grid sampling, async batch
  requests, scheduled refreshes, or multi-user reliability.

## When a Server Backend Helps

A small backend service is useful when the project moves beyond a demo:

- async SERENE API batch requests over hundreds of grid points;
- rate limiting and retry queues;
- short TTL response caching to avoid repeated identical API calls;
- precomputed forecast tiles for faster map rendering;
- monitoring and logs for dissertation evaluation.

This does not require storing local research datasets. The backend can keep
only temporary API response cache entries with a short TTL.
