# SERENE-only ICAO Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build SERENE-only categorical aviation-risk maps, an ICAO-style latest/Max-3h/forecast table, and deterministic research text advisories.

**Architecture:** Extend the existing authenticated AIDA client with the official forecast endpoint, then add pure risk, message, and visualisation modules. `data_loader.py` will orchestrate observation-window, 30-day reference, and official forecast downloads while preserving one HDF5 request per distinct time/product and local calculation for every grid point.

**Tech Stack:** Python 3.11, Streamlit, pandas, NumPy, Plotly, requests, h5py, `breid-phys/aida-ionosphere v0.1.3`, unittest.

---

### Task 1: Official AIDA forecast downloads and bounded state cache

**Files:**
- Modify: `streamlit_cloud_github/serene_client.py`
- Modify: `streamlit_cloud_github/tests/test_aida_output_client.py`

- [ ] **Step 1: Write failing forecast-contract and bounded-cache tests**

Add tests that call the wished-for API:

```python
def test_forecast_request_matches_upstream_contract(self):
    response = _response()
    self.client._session.request = Mock(return_value=response)

    ok, message, payload = self.client.download_aida_forecast(
        requested_time="2026-06-24T12:00:00Z",
        latency="ultra",
        period_minutes=180,
    )

    self.assertTrue(ok, message)
    self.assertEqual(payload, response.content)
    kwargs = self.client._session.request.call_args.kwargs
    self.assertEqual(
        kwargs["url"],
        "https://spaceweather.bham.ac.uk/api/download-forecast/",
    )
    self.assertEqual(kwargs["data"], {
        "file_time": "2026-06-24T12:00:00",
        "product": "ultra",
        "file_type": "raw",
        "period": 180,
    })

def test_forecast_rejects_unsupported_period(self):
    ok, message, payload = self.client.download_aida_forecast(
        "2026-06-24T12:00:00Z", "ultra", 120,
    )
    self.assertFalse(ok)
    self.assertIn("Unsupported AIDA forecast period", message)
    self.assertIsNone(payload)

def test_raw_cache_evicts_oldest_entry(self):
    from serene_client import AIDA_RAW_CACHE_MAX_ENTRIES, SereneClient
    self.client._session.request = Mock(return_value=_response())
    for minute in range(AIDA_RAW_CACHE_MAX_ENTRIES + 1):
        self.client.download_aida_raw_output(
            f"2026-06-24T12:{minute:02d}:00Z", "ultra"
        )
    self.assertLessEqual(
        len(SereneClient._aida_raw_cache), AIDA_RAW_CACHE_MAX_ENTRIES
    )
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
cd streamlit_cloud_github
python -m unittest tests.test_aida_output_client -v
```

Expected: failures because `download_aida_forecast` and
`AIDA_RAW_CACHE_MAX_ENTRIES` do not exist.

- [ ] **Step 3: Implement the official forecast contract and LRU cache**

Use an `OrderedDict` cache keyed by `(kind, normalised_time, latency,
period_minutes)`, with a configurable default maximum of 16 entries. Add:

```python
AIDA_RAW_CACHE_MAX_ENTRIES = max(
    1, int(os.getenv("SERENE_AIDA_RAW_CACHE_MAX_ENTRIES", "16"))
)

def download_aida_forecast(
    self,
    requested_time: str,
    latency: str,
    period_minutes: int,
) -> tuple[bool, str, bytes | None]:
    """Download an official AIDA forecast using upstream v0.1.3 contract."""
```

Share HDF5 validation, safe error extraction, request execution, cache lookup,
and eviction between analysis and forecast downloads. Forecast periods are
restricted to `{30, 90, 180, 360}` and `latest` is not accepted for forecasts.

- [ ] **Step 4: Run focused and full client tests and verify GREEN**

```bash
python -m unittest tests.test_aida_output_client -v
python -m unittest discover -s tests -v
```

Expected: all tests pass and no token appears in an error.

