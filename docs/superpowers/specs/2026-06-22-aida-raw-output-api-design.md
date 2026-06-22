# AIDA Raw Output API Design

## Objective

Replace the unsupported attempt to authenticate against SERENE web catalogue
pages with the official AIDA raw-output API and interpreter published by
Benjamin Reid. For each distinct requested output time, the dashboard must make
one raw-state download and calculate all requested latitude/longitude points
locally.

## Upstream scientific source

The scientific API contract and interpretation method come from Benjamin
Reid's MIT-licensed `breid-phys/aida-ionosphere` repository:

- Repository and usage: https://github.com/breid-phys/aida-ionosphere
- Raw download implementation: https://github.com/breid-phys/aida-ionosphere/blob/main/aida/api.py
- Version used by this project: `v0.1.3`

Project code that follows this contract will contain nearby attribution
comments. The dashboard will depend on the upstream package rather than copy
its scientific model implementation.

## Selected approach

Use the upstream `aida` package for raw-state interpretation and grid
calculation, while retaining a small dashboard-owned HTTP client for download
counting, in-memory caching, error reporting, and Streamlit Secrets.

The official package currently requires Python 3.9-3.11-compatible versions of
`pandas<2` and `numpy<2`; Streamlit Cloud will therefore be pinned to Python
3.11. The dependency will be installed from the upstream Git tag so deployments
are reproducible.

## Data flow

```text
Streamlit Secrets API token
        |
        v
GET https://spaceweather.bham.ac.uk/api/download-output/
Authorization: Token <token>
payload: file_time/latest, product, file_type=raw
        |
        v
one raw AIDA HDF5 response per distinct requested time
        |
        v
temporary file -> aida.AIDAState.readFile()
        |
        v
AIDAState.calc(lat, lon, grid="3D", TEC=True, MUF3000=True)
        |
        v
long-form DataFrame -> regional maps, alerts, and forecasts
```

Kp/ap remain a separate global resource and never become regional map cells.

## Components

### `serene_client.py`

Remove HTML catalogue parsing and `param_2d` web-page downloads. Add a typed raw
output request keyed by requested time and latency (`ultra`, `rapid`, or
`final`). Follow the upstream request contract exactly:

- endpoint: `/api/download-output/`
- method: `GET`
- header: `Authorization: Token ...`
- latest payload: `latest=True`, `product=<latency>`, `file_type=raw`
- historical payload: `file_time=<ISO time>`, `product=<latency>`,
  `file_type=raw`

Cache successful response bytes by request key. Never log or store the token.
Return clear messages for 401/403, unavailable output times, timeouts, HTML
responses, empty content, and invalid HDF5 responses.

### `aida_adapter.py`

Provide a focused boundary around the upstream scientific package:

1. Validate the requested coordinate axes with the existing exact-spacing
   helper.
2. Write the raw response to a short-lived temporary `.h5` file.
3. Load it with `aida.AIDAState.readFile()`.
4. Call `AIDAState.calc()` once for the complete regular grid with
   `grid="3D"`, `TEC=True`, `MUF3000=True`, `collapse_particles=True`, and
   `as_dict=True`.
5. Convert selected fields to the dashboard schema.

The upstream `(longitude, latitude)` array orientation must be retained.
Dashboard naming maps upstream `MUF3000` to `MUF3000F2`. Supported variables
remain `TEC`, `foF2`, `MUF3000F2`, `NmF2`, and `hmF2`.

### `data_loader.py`

For each unique requested start/end time:

- choose `ultra` for current-year requests and `final` for earlier archive
  requests;
- deduplicate identical request keys;
- download one raw state for each key;
- calculate the entire selected regional grid locally;
- record requested time, actual model time, download count, local map point
  count, latency, and upstream package provenance in status metadata.

Grid spacing and bounding-box size must never alter the raw download count.

### Configuration and deployment

- Set `SERENE_API_BASE_URL=https://spaceweather.bham.ac.uk`.
- Add a Streamlit `runtime.txt` selecting Python 3.11.
- Pin the upstream package to `v0.1.3` in `requirements.txt`.
- Keep the API token only in Streamlit Secrets or a gitignored local `.env`.
- Document that previously exposed tokens must be revoked before deployment.

## User interface

Keep the current controls and global Kp/ap panel. Change connection and status
messages to refer to the AIDA raw-output API rather than the output catalogue.
Continue to show separate metrics for raw datasets downloaded and local map
points so the supervisor can verify the request-count behaviour.

## Error handling

- Missing token/base URL: configuration warning, no scientific fallback.
- 401/403: explicit token/authentication error.
- 404 or unavailable requested time: output-unavailable warning.
- Non-HDF5/HTML body: reject before invoking the interpreter.
- Upstream interpreter error: show a concise model-reading/calculation warning.
- Kp/ap failure: retain successfully calculated AIDA rows and show a warning.
- AIDA failure with successful Kp/ap: do not describe the regional AIDA load as
  successful; global indices may still be displayed independently.

## Testing and acceptance criteria

Automated tests will establish that:

1. Raw download requests match the upstream endpoint, headers, and payload.
2. The token never appears in logs or user-facing messages.
3. Identical request keys download once, including across denser grids.
4. Different requested output times each download once.
5. The adapter preserves exact grid spacing and longitude/latitude orientation.
6. `MUF3000` is exposed as `MUF3000F2`.
7. HTML/login responses and invalid HDF5 content are rejected.
8. Kp/ap remain global-only.
9. All existing dashboard tests and Streamlit startup checks pass.

Live acceptance requires a newly rotated SERENE token in Streamlit Secrets.
No real token will be placed in source code, tests, commits, or documentation.
