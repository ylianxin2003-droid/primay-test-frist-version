# AIDA Raw Output API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Download one official raw AIDA state per distinct requested time and use Benjamin Reid's upstream interpreter to calculate all selected regional grid points locally.

**Architecture:** `SereneClient` owns the authenticated raw download and byte cache. A new `aida_adapter` module is the only boundary that imports the upstream scientific package, loads the temporary HDF5 state, calls `AIDAState.calc()`, and returns the dashboard's long-form DataFrame. `data_loader` deduplicates time/latency request keys and keeps global Kp/ap independent from regional AIDA success.

**Tech Stack:** Python 3.11, Streamlit, requests, pandas 1.x, NumPy 1.x, h5py, upstream `breid-phys/aida-ionosphere` v0.1.3, unittest, Plotly.

---

## File responsibility map

- `streamlit_cloud_github/serene_client.py`: HTTP authentication, raw-output request contract, response validation, byte caching, Kp/ap download.
- `streamlit_cloud_github/aida_adapter.py`: upstream AIDA interpreter boundary and DataFrame conversion.
- `streamlit_cloud_github/aida_grid.py`: exact target-axis construction and point estimation only; remove param_2d interpolation responsibilities after migration.
- `streamlit_cloud_github/data_loader.py`: time/latency selection, request deduplication, AIDA/Kp orchestration, status metadata.
- `streamlit_cloud_github/app.py`: connection/status wording and global-indices-only partial result messaging.
- `streamlit_cloud_github/requirements.txt`: reproducible upstream dependency and compatible numeric versions.
- `streamlit_cloud_github/README.md`, `部署说明.md`, `云端修复说明.md`: scientific provenance, deployment, Python 3.11 redeployment, and token safety.
- `streamlit_cloud_github/tests/`: endpoint, adapter, loader, UI text, and regression coverage.

### Task 1: Replace web-catalogue scraping with the official raw-output API

**Files:**
- Modify: `streamlit_cloud_github/serene_client.py:1-367`
- Replace tests: `streamlit_cloud_github/tests/test_aida_output_client.py`

- [ ] **Step 1: Replace catalogue tests with failing raw-download contract tests**

```python
class AidaRawOutputClientTest(unittest.TestCase):
    def setUp(self):
        from serene_client import SereneClient
        SereneClient._aida_raw_cache = {}
        self.client = SereneClient(
            base_url="https://spaceweather.bham.ac.uk",
            token="test-token",
        )

    def test_historical_raw_request_matches_upstream_contract(self):
        response = _response(content=b"\x89HDF\r\n\x1a\nraw-state")
        self.client._session.request = Mock(return_value=response)

        ok, message, payload = self.client.download_aida_raw_output(
            requested_time="2025-01-01T13:55:00Z",
            latency="rapid",
        )

        self.assertTrue(ok, message)
        self.assertEqual(payload, response.content)
        kwargs = self.client._session.request.call_args.kwargs
        self.assertEqual(kwargs["method"], "GET")
        self.assertEqual(
            kwargs["url"],
            "https://spaceweather.bham.ac.uk/api/download-output/",
        )
        self.assertEqual(kwargs["headers"]["Authorization"], "Token test-token")
        self.assertEqual(kwargs["data"], {
            "file_time": "2025-01-01T13:55:00+00:00",
            "product": "rapid",
            "file_type": "raw",
        })

    def test_latest_raw_request_is_cached(self):
        response = _response(content=b"\x89HDF\r\n\x1a\nraw-state")
        self.client._session.request = Mock(return_value=response)
        first = self.client.download_aida_raw_output(None, "ultra")
        second = self.client.download_aida_raw_output(None, "ultra")
        self.assertTrue(first[0])
        self.assertEqual(second[2], response.content)
        self.assertEqual(self.client._session.request.call_count, 1)
        self.assertEqual(
            self.client._session.request.call_args.kwargs["data"],
            {"latest": True, "product": "ultra", "file_type": "raw"},
        )

    def test_html_response_is_rejected_without_exposing_token(self):
        self.client._session.request = Mock(return_value=_response(
            content=b"<html><form id='login-form'></form></html>",
            content_type="text/html",
        ))
        ok, message, payload = self.client.download_aida_raw_output(None, "ultra")
        self.assertFalse(ok)
        self.assertIsNone(payload)
        self.assertNotIn("test-token", message)
        self.assertIn("non-HDF5", message)
```