- [ ] **Step 5: Commit**

```bash
git add streamlit_cloud_github/serene_client.py \
        streamlit_cloud_github/tests/test_aida_output_client.py
git commit -m "feat: add official AIDA forecast downloads"
```

### Task 2: ICAO category and PSD calculation engine

**Files:**
- Create: `streamlit_cloud_github/icao_risk.py`
- Create: `streamlit_cloud_github/tests/test_icao_risk.py`

- [ ] **Step 1: Write failing boundary and PSD tests**

```python
class IcaoRiskTest(unittest.TestCase):
    def test_tec_boundaries(self):
        from icao_risk import classify_tec
        self.assertEqual(classify_tec(124.99), "OK")
        self.assertEqual(classify_tec(125), "MODERATE")
        self.assertEqual(classify_tec(174.99), "MODERATE")
        self.assertEqual(classify_tec(175), "SEVERE")

    def test_auroral_absorption_boundaries(self):
        from icao_risk import classify_auroral_absorption
        self.assertEqual(classify_auroral_absorption(7.9), "OK")
        self.assertEqual(classify_auroral_absorption(8), "MODERATE")
        self.assertEqual(classify_auroral_absorption(9), "SEVERE")

    def test_psd_requires_previous_storm(self):
        from icao_risk import classify_psd
        self.assertEqual(classify_psd(55, kp_storm_eligible=False), "OK")
        self.assertEqual(classify_psd(30, kp_storm_eligible=True), "MODERATE")
        self.assertEqual(classify_psd(50, kp_storm_eligible=True), "SEVERE")

    def test_psd_percent_uses_positive_depression(self):
        from icao_risk import calculate_psd_percent
        self.assertAlmostEqual(calculate_psd_percent(7.0, 10.0), 30.0)
        self.assertEqual(calculate_psd_percent(11.0, 10.0), 0.0)
        self.assertIsNone(calculate_psd_percent(5.0, 0.0))
```

- [ ] **Step 2: Run the focused test and verify RED**

```bash
python -m unittest tests.test_icao_risk -v
```

Expected: import failure for missing `icao_risk`.

- [ ] **Step 3: Implement pure classifications and PSD helpers**

Create constants and pure functions:

```python
ICAO_COLORS = {
    "OK": "#2ecc71",
    "MODERATE": "#f39c12",
    "SEVERE": "#e74c3c",
    "UNAVAILABLE": "#95a5a6",
}

def classify_tec(value: float) -> str:
    if not np.isfinite(value):
        return "UNAVAILABLE"
    return "SEVERE" if value >= 175 else "MODERATE" if value >= 125 else "OK"

def classify_auroral_absorption(kp: float) -> str:
    if not np.isfinite(kp):
        return "UNAVAILABLE"
    return "SEVERE" if kp >= 9 else "MODERATE" if kp >= 8 else "OK"

def calculate_psd_percent(current: float, reference: float) -> float | None:
    if not np.isfinite(current) or not np.isfinite(reference) or reference <= 0:
        return None
    return max(0.0, (reference - current) / reference * 100.0)

def classify_psd(value: float, kp_storm_eligible: bool) -> str:
    if not np.isfinite(value):
        return "UNAVAILABLE"
    if not kp_storm_eligible:
        return "OK"
    return "SEVERE" if value >= 50 else "MODERATE" if value >= 30 else "OK"

def worst_category(values: Iterable[str]) -> str:
    priority = {"UNAVAILABLE": -1, "OK": 0, "MODERATE": 1, "SEVERE": 2}
    valid = [value for value in values if value in priority]
    return max(valid, key=priority.get) if valid else "UNAVAILABLE"
```

`calculate_psd_percent` returns
`max(0, (reference-current)/reference*100)` and rejects non-finite/non-positive
references.

- [ ] **Step 4: Add failing regional-cell and summary-row tests**

