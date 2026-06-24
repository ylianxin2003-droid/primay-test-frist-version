# SERENE-only ICAO-style dashboard design

## Objective

Extend the dissertation dashboard so that it uses only SERENE-hosted data to
produce:

1. categorical regional maps with `OK`, `MODERATE`, and `SEVERE` states;
2. an ICAO-dashboard-style table containing the latest value, rolling
   three-hour maximum, and available SERENE forecasts; and
3. automatically generated, text-based space-weather prototype messages.

The application remains an academic research prototype. It must not claim to
be an operational ICAO advisory service or invent values that SERENE does not
provide.

## Authoritative data boundary

All scientific input must come from SERENE:

- authenticated AIDA raw analysis states from `/api/download-output/`;
- authenticated AIDA forecast states from `/api/download-forecast/`;
- public SERENE Kp/ap indices from `resources/Indices/Kp_ap.csv`.

The forecast request follows the MIT-licensed
`breid-phys/aida-ionosphere v0.1.3` contract. Supported forecast periods are
30, 90, 180, and 360 minutes. Source comments must identify code based on that
contract.

No NOAA, ESA, PECASUS, locally bundled scientific sample, or synthetic fallback
data may enter the calculations.

## Supported and unavailable indicators

### Supported

| Indicator | SERENE source | Regional map | Current/max/forecast table |
|---|---|---:|---:|
| Vertical TEC | AIDA `TEC` | Yes | Yes |
| Post-storm depression (PSD) | AIDA `MUF3000`/`foF2` plus SERENE Kp | Yes | Yes |
| Auroral absorption proxy | SERENE Kp | No; Kp is global | Current and 3-hour maximum only |
| foF2, MUF3000F2, NmF2, hmF2 | AIDA | Raw map only | Optional raw-data views |

### Explicitly unavailable

The interface must show these as `Not available from SERENE` rather than
assigning zero or `OK`:

- amplitude scintillation S4;
- phase scintillation sigma-phi;
- polar-cap absorption from 30 MHz riometer measurements;
- shortwave fadeout from solar X-ray measurements.

## Time products and API behaviour

For a selected analysis time `T`:

- `Latest` uses the AIDA analysis state at `T`.
- `Max 3h` loads distinct five-minute AIDA states from `T-3h` through `T`,
  downloads each state at most once, calculates every requested grid point
  locally, and takes the maximum over both time and the selected region.
- `+3h` and `+6h` use the official AIDA forecast endpoint with periods 180 and
  360 minutes. They are not produced by linear extrapolation.
- Kp/ap use all SERENE index rows in the selected observation interval. Since
  SERENE does not provide a Kp forecast through the current resource, forecast
  cells for auroral absorption display `N/A`.

The application must deduplicate identical `(analysis time, latency, forecast
period)` requests. The in-process HDF5 cache must be bounded so a long-running
Streamlit worker cannot grow without limit.

If an official forecast is unavailable for a requested historical time, the
dashboard continues with observed products and displays the forecast as
unavailable with the server's safe error message.

## ICAO-style classifications

Only three display categories are used for the new operational-style views:

| Indicator | OK | MODERATE | SEVERE |
|---|---:|---:|---:|
| Vertical TEC | `< 125 TECU` | `125 to <175 TECU` | `>=175 TECU` |
| Auroral absorption proxy | `Kp < 8` | `8 <= Kp < 9` | `Kp >= 9` |
| PSD | `<30%` | `30% to <50%` | `>=50%` |

PSD is the percentage decrease in MUF relative to a 30-day running reference.
For the selected UTC time, the reference is the median of AIDA reference values
at the same UTC time over the previous 30 days. PSD is eligible for a
MODERATE/SEVERE warning only when SERENE Kp reached at least 6 during the
previous 96 hours. Without that storm condition, the status remains `OK`, while
the calculated depression remains visible.

Threshold definitions and calculation explanations must be visible in the UI.

## Regional map design

The regional categorical map supports:

- `Vertical TEC`;
- `Post-storm depression`;
- horizons `Latest`, `+3h`, and `+6h` when the corresponding official state is
  available.