- [ ] **Step 2: Run the client tests and verify RED**

Run:

```bash
cd streamlit_cloud_github
.venv/bin/python -m unittest tests.test_aida_output_client -v
```

Expected: FAIL because `download_aida_raw_output` and `_aida_raw_cache` do not exist.

- [ ] **Step 3: Implement the upstream raw-output request contract with attribution**

Remove `BeautifulSoup`, `urljoin`, `AidaOutput`, catalogue parsing, nearest-output selection, and web-page download methods. Add:

```python
ENDPOINTS = {
    "aida_raw_output": "/api/download-output/",
    "calc": "/api/calc/",
    "kp_ap": "/resources/download/Indices__Kp_ap.csv/",
}

class SereneClient:
    _aida_raw_cache: dict[tuple[str, str], bytes] = {}

    def download_aida_raw_output(
        self,
        requested_time: str | None,
        latency: str,
    ) -> tuple[bool, str, bytes | None]:
        """Download one raw AIDA state using Benjamin Reid's official API contract.

        Source: https://github.com/breid-phys/aida-ionosphere/blob/main/aida/api.py
        (`downloadOutput`, MIT License). The scientific interpreter remains an
        upstream dependency; this method only follows its documented request.
        """
        if latency not in {"ultra", "rapid", "final"}:
            return False, f"Unsupported AIDA latency: {latency}", None
        if not self.base_url:
            return False, "SERENE_API_BASE_URL is not configured.", None
        if not self.token:
            return False, "SERENE_API_TOKEN is not configured.", None

        if requested_time is None:
            cache_time = "latest"
            request_data = {"latest": True, "product": latency, "file_type": "raw"}
        else:
            parsed = pd.to_datetime(requested_time, errors="coerce", utc=True)
            if pd.isna(parsed):
                return False, f"Invalid requested AIDA time: {requested_time}", None
            cache_time = parsed.isoformat()
            request_data = {
                "file_time": parsed.isoformat(),
                "product": latency,
                "file_type": "raw",
            }

        key = (cache_time, latency)
        if key in type(self)._aida_raw_cache:
            return True, f"Loaded cached AIDA raw state for {cache_time}.", type(self)._aida_raw_cache[key]

        url = f"{self.base_url}{ENDPOINTS['aida_raw_output']}"
        try:
            response = self._session.request(
                method="GET",
                url=url,
                headers=self._auth_headers(),
                data=request_data,
                timeout=self.timeout,
            )
        except requests.exceptions.RequestException as exc:
            return False, f"SERENE AIDA raw-output request failed: {exc}", None

        if response.status_code in {401, 403}:
            return False, "SERENE rejected the API token for AIDA raw output.", None
        if not response.ok:
            return False, f"SERENE AIDA raw-output API returned status {response.status_code}.", None
        content = bytes(response.content)
        content_type = response.headers.get("Content-Type", "").lower()
        if not content or "html" in content_type or not content.startswith(b"\x89HDF\r\n\x1a\n"):
            return False, "SERENE AIDA raw-output API returned a non-HDF5 response.", None

        type(self)._aida_raw_cache[key] = content
        return True, f"Downloaded AIDA raw state for {cache_time}.", content
```

Update `test_connection()` to call `download_aida_raw_output(None, "ultra")` and report `Connected to SERENE AIDA raw-output API`.