Test a two-location dataset containing `product_kind` values `analysis`,
`rolling`, `forecast_180`, and `forecast_360`. Assert that:

- Kp/ap never appear in map cells;
- each TEC map row receives an ICAO category;
- summary values are regional maxima;
- missing forecast values remain `N/A`, not zero;
- the Kp row has no regional forecast.

- [ ] **Step 5: Implement map-cell and summary-table builders**

Add:

```python
def build_categorical_cells(
    products: pd.DataFrame,
    indicator: str,
    horizon: str,
    kp_storm_eligible: bool = False,
) -> pd.DataFrame:
    kind = {"Latest": "analysis", "+3h": "forecast_180", "+6h": "forecast_360"}.get(horizon)
    variable = {"Vertical TEC": "TEC", "Post-storm depression": "MUF3000F2"}.get(indicator)
    if kind is None or variable is None:
        return pd.DataFrame()
    work = products[(products["product_kind"] == kind) & (products["variable"] == variable)].copy()
    value_column = "value" if variable == "TEC" else "psd_percent"
    if work.empty or value_column not in work:
        return pd.DataFrame()
    work["display_value"] = pd.to_numeric(work[value_column], errors="coerce")
    classifier = classify_tec if variable == "TEC" else lambda value: classify_psd(value, kp_storm_eligible)
    work["category"] = work["display_value"].map(classifier)
    work["indicator"] = indicator
    work["unit"] = "TECU" if variable == "TEC" else "%"
    return work.dropna(subset=["lat", "lon", "display_value"]).reset_index(drop=True)

def build_icao_summary(
    products: pd.DataFrame,
    indices: pd.DataFrame,
    kp_storm_eligible: bool,
) -> pd.DataFrame:
    rows = [
        _spatial_summary_row(products, "Vertical TEC", kp_storm_eligible),
        _spatial_summary_row(products, "Post-storm depression", kp_storm_eligible),
        _kp_summary_row(indices),
    ]
    return pd.DataFrame(rows)

def unavailable_indicator_rows() -> pd.DataFrame:
    return pd.DataFrame({
        "Indicator": ["Amplitude scintillation S4", "Phase scintillation sigma-phi", "Polar-cap absorption", "Shortwave fadeout"],
        "Availability": ["Not available from SERENE"] * 4,
    })
```

Use stable display columns from the design. Preserve unavailable cells as the
string `N/A` and add explanatory source columns. Implement
`_spatial_summary_row` by taking the regional maximum from `analysis`,
`rolling`, `forecast_180`, and `forecast_360`; implement `_kp_summary_row` from
the latest and maximum Kp values and assign `N/A` to both forecasts.

- [ ] **Step 6: Run focused and complete tests**

```bash
python -m unittest tests.test_icao_risk -v
python -m unittest discover -s tests -v
```

- [ ] **Step 7: Commit**

```bash
git add streamlit_cloud_github/icao_risk.py \
        streamlit_cloud_github/tests/test_icao_risk.py
git commit -m "feat: add ICAO categorical risk engine"
```

### Task 3: SERENE observation-window, baseline, and official forecast loader

**Files:**
- Modify: `streamlit_cloud_github/data_loader.py`
- Modify: `streamlit_cloud_github/tests/test_api_only_data_loader.py`

- [ ] **Step 1: Write failing time-schedule tests**

```python
def test_three_hour_schedule_has_distinct_five_minute_states(self):
    import data_loader
    times = data_loader.three_hour_aida_times("2026-06-24T12:00:00Z")
    self.assertEqual(len(times), 37)
    self.assertEqual(times[0], pd.Timestamp("2026-06-24T09:00:00Z"))
    self.assertEqual(times[-1], pd.Timestamp("2026-06-24T12:00:00Z"))

def test_baseline_schedule_uses_previous_thirty_days_same_utc(self):
    import data_loader
    times = data_loader.psd_reference_times("2026-06-24T12:00:00Z")
    self.assertEqual(len(times), 30)
    self.assertEqual(times[0], pd.Timestamp("2026-05-25T12:00:00Z"))
    self.assertEqual(times[-1], pd.Timestamp("2026-06-23T12:00:00Z"))
```

