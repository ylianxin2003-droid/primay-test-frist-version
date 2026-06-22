# Aviation Space Weather Risk Forecast Dashboard

Streamlit dissertation prototype using authenticated SERENE AIDA ionospheric
model outputs. It creates transparent, rule-based GNSS/HF risk indications from
spatial ionospheric parameters.

> Academic prototype only. It is not an official ICAO advisory system and must
> not be used for operational aviation decisions.

## Correct API data flow

```text
Streamlit Secrets
  -> GET https://spaceweather.bham.ac.uk/api/download-output/
  -> one raw AIDA HDF5 state per distinct requested time
  -> official AIDAState.readFile() and AIDAState.calc()
  -> exact local bounding-box/grid calculation
  -> time, lat, lon, variable, value, model DataFrame
  -> maps, alerts and short-horizon prototype forecasts
```

Changing the map extent or spacing changes only local calculation and plotting.
It does not create one API request per point. Identical time/latency requests
are deduplicated.

## Upstream scientific implementation

Raw-state interpretation and scientific grid calculation use Benjamin Reid's
MIT-licensed [`breid-phys/aida-ionosphere`](https://github.com/breid-phys/aida-ionosphere)
package, pinned to `v0.1.3`. The authenticated request follows its official
[`downloadOutput` implementation](https://github.com/breid-phys/aida-ionosphere/blob/main/aida/api.py).
Nearby source comments identify every boundary that relies on this contract;
the dashboard does not copy the upstream scientific model implementation.

Supported spatial fields are `TEC`, `foF2`, `MUF3000F2` (upstream
`MUF3000`), `NmF2`, and `hmF2`. Kp/ap are global planetary indices and are
shown only as global context, never as regional map cells.

## Forecast limitations

The forecast is a transparent research prototype, not a trained AI model. It
uses short recent trends when multiple states are available and low-confidence
persistence otherwise. Displayed probability/confidence values are heuristic,
not statistically calibrated. High absolute TEC alone is not proof of GNSS
risk; gradients, anomalies, variability and scintillation need additional data.

## Streamlit Community Cloud deployment

The upstream package requires `pandas<2` and `numpy<2`. Deploy with **Python
3.11**. Streamlit Community Cloud cannot change an existing app's Python version
in place, so preserve the URL and Secrets, delete the existing app, then deploy
it again and select Python 3.11 under **Advanced settings**. See the
[official Streamlit instructions](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app/upgrade-python).

Use `streamlit_cloud_github/app.py` as the entrypoint and configure:

```toml
SERENE_API_BASE_URL = "https://spaceweather.bham.ac.uk"
SERENE_API_TOKEN = "your-new-api-token"
SERENE_API_TIMEOUT = "30"
SERENE_AUTH_SCHEME = "Token"
```

Any token pasted into chat, screenshots, commits, or public files must be
revoked. Never reuse the previously exposed token.

## Verification

After deployment:

1. Click **Test SERENE API connection** and expect `Connected to SERENE AIDA raw-output API`.
2. Load a small region and confirm AIDA maps appear.
3. Compare a global 30-degree grid (91 local points) and 2-degree grid (16,471
   local points) with the same times. Raw dataset download count must not change.
4. Confirm Kp/ap appear only in the global geomagnetic panel.

Local automated tests:

```bash
python -m unittest discover -s tests -v
```

No local scientific sample dataset is used as a silent fallback.