- [ ] **Step 4: Run focused and existing client tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_aida_output_client tests.test_serene_indices -v
```

Expected: all client and Kp/ap tests PASS.

- [ ] **Step 5: Commit the raw client**

```bash
git add streamlit_cloud_github/serene_client.py streamlit_cloud_github/tests/test_aida_output_client.py
git commit -m "Use official AIDA raw output API"
```

### Task 2: Add the official AIDA interpreter adapter

**Files:**
- Create: `streamlit_cloud_github/aida_adapter.py`
- Create tests: `streamlit_cloud_github/tests/test_aida_adapter.py`
- Modify: `streamlit_cloud_github/aida_grid.py`

- [ ] **Step 1: Write failing adapter tests with a deterministic fake state**

```python
class FakeAIDAState:
    Time = 1735740000.0
    read_path = None

    def readFile(self, path):
        self.read_path = path
        assert os.path.exists(path)

    def calc(self, **kwargs):
        lats = np.asarray(kwargs["lat"], dtype=float)
        lons = np.asarray(kwargs["lon"], dtype=float)
        values = np.add.outer(lons, lats)
        return {
            "TEC": values,
            "foF2": values + 1,
            "MUF3000": values + 2,
            "NmF2": values + 3,
            "hmF2": values + 4,
        }

def test_adapter_calculates_exact_grid_and_maps_muf_name(self):
    from aida_adapter import calculate_aida_grid
    frame = calculate_aida_grid(
        b"raw-state",
        region={"lat_min": 0, "lat_max": 10, "lon_min": 20, "lon_max": 30},
        step=5,
        variables=["TEC", "MUF3000F2"],
        state_factory=FakeAIDAState,
    )
    self.assertEqual(sorted(frame["lat"].unique().tolist()), [0.0, 5.0, 10.0])
    self.assertEqual(sorted(frame["lon"].unique().tolist()), [20.0, 25.0, 30.0])
    self.assertEqual(set(frame["variable"]), {"TEC", "MUF3000F2"})
    muf = frame[(frame["lat"] == 5) & (frame["lon"] == 25) & (frame["variable"] == "MUF3000F2")]
    self.assertEqual(float(muf.iloc[0]["value"]), 32.0)

def test_adapter_calls_upstream_grid_contract(self):
    state = FakeAIDAState()
    calculate_aida_grid(
        b"raw-state",
        region={"lat_min": -5, "lat_max": 5, "lon_min": 0, "lon_max": 10},
        step=5,
        variables=["TEC"],
        state_factory=lambda: state,
    )
    self.assertEqual(state.last_kwargs["grid"], "3D")
    self.assertTrue(state.last_kwargs["TEC"])
    self.assertFalse(state.last_kwargs["MUF3000"])
    self.assertTrue(state.last_kwargs["collapse_particles"])
    self.assertTrue(state.last_kwargs["as_dict"])
```

Store `kwargs` as `self.last_kwargs` in the fake before returning its output.

- [ ] **Step 2: Run adapter tests and verify RED**

Run:

```bash
.venv/bin/python -m unittest tests.test_aida_adapter -v
```

Expected: FAIL because `aida_adapter` does not exist.

- [ ] **Step 3: Implement the adapter with nearby upstream attribution**

```python
"""Boundary around Benjamin Reid's official AIDA interpreter.

Upstream source (MIT): https://github.com/breid-phys/aida-ionosphere
"""

def _official_state_factory():
    import aida
    return aida.AIDAState()