- [ ] **Step 2: Run focused tests and verify RED**

```bash
python -m unittest tests.test_api_only_data_loader -v
```

- [ ] **Step 3: Implement deterministic time schedules**

Add pure helpers that normalise to the nearest AIDA five-minute time and reject
times before `2024-09-28T00:00:00Z` or after the current publication-safe UTC
time.

- [ ] **Step 4: Write failing product-loader orchestration tests**

Extend `FakeRawClient` with `download_aida_forecast`. Test that
`load_icao_products`:

- downloads 37 distinct rolling analysis states;
- downloads 30 distinct daily baseline states only when PSD is requested;
- requests forecast periods 180 and 360 exactly once;
- performs the same number of downloads for 2-degree and 30-degree grids;
- labels frames with `analysis`, `rolling`, `baseline`, `forecast_180`, or
  `forecast_360`;
- retains observations when forecasts fail;
- fetches Kp from `T-96h` through `T` and marks storm eligibility when max Kp is
  at least 6.

- [ ] **Step 5: Implement `load_icao_products`**

Use this public result shape:

```python
@dataclass
class IcaoProductBundle:
    products: pd.DataFrame = field(default_factory=pd.DataFrame)
    indices: pd.DataFrame = field(default_factory=pd.DataFrame)
    status: LoadStatus = field(default_factory=LoadStatus)
    kp_storm_eligible: bool = False

def load_icao_products(
    analysis_time: str,
    variables: list[str],
    region: dict[str, float],
    grid_step: float,
    include_three_hour_window: bool = True,
    include_psd_baseline: bool = True,
    progress_callback: Any | None = None,
) -> IcaoProductBundle:
    analysis = normalise_aida_request_time(analysis_time)
    rolling = three_hour_aida_times(analysis.isoformat()) if include_three_hour_window else [analysis]
    baseline = psd_reference_times(analysis.isoformat()) if include_psd_baseline else []
    client = SereneClient()
    frames, warnings, metadata = _load_analysis_frames(
        client, analysis, rolling, baseline, variables, region, grid_step, progress_callback
    )
    forecasts, forecast_warnings = _load_forecast_frames(
        client, analysis, (180, 360), variables, region, grid_step, progress_callback
    )
    warnings.extend(forecast_warnings)
    indices = _load_icao_indices(client, analysis)
    kp = pd.to_numeric(indices.loc[indices["variable"] == "Kp", "value"], errors="coerce").dropna()
    eligible = bool(not kp.empty and kp.max() >= 6)
    products = _attach_psd_reference(pd.concat(frames + forecasts, ignore_index=True))
    status = _icao_load_status(products, warnings, metadata)
    return IcaoProductBundle(products, indices, status, eligible)
```

Calculate only required fields: TEC for GNSS products and MUF3000F2 for PSD.
Reuse one client instance, deduplicate specs before requesting, and append
`product_kind`, `requested_time`, and `forecast_minutes` columns. Calculate the
30-day median by `(lat, lon, variable)` and merge it into current/rolling/
forecast MUF rows as `reference_value` and `psd_percent`.

- [ ] **Step 6: Run loader tests and regression suite**

```bash
python -m unittest tests.test_api_only_data_loader -v
python -m unittest discover -s tests -v
```

- [ ] **Step 7: Commit**

```bash
git add streamlit_cloud_github/data_loader.py \
        streamlit_cloud_github/tests/test_api_only_data_loader.py
git commit -m "feat: load SERENE ICAO observation and forecast products"
```

### Task 4: Deterministic ICAO-style research messages

**Files:**
- Create: `streamlit_cloud_github/icao_message.py`
- Create: `streamlit_cloud_github/tests/test_icao_message.py`

