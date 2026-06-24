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
  -> GET https://spaceweather.bham.ac.uk/api/download-forecast/
  -> one raw AIDA HDF5 state per distinct requested time
  -> official AIDAState.readFile() and AIDAState.calc()
  -> exact local bounding-box/grid calculation
  -> time, lat, lon, variable, value, model DataFrame
  -> ICAO-style category maps, summary table and research text messages
```

Changing the map extent or spacing changes only local calculation and plotting.
It does not create one API request per point. Identical time/latency requests
are deduplicated.

## Upstream scientific implementation

Raw-state interpretation and scientific grid calculation use Benjamin Reid's
MIT-licensed [`breid-phys/aida-ionosphere`](https://github.com/breid-phys/aida-ionosphere)
package, pinned to `v0.1.3`. The authenticated request follows its official
[`downloadOutput` implementation](https://github.com/breid-phys/aida-ionosphere/blob/v0.1.3/aida/api.py).
Nearby source comments identify every boundary that relies on this contract;
the dashboard does not copy the upstream scientific model implementation.

Supported spatial fields are `TEC`, `foF2`, `MUF3000F2` (upstream
`MUF3000`), `NmF2`, and `hmF2`. Kp/ap are global planetary indices and are
shown only as global context, never as regional map cells.

## SERENE-only ICAO-style products

The primary dashboard uses three research categories: `OK`, `MODERATE`, and
`SEVERE`. Vertical TEC uses the ICAO 125/175 TECU thresholds. The Kp auroral
absorption proxy uses Kp 8/9 and remains global. Post-storm depression uses
30%/50%, a same-UTC 30-day AIDA median, and the requirement that SERENE Kp
reached 6 during the preceding 96 hours.

`Max 3h` loads 37 five-minute AIDA analysis states. Each distinct time is
downloaded once; all regional grid cells are calculated locally. The +3h and
+6h columns use official SERENE AIDA forecast HDF5 products (periods 180 and
360 minutes), not linear extrapolation.

SERENE AIDA does not currently provide amplitude scintillation S4, phase
scintillation sigma-phi, 30 MHz riometer PCA, or solar-X-ray SWF inputs. The UI
marks them `Not available from SERENE` and never fabricates zero or `OK`.

Generated SWX text is deterministic and explicitly marked `STATUS: TEST` and
`RESEARCH PROTOTYPE - NOT FOR OPERATIONAL USE`.

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
3. Confirm the table contains Latest, Max 3h, +3h and +6h columns.
4. Confirm the categorical map uses only OK/MODERATE/SEVERE (plus grey
   unavailable cells).
5. Compare 30-degree and 2-degree grids for the same analysis time. The number
   of time-product API requests must not change.
6. Confirm Kp/ap appear only in the global geomagnetic panel.

Local automated tests:

```bash
python -m unittest discover -s tests -v
```

No local scientific sample dataset is used as a silent fallback.