def calculate_aida_grid(payload, region, step, variables, state_factory=None):
    target_lats = target_axis(region["lat_min"], region["lat_max"], step)
    target_lons = target_axis(region["lon_min"], region["lon_max"], step)
    selected = _normalise_variables(variables)

    factory = state_factory or _official_state_factory
    state = factory()
    try:
        with tempfile.NamedTemporaryFile(suffix=".h5") as handle:
            handle.write(payload)
            handle.flush()
            state.readFile(handle.name)
    except Exception as exc:
        raise AidaGridError(f"Official AIDA interpreter could not read the raw state: {exc}") from exc

    # Scientific calculation contract from the upstream README map example:
    # https://github.com/breid-phys/aida-ionosphere#example-3-maps
    try:
        output = state.calc(
            lat=target_lats,
            lon=target_lons,
            grid="3D",
            TEC="TEC" in selected,
            MUF3000="MUF3000F2" in selected,
            collapse_particles=True,
            as_dict=True,
        )
    except Exception as exc:
        raise AidaGridError(f"Official AIDA grid calculation failed: {exc}") from exc

    output_time = _normalise_state_time(state.Time)
    upstream_names = {"MUF3000F2": "MUF3000"}
    rows = []
    for variable in selected:
        field = upstream_names.get(variable, variable)
        values = np.asarray(output[field], dtype=float)
        expected = (len(target_lons), len(target_lats))
        if values.shape != expected:
            raise AidaGridError(f"AIDA field {field} has shape {values.shape}; expected {expected}.")
        for lon_index, lon in enumerate(target_lons):
            for lat_index, lat in enumerate(target_lats):
                rows.append({
                    "time": output_time,
                    "lat": float(lat),
                    "lon": float(lon),
                    "variable": variable,
                    "value": float(values[lon_index, lat_index]),
                    "model": "AIDA",
                    "source": "SERENE raw API + breid-phys/aida-ionosphere v0.1.3",
                })
    return pd.DataFrame(rows)
```

Move reusable variable normalisation into `aida_grid.py`; retain `target_axis`, `estimate_target_points`, `AIDA_VARIABLES`, and `AidaGridError`. Remove the obsolete `sample_aida_hdf5` interpolation path after loader migration in Task 3.

- [ ] **Step 4: Run adapter and axis tests**

```bash
.venv/bin/python -m unittest tests.test_aida_adapter tests.test_aida_grid -v
```

Expected: PASS, with exact spacing and orientation assertions green.

- [ ] **Step 5: Commit the adapter**

```bash
git add streamlit_cloud_github/aida_adapter.py streamlit_cloud_github/aida_grid.py streamlit_cloud_github/tests/test_aida_adapter.py streamlit_cloud_github/tests/test_aida_grid.py
git commit -m "Calculate grids with official AIDA interpreter"
```

### Task 3: Make the loader download once per time and calculate locally

**Files:**
- Modify: `streamlit_cloud_github/data_loader.py:9-187`
- Modify tests: `streamlit_cloud_github/tests/test_api_only_data_loader.py`

- [ ] **Step 1: Rewrite loader fakes and add failing request-count tests**

Use a fake client exposing only `download_aida_raw_output()` and
`fetch_kp_ap_indices()`. Patch `data_loader.calculate_aida_grid` to return a
small deterministic spatial DataFrame whose time is the requested output time.

```python
def test_grid_density_does_not_change_raw_download_count(self):
    coarse_client = FakeRawClient()
    with patch.object(data_loader, "SereneClient", return_value=coarse_client), \
         patch.object(data_loader, "calculate_aida_grid", side_effect=fake_calculation):
        _, coarse = data_loader.load_data(
            start_time="2026-06-21T20:00:00Z",
            end_time="2026-06-21T21:00:00Z",
            variables=["TEC"], region=GLOBAL, grid_step=30,
        )
    dense_client = FakeRawClient()
    with patch.object(data_loader, "SereneClient", return_value=dense_client), \
         patch.object(data_loader, "calculate_aida_grid", side_effect=fake_calculation):
        _, dense = data_loader.load_data(
            start_time="2026-06-21T20:00:00Z",
            end_time="2026-06-21T21:00:00Z",
            variables=["TEC"], region=GLOBAL, grid_step=2,
        )
    self.assertEqual(coarse_client.download_calls, 2)
    self.assertEqual(dense_client.download_calls, 2)
    self.assertEqual(coarse.metadata["local_map_points"], 91)
    self.assertEqual(dense.metadata["local_map_points"], 16471)