- [ ] **Step 1: Write failing OK, warning, and missing-forecast tests**

```python
def test_moderate_gnss_message_is_explicitly_test_only(self):
    from icao_message import generate_icao_message
    message = generate_icao_message(
        effect="GNSS",
        observed_time="2026-06-24T12:00:00Z",
        observed_category="MODERATE",
        region={"lat_min": 45, "lat_max": 60, "lon_min": -15, "lon_max": 15},
        forecasts={180: "MODERATE", 360: "OK"},
        generated_time="2026-06-24T12:05:00Z",
        advisory_number="2026/001",
    )
    self.assertIn("STATUS: TEST", message)
    self.assertIn("SWX EFFECT: GNSS", message)
    self.assertIn("FCST SWX +3 HR:", message)
    self.assertIn("RESEARCH PROTOTYPE - NOT FOR OPERATIONAL USE", message)

def test_missing_forecast_is_not_reported_as_ok(self):
    from icao_message import generate_icao_message
    message = generate_icao_message(
        effect="GNSS",
        observed_time="2026-06-24T12:00:00Z",
        observed_category="MODERATE",
        region={"lat_min": 45, "lat_max": 60, "lon_min": -15, "lon_max": 15},
        forecasts={180: None, 360: None},
        generated_time="2026-06-24T12:05:00Z",
        advisory_number="2026/001",
    )
    self.assertIn("FCST SWX +3 HR: NOT AVAILABLE", message)

def test_ok_message_reports_no_space_weather_expected(self):
    from icao_message import generate_icao_message
    message = generate_icao_message(
        effect="GNSS",
        observed_time="2026-06-24T12:00:00Z",
        observed_category="OK",
        region={"lat_min": 45, "lat_max": 60, "lon_min": -15, "lon_max": 15},
        forecasts={180: "OK", 360: "OK"},
        generated_time="2026-06-24T12:05:00Z",
        advisory_number="2026/001",
    )
    self.assertIn("NO SWX EXP", message)
```

- [ ] **Step 2: Run tests and verify RED**

```bash
python -m unittest tests.test_icao_message -v
```

- [ ] **Step 3: Implement the pure message formatter**

```python
def generate_icao_message(
    *,
    effect: str,
    observed_time: str | pd.Timestamp,
    observed_category: str,
    region: dict[str, float],
    forecasts: dict[int, str | None],
    generated_time: str | pd.Timestamp,
    advisory_number: str,
) -> str:
    if effect not in {"GNSS", "HF COM"}:
        raise ValueError(f"Unsupported SWX effect: {effect}")
    if observed_category not in {"OK", "MODERATE", "SEVERE"}:
        raise ValueError(f"Unsupported category: {observed_category}")
    observed = _format_icao_time(observed_time)
    generated = pd.to_datetime(generated_time, utc=True).strftime("%Y%m%d/%H%MZ")
    observed_text = "NO SWX EXP" if observed_category == "OK" else _short_category(observed_category)
    region_text = _format_region(region)
    lines = [
        "SWX ADVISORY", "STATUS: TEST", f"DTG: {generated}",
        "SWXC: UOB RESEARCH PROTOTYPE", f"SWX EFFECT: {effect}",
        f"ADVISORY NR: {advisory_number}",
        f"OBS SWX: {observed} {observed_text} {region_text}",
    ]
    for period in (180, 360):
        hours = period // 60
        category = forecasts.get(period)
        if category is None:
            lines.append(f"FCST SWX +{hours} HR: NOT AVAILABLE")
            continue
        forecast_time = pd.to_datetime(observed_time, utc=True) + pd.Timedelta(minutes=period)
        forecast_text = "NO SWX EXP" if category == "OK" else _short_category(category)
        lines.append(f"FCST SWX +{hours} HR: {_format_icao_time(forecast_time)} {forecast_text} {region_text}")
    lines.extend([
        "RMK: GENERATED ONLY FROM SERENE AIDA/KP DATA.",
        "NXT ADVISORY: NO FURTHER ADVISORIES",
        "RESEARCH PROTOTYPE - NOT FOR OPERATIONAL USE",
    ])
    return "\n".join(lines)
```