Each requested latitude/longitude cell is coloured:

- green: `OK`;
- orange: `MODERATE`;
- red: `SEVERE`;
- grey: unavailable/invalid.

Hover text shows time, latitude, longitude, source value, unit, category,
threshold explanation, and whether the state is analysis or official forecast.
Kp/ap must never be converted into regional point cells.

## Summary table design

The primary table contains:

| Indicator | Latest time UTC | Latest value | Status | Max 3h | Max-3h status | +3h forecast | +3h status | +6h forecast | +6h status |
|---|---|---:|---|---:|---|---:|---|---:|---|

For spatial indicators, values are conservative regional maxima. A detail
caption makes that aggregation explicit. The table contains rows for Vertical
TEC, PSD, and the Kp auroral-absorption proxy. Unavailable forecast cells use
`N/A`, never zero.

A separate compact availability table lists S4, sigma-phi, PCA, and SWF as not
available from the current SERENE source.

## Text product design

Generate an ICAO-style research message from the worst supported category. The
message contains:

```text
SWX ADVISORY
STATUS: TEST
DTG: <generation time UTC>
SWXC: UOB RESEARCH PROTOTYPE
SWX EFFECT: <GNSS or HF COM>
ADVISORY NR: <session-local identifier>
OBS SWX: <time> <MOD/SEV or NO SWX EXP> <selected region>
FCST SWX +3 HR: <time and category, or NOT AVAILABLE>
FCST SWX +6 HR: <time and category, or NOT AVAILABLE>
RMK: GENERATED ONLY FROM SERENE AIDA/KP DATA.
NXT ADVISORY: NO FURTHER ADVISORIES
RESEARCH PROTOTYPE - NOT FOR OPERATIONAL USE
```

No advisory is presented as active when every supported indicator is `OK`;
instead the generated text reports `NO SWX EXP`. The message can be copied and
downloaded as a `.txt` file.

## Component boundaries

- `serene_client.py`: authenticated analysis/forecast downloads, safe errors,
  request deduplication, and bounded raw-state cache.
- `data_loader.py`: constructs observation, rolling-window, baseline, and
  official forecast datasets without per-grid-point API calls.
- `icao_risk.py` (new): pure threshold classification, PSD calculation, regional
  aggregation, and table-row construction.
- `icao_message.py` (new): pure, deterministic text-product generation.
- `icao_visualisation.py` (new): categorical map rendering only.
- `app.py`: controls loading, progress, UI selection, table/map/message display,
  and unavailability notices.
- existing raw maps and Kp/ap context remain available for scientific
  inspection.

## Error handling

- Reject dates before 2024-09-28, future analysis times, and reversed ranges
  before calling SERENE.
- A failed forecast must not discard valid observed data.
- Missing 30-day baseline states produce `PSD unavailable`, not a fabricated
  zero.
- Missing Kp history prevents PSD warning eligibility and is reported clearly.
- API error details are shortened, sanitised, and never include the token.

## Test strategy

Tests are written before implementation and cover:

- official forecast request path, payload, periods, cache keys, and safe errors;
- exact five-minute rolling-window time generation and request deduplication;
- TEC, Kp, and PSD boundary classifications;
- PSD calculation and the previous-96-hour Kp eligibility rule;
- regional maximum summary rows and correct `N/A` handling;
- deterministic ICAO-style message fields for OK, MODERATE, SEVERE, and missing
  forecast states;
- categorical map exclusion of Kp/ap;
- Streamlit smoke startup and the existing regression suite.

## Acceptance criteria

1. The dashboard labels every scientific input as SERENE AIDA or SERENE
   indices.
2. Changing grid spacing never increases API calls for a fixed set of times.
3. Latest, Max-3h, +3h, and +6h values are traceable to downloaded SERENE
   states.
4. TEC and PSD maps use only `OK`, `MODERATE`, and `SEVERE`.
5. Kp remains global and is never shown as a regional point map.
6. Unsupported indicators visibly say `Not available from SERENE`.
7. Generated text is clearly marked `STATUS: TEST` and research-only.
8. Existing and new automated tests pass in the Streamlit Cloud dependency
   environment.