def test_duplicate_time_and_latency_download_once(self):
    client = FakeRawClient()
    with patch.object(data_loader, "SereneClient", return_value=client), \
         patch.object(data_loader, "calculate_aida_grid", side_effect=fake_calculation):
        _, status = data_loader.load_data(
            start_time="2026-06-21T20:00:00Z",
            end_time="2026-06-21T20:00:00Z",
        )
    self.assertEqual(client.download_calls, 1)
    self.assertEqual(status.metadata["aida_dataset_downloads"], 1)

def test_indices_only_result_does_not_claim_aida_success(self):
    client = FailingRawButWorkingIndicesClient()
    with patch.object(data_loader, "SereneClient", return_value=client):
        frame, status = data_loader.load_data(start_time="2026-06-21T20:00:00Z")
    self.assertTrue(set(frame["variable"]).issubset({"Kp", "ap"}))
    self.assertFalse(status.ok)
    self.assertEqual(status.source, "indices")
```

- [ ] **Step 2: Run loader tests and verify RED**

```bash
.venv/bin/python -m unittest tests.test_api_only_data_loader -v
```

Expected: FAIL because the loader still calls catalogue and param_2d methods.

- [ ] **Step 3: Implement request-key deduplication and adapter orchestration**

Replace catalogue logic with:

```python
requested_times = list(dict.fromkeys(value for value in (start_time, end_time) if value))
if not requested_times:
    request_specs = [(None, "ultra")]
else:
    request_specs = []
    current_year = pd.Timestamp.now(tz="UTC").year
    for value in requested_times:
        parsed = pd.to_datetime(value, errors="coerce", utc=True)
        if pd.isna(parsed):
            api_warnings.append(f"Invalid requested AIDA time: {value}")
            continue
        latency = "final" if parsed.year < current_year else "ultra"
        request_specs.append((parsed.isoformat(), latency))
request_specs = list(dict.fromkeys(request_specs))

aida_frames = []
download_messages = []
for index, (requested, latency) in enumerate(request_specs, start=1):
    if progress_callback:
        progress_callback(index, max(len(request_specs), 1))
    ok, message, payload = client.download_aida_raw_output(requested, latency)
    download_messages.append(message)
    if not ok or payload is None:
        api_warnings.append(message)
        continue
    try:
        frame = calculate_aida_grid(payload, r, grid_step, variables)
    except AidaGridError as exc:
        api_warnings.append(str(exc))
        continue
    if not frame.empty:
        aida_frames.append(frame)
```

Set `status.ok=True` only when `aida_frames` is non-empty. If only Kp/ap rows are available, return those rows with `status.source="indices"`, `status.ok=False`, and a message stating that regional AIDA data failed. Replace catalogue metadata with `download_messages`, distinct request specifications, actual output times from the calculated frames, upstream version, and raw download count.

- [ ] **Step 4: Remove obsolete param_2d sampling and run focused tests**

Delete `sample_aida_hdf5`, `_bilinear`, `_bracket`, and source-axis validation from `aida_grid.py`, then update `test_aida_grid.py` to cover exact axes, point estimates, bounds, and variable normalisation only.

Run:

```bash
.venv/bin/python -m unittest tests.test_api_only_data_loader tests.test_aida_adapter tests.test_aida_grid -v
```

Expected: all loader/adapter/grid tests PASS.

- [ ] **Step 5: Commit the loader migration**

```bash
git add streamlit_cloud_github/data_loader.py streamlit_cloud_github/aida_grid.py streamlit_cloud_github/tests/test_api_only_data_loader.py streamlit_cloud_github/tests/test_aida_grid.py
git commit -m "Load one raw AIDA state per requested time"
```

### Task 4: Update dashboard wording and regression guards

**Files:**
- Modify: `streamlit_cloud_github/app.py:142-310`
- Modify tests: `streamlit_cloud_github/tests/test_dashboard_settings.py`

- [ ] **Step 1: Add failing source-level UI regression assertions**

```python
def test_app_describes_raw_download_and_local_calculation(self):
    source = APP_PATH.read_text()
    self.assertIn("AIDA raw datasets downloaded", source)
    self.assertIn("calculated locally", source)
    self.assertNotIn("output catalog", source.lower())