Validate effects (`GNSS`, `HF COM`) and categories. Format UTC as ICAO
`DD/HHMMZ`, encode the selected bounding box plainly without claiming an
official FIR/polygon, and always emit the research-only footer.

- [ ] **Step 4: Run focused and complete tests**

```bash
python -m unittest tests.test_icao_message -v
python -m unittest discover -s tests -v
```

- [ ] **Step 5: Commit**

```bash
git add streamlit_cloud_github/icao_message.py \
        streamlit_cloud_github/tests/test_icao_message.py
git commit -m "feat: generate ICAO-style research messages"
```

### Task 5: Categorical regional map

**Files:**
- Create: `streamlit_cloud_github/icao_visualisation.py`
- Create: `streamlit_cloud_github/tests/test_icao_visualisation.py`

- [ ] **Step 1: Write failing map tests**

Construct TEC cells with one cell in each category and assert:

```python
fig = create_icao_category_map(cells, title="Vertical TEC - Latest")
self.assertEqual(sum(len(trace.lat) for trace in fig.data), 3)
self.assertEqual(
    {trace.name for trace in fig.data},
    {"OK", "MODERATE", "SEVERE"},
)
```

Also assert an empty figure for Kp/ap and unavailable frames.

- [ ] **Step 2: Run the test and verify RED**

```bash
python -m unittest tests.test_icao_visualisation -v
```

- [ ] **Step 3: Implement the categorical Plotly map**

```python
def create_icao_category_map(
    cells: pd.DataFrame,
    title: str,
) -> go.Figure:
    if cells.empty or cells.get("variable", pd.Series(dtype=str)).isin(["Kp", "ap"]).any():
        return empty_icao_figure("No regional ICAO category data available.")
    fig = px.scatter_geo(
        cells,
        lat="lat",
        lon="lon",
        color="category",
        hover_name="indicator",
        hover_data={"display_value": ":.2f", "unit": True, "time": True, "source": True},
        color_discrete_map=ICAO_COLORS,
        category_orders={"category": ["OK", "MODERATE", "SEVERE", "UNAVAILABLE"]},
        title=title,
        projection="natural earth",
    )
    fig.update_traces(marker={"size": 10, "opacity": 0.82})
    fig.update_geos(fitbounds="locations", showcoastlines=True, showland=True, showocean=True)
    fig.update_layout(template="plotly_white", height=560)
    return fig
```

Use `ICAO_COLORS`, fixed category order, marker size 10, regional fit bounds,
and hover fields for value, unit, time, category, source, and threshold. Never
accept Kp/ap as regional indicators.

- [ ] **Step 4: Run focused and complete tests**

```bash
python -m unittest tests.test_icao_visualisation -v
python -m unittest discover -s tests -v
```

- [ ] **Step 5: Commit**

```bash
git add streamlit_cloud_github/icao_visualisation.py \
        streamlit_cloud_github/tests/test_icao_visualisation.py
git commit -m "feat: add ICAO categorical regional maps"
```

### Task 6: Streamlit dashboard integration

**Files:**
- Modify: `streamlit_cloud_github/app.py`
- Modify: `streamlit_cloud_github/app_utils.py`
- Modify: `streamlit_cloud_github/tests/test_dashboard_settings.py`
- Create: `streamlit_cloud_github/tests/test_icao_app_helpers.py`

- [ ] **Step 1: Write failing UI-source and helper tests**

Assert that the app contains:

- `ICAO-style SERENE-only products`;
- the indicator and horizon selectors;
- a summary dataframe;
- `Not available from SERENE`;
- a text-area/code block and `.txt` download button;
- no external scientific-data URL or client.

Add pure helper tests for future-time rejection, reversed-range rejection, and
session-local advisory numbering.

- [ ] **Step 2: Run tests and verify RED**

```bash
python -m unittest tests.test_dashboard_settings tests.test_icao_app_helpers -v
```

- [ ] **Step 3: Integrate loading and session state**

Add `icao_bundle`, `icao_summary`, and `icao_messages` session keys. Replace the
old heuristic forecast as the primary view with a button-driven SERENE product
load. Preserve raw-data and global-index inspection below the new product.

The progress display reports total distinct HDF5 states and the current product
type. Forecast failures render warnings without hiding observations.

- [ ] **Step 4: Render the new dashboard sections**

Render, in order:

1. data/API status and historical event selector;
2. ICAO summary table with regional-max caption;
3. indicator/horizon categorical map;
4. SERENE-unavailable indicator table;
5. generated GNSS and HF COM research messages with `.txt` downloads;
6. global Kp/ap context and raw scientific views.

Do not render Kp/ap as regional map points. Label every message and advisory as
test/research-only.

- [ ] **Step 5: Run UI tests and Streamlit smoke test**

```bash
python -m unittest tests.test_dashboard_settings tests.test_icao_app_helpers -v
python - <<'PY'
from streamlit.testing.v1 import AppTest
at = AppTest.from_file("app.py", default_timeout=30).run()
assert not at.exception, [exc.value for exc in at.exception]
print("AppTest exceptions=0")
PY
```

- [ ] **Step 6: Commit**

```bash
git add streamlit_cloud_github/app.py \
        streamlit_cloud_github/app_utils.py \
        streamlit_cloud_github/tests/test_dashboard_settings.py \
        streamlit_cloud_github/tests/test_icao_app_helpers.py
git commit -m "feat: integrate SERENE-only ICAO dashboard"
```

### Task 7: Documentation, complete verification, and deployment handoff

**Files:**
- Modify: `streamlit_cloud_github/README.md`
- Modify: `streamlit_cloud_github/部署说明.md`

- [ ] **Step 1: Update documentation**

Document:

- SERENE-only inputs and exact endpoints;
- 37-state Max-3h cost and one-request-per-time behavior;
- official +3h/+6h AIDA forecasts;
- ICAO thresholds and PSD eligibility rule;
- unavailable S4, sigma-phi, PCA, and SWF fields;
- research-only/non-operational status;
- Streamlit Cloud Python 3.11 deployment and Secrets.

- [ ] **Step 2: Run source-safety checks**

```bash
rg -n "noaa|esa.int|pecasus" streamlit_cloud_github/*.py
rg -n "SERENE_API_TOKEN\s*=\s*['\"][^'\"]+" streamlit_cloud_github
git diff --check
```

Expected: no external scientific runtime source and no hard-coded token.

- [ ] **Step 3: Run complete verification**

```bash
cd streamlit_cloud_github
python -m unittest discover -s tests -v
python -m compileall -q .
python -m pip check
python - <<'PY'
from streamlit.testing.v1 import AppTest
at = AppTest.from_file("app.py", default_timeout=30).run()
assert not at.exception, [exc.value for exc in at.exception]
print("AppTest exceptions=0")
PY
```

Expected: all tests pass, compilation exits zero, dependencies are consistent,
and Streamlit reports zero exceptions.

- [ ] **Step 4: Review the final diff against the acceptance criteria**

Confirm that all values shown as scientific inputs originate from SERENE, Kp is
global only, unavailable fields are explicit, messages are test-only, and grid
density does not change request count for fixed times.

- [ ] **Step 5: Commit documentation**

```bash
git add streamlit_cloud_github/README.md streamlit_cloud_github/部署说明.md
git commit -m "docs: explain SERENE-only ICAO products"
```

- [ ] **Step 6: Push only after verification**

```bash
git status --short
git push origin main
```

Expected: clean working tree and GitHub `main` updated without assistant names
in commit messages.