def test_legacy_catalogue_code_is_removed(self):
    source = CLIENT_PATH.read_text()
    self.assertNotIn("BeautifulSoup", source)
    self.assertNotIn("fetch_aida_catalog", source)
    self.assertNotIn("param_2d", source)
    self.assertIn("breid-phys/aida-ionosphere", source)
```

- [ ] **Step 2: Run dashboard settings tests and verify RED**

```bash
.venv/bin/python -m unittest tests.test_dashboard_settings -v
```

Expected: FAIL on old metric/empty-state wording and catalogue source text.

- [ ] **Step 3: Update the UI messages**

Change sidebar/status text to:

```python
st.caption(
    f"Local map points: {local_points:,}. "
    "One raw AIDA state is downloaded per output time; this grid is calculated locally."
)
st.metric(
    "AIDA raw datasets downloaded",
    int(status.metadata.get("aida_dataset_downloads", 0)),
)
```

The connection button must test the raw-output endpoint. The empty state must say that raw states are temporary API responses interpreted by the official AIDA package, not local sample datasets. Add `_source_label` support for `indices` as `SERENE global indices only`.

- [ ] **Step 4: Run UI and Streamlit startup checks**

```bash
.venv/bin/python -m unittest tests.test_dashboard_settings -v
.venv/bin/python -c "from streamlit.testing.v1 import AppTest; at=AppTest.from_file('app.py').run(timeout=20); assert not at.exception, at.exception"
```

Expected: tests PASS and AppTest exits 0.

- [ ] **Step 5: Commit dashboard wording**

```bash
git add streamlit_cloud_github/app.py streamlit_cloud_github/tests/test_dashboard_settings.py
git commit -m "Explain raw AIDA downloads in dashboard"
```

### Task 5: Pin upstream dependencies and document attribution/deployment

**Files:**
- Modify: `streamlit_cloud_github/requirements.txt`
- Modify: `streamlit_cloud_github/.env.example`
- Modify: `streamlit_cloud_github/README.md`
- Modify: `streamlit_cloud_github/部署说明.md`
- Modify: `streamlit_cloud_github/云端修复说明.md`
- Test: `streamlit_cloud_github/tests/test_dashboard_settings.py`

- [ ] **Step 1: Add failing dependency/provenance tests**

```python
def test_upstream_aida_dependency_is_pinned(self):
    requirements = REQUIREMENTS_PATH.read_text()
    self.assertIn("numpy>=1.25,<2", requirements)
    self.assertIn("pandas<2", requirements)
    self.assertIn(
        "git+https://github.com/breid-phys/aida-ionosphere.git@v0.1.3",
        requirements,
    )
    self.assertNotIn("beautifulsoup4", requirements)

def test_example_uses_raw_api_host(self):
    example = ENV_EXAMPLE_PATH.read_text()
    self.assertIn("SERENE_API_BASE_URL=https://spaceweather.bham.ac.uk", example)
```

- [ ] **Step 2: Run settings tests and verify RED**

```bash
.venv/bin/python -m unittest tests.test_dashboard_settings -v
```

Expected: FAIL because the upstream dependency and compatible pins are absent.

- [ ] **Step 3: Update requirements and secrets example**

Use:

```text
streamlit
requests
python-dotenv
pandas<2
numpy>=1.25,<2
plotly
h5py>=3.11,<4
git+https://github.com/breid-phys/aida-ionosphere.git@v0.1.3
```

Remove BeautifulSoup. Set the example base URL to `https://spaceweather.bham.ac.uk` and keep only placeholder token text.

- [ ] **Step 4: Update documentation with explicit upstream attribution**

Document:

- the raw endpoint and one-download-per-time flow;
- the `breid-phys/aida-ionosphere` v0.1.3 scientific dependency and MIT source;
- nearby comments are attribution, not copied model code;
- a previously exposed token must be revoked and never committed;
- Streamlit Community Cloud must be deleted and redeployed to change Python;
- select Python 3.11 under Advanced settings, restore Secrets, and use `streamlit_cloud_github/app.py` as the entrypoint;
- a successful connection message and expected grid/download-count checks.

Use the official current deployment instruction source:
https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app/upgrade-python

- [ ] **Step 5: Run settings tests and scan for secrets/obsolete claims**

```bash
.venv/bin/python -m unittest tests.test_dashboard_settings -v
rg -n "serene\.bham\.ac\.uk/output|fetch_aida_catalog|param_2d|BeautifulSoup|github_pat_|ghp_" streamlit_cloud_github
```

Expected: tests PASS; search finds no obsolete catalogue implementation or credential patterns. Documentation may mention the rejected old approach only if clearly labelled historical.

- [ ] **Step 6: Commit deployment and attribution updates**

```bash
git add streamlit_cloud_github/requirements.txt streamlit_cloud_github/.env.example streamlit_cloud_github/README.md streamlit_cloud_github/部署说明.md streamlit_cloud_github/云端修复说明.md streamlit_cloud_github/tests/test_dashboard_settings.py
git commit -m "Document official AIDA interpreter deployment"
```

### Task 6: Full verification and live-deployment handoff

**Files:**
- Verify all modified project files
- Update checklist: `docs/superpowers/plans/2026-06-22-aida-raw-output-api.md`

- [ ] **Step 1: Run the complete automated suite**

```bash
cd streamlit_cloud_github
.venv/bin/python -m unittest discover -s tests -v
```

Expected: all tests PASS with no failure or error.

- [ ] **Step 2: Compile every application and test module**

```bash
.venv/bin/python -m compileall -q app.py config.py serene_client.py aida_adapter.py aida_grid.py data_loader.py alert_engine.py forecast_engine.py visualisation.py forecast_visualisation.py app_utils.py tests
```

Expected: exit 0 and no output.

- [ ] **Step 3: Run Streamlit's application test**

```bash
.venv/bin/python -c "from streamlit.testing.v1 import AppTest; at=AppTest.from_file('app.py').run(timeout=20); print('exceptions=', len(at.exception)); assert not at.exception, at.exception"
```

Expected: `exceptions= 0`.

- [ ] **Step 4: Verify repository scope and attribution**

```bash
git diff main --check
git status -sb
git log --oneline main..HEAD
rg -n "breid-phys/aida-ionosphere|download-output" streamlit_cloud_github docs/superpowers
```

Expected: no whitespace errors; only planned files are changed; attribution is present beside the API and adapter plus in documentation.

- [ ] **Step 5: Push a branch without Codex branding and open a normal PR**

```bash
git push -u origin aida-raw-output-api
gh pr create \
  --base main \
  --head aida-raw-output-api \
  --title "Use official AIDA raw output API" \
  --body-file /tmp/aida-raw-output-pr.md
```

The PR body must summarize upstream attribution, request-count behaviour, tests, Python 3.11 requirement, and the need for a rotated token. Do not include `codex` in the branch name, title, or PR body.

- [ ] **Step 6: Complete live acceptance after the user rotates the token**

In Streamlit Community Cloud:

1. Preserve the app URL and Secrets, then delete and redeploy the app.
2. Select Python 3.11 in Advanced settings.
3. Enter a newly rotated SERENE token; never reuse the token exposed in chat.
4. Click `Test SERENE API connection` and expect `Connected to SERENE AIDA raw-output API`.
5. Load a small 5-degree grid and verify AIDA rows/maps appear.
6. Compare a 30-degree global grid (91 local points) with a 2-degree global grid (16,471 local points); for the same requested times, the raw dataset download count must stay unchanged.
7. Confirm Kp/ap appear only in the global-indices panel.

If live authentication or output availability fails, record the HTTP status and user-facing message without logging the token. Do not mark live acceptance complete until a real raw HDF5 response is interpreted successfully.
