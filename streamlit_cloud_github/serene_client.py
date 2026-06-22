"""Authenticated SERENE client for AIDA HDF5 outputs and global Kp/ap data."""

from __future__ import annotations

import logging
import os
import time
from io import StringIO
from typing import Any

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import (
    SERENE_API_BASE_URL,
    SERENE_API_TIMEOUT,
    SERENE_API_TOKEN,
    SERENE_AUTH_SCHEME,
)

KP_AP_CACHE_TTL_SECONDS = int(os.getenv("SERENE_KP_AP_CACHE_TTL", "3600"))

logger = logging.getLogger(__name__)

# ── API Endpoints ───────────────────────────────────────────────────────────
ENDPOINTS: dict[str, str] = {
    "aida_raw_output": "/api/download-output/",
    "calc": "/api/calc/",
    "kp_ap": "/resources/download/Indices__Kp_ap.csv/",
    # Placeholders (not yet documented for Birmingham deployment):
    "health": "/api/health/",
    "models": "/api/models/",
    "variables": "/api/variables/",
    "model_output": "/api/model-output/",
}

class SereneAPIError(Exception):
    """Non-fatal SERENE API error with a user-readable message."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class SereneClient:
    """HTTP client for the SERENE API.

    Parameters
    ----------
    base_url : str, optional
        Override ``SERENE_API_BASE_URL``.
    token : str, optional
        Override ``SERENE_API_TOKEN``.
    timeout : int, optional
        Request timeout in seconds.
    auth_scheme : str, optional
        Official SERENE value is ``Token`` (override ``SERENE_AUTH_SCHEME``).
    """

    _kp_ap_csv_cache: tuple[float, str] | None = None
    _aida_raw_cache: dict[tuple[str, str], bytes] = {}

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        timeout: int | None = None,
        auth_scheme: str | None = None,
    ) -> None:
        self.base_url = (base_url or SERENE_API_BASE_URL).rstrip("/")
        self.token = token or SERENE_API_TOKEN
        self.timeout = timeout if timeout is not None else SERENE_API_TIMEOUT
        self.auth_scheme = (auth_scheme or SERENE_AUTH_SCHEME).strip()

        self._session = requests.Session()
        retry_strategy = Retry(
            total=2,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    # ── Low-level request ───────────────────────────────────────────────────

    def _auth_headers(self) -> dict[str, str]:
        if not self.token:
            return {}
        # Official: Authorization: Token <token>
        return {"Authorization": f"{self.auth_scheme} {self.token}"}

    @staticmethod
    def _calc_form(lat: float, lon: float) -> dict[str, float]:
        """Form body for POST /api/calc/ (official fields only)."""
        return {"latitude": float(lat), "longitude": float(lon)}

    def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> tuple[bool, str, Any]:
        """Execute an HTTP request.

        Returns
        -------
        tuple[bool, str, Any]
            ``(success, message, parsed_body_or_none)``
        """
        if not self.base_url:
            return False, "SERENE_API_BASE_URL is not configured.", None

        url = f"{self.base_url}{endpoint}"
        headers = self._auth_headers()

        try:
            response = self._session.request(
                method=method.upper(),
                url=url,
                headers=headers,
                params=params,
                json=json,
                data=data,
                timeout=self.timeout,
            )
        except requests.exceptions.Timeout:
            msg = f"SERENE API request timed out after {self.timeout}s: {url}"
            logger.warning(msg)
            return False, msg, None
        except requests.exceptions.ConnectionError as exc:
            msg = (
                f"Cannot connect to SERENE API at {self.base_url}. "
                f"Check SERENE_API_BASE_URL and network. ({exc})"
            )
            logger.warning(msg)
            return False, msg, None
        except requests.exceptions.RequestException as exc:
            msg = f"SERENE API request failed: {exc}"
            logger.warning(msg)
            return False, msg, None

        if response.status_code == 401:
            msg = (
                "SERENE API returned 401 Unauthorized. "
                "Check SERENE_API_TOKEN. Official auth is: Authorization: Token <token>."
            )
            logger.warning(msg)
            return False, msg, None

        if response.status_code == 403:
            msg = "SERENE API returned 403 Forbidden. Token may lack permission."
            logger.warning(msg)
            return False, msg, None

        if response.status_code == 404:
            msg = f"SERENE API endpoint not found (404): {url}"
            logger.warning(msg)
            return False, msg, None

        if response.status_code >= 500:
            msg = f"SERENE API server error ({response.status_code}): {url}"
            logger.warning(msg)
            return False, msg, None

        if not response.ok:
            msg = f"SERENE API unexpected status {response.status_code}: {url}"
            logger.warning(msg)
            return False, msg, None

        if not response.content:
            return True, "OK (empty response body)", None

        try:
            body = response.json()
        except ValueError:
            text = response.text.strip()
            if not text:
                return True, "OK (empty response)", None
            return True, "OK (non-JSON response)", text

        if body is None or body == "" or body == [] or body == {}:
            return True, "OK (no data in response)", body

        return True, "OK", body

    # ── High-level API methods ──────────────────────────────────────────────

    def test_connection(self) -> tuple[bool, str]:
        """Verify connectivity and authentication."""
        if not self.base_url:
            return False, "SERENE_API_BASE_URL is not configured."
        if not self.token:
            return False, "SERENE_API_TOKEN is not configured."

        ok, msg, _payload = self.download_aida_raw_output(None, "ultra")
        if ok:
            return (
                True,
                f"Connected to SERENE AIDA raw-output API at {self.base_url}.",
            )

        if "401" in msg or "403" in msg:
            return False, msg

        return False, msg

    def download_aida_raw_output(
        self,
        requested_time: str | None,
        latency: str,
    ) -> tuple[bool, str, bytes | None]:
        """Download one raw AIDA state using Benjamin Reid's official contract.

        Source: https://github.com/breid-phys/aida-ionosphere/blob/main/aida/api.py
        (``downloadOutput``, MIT License). This method follows the upstream HTTP
        request; scientific state interpretation remains in the upstream package.
        """
        if latency not in {"ultra", "rapid", "final"}:
            return False, f"Unsupported AIDA latency: {latency}", None
        if not self.base_url:
            return False, "SERENE_API_BASE_URL is not configured.", None
        if not self.token:
            return False, "SERENE_API_TOKEN is not configured.", None

        if requested_time is None:
            cache_time = "latest"
            request_data: dict[str, Any] = {
                "latest": True,
                "product": latency,
                "file_type": "raw",
            }
        else:
            parsed = pd.to_datetime(requested_time, errors="coerce", utc=True)
            if pd.isna(parsed):
                return False, f"Invalid requested AIDA time: {requested_time}", None
            cache_time = parsed.isoformat()
            # Upstream ``downloadOutput`` sends ``np.datetime64.astype('str')``:
            # an ISO value without a timezone suffix. Preserve that exact contract.
            upstream_file_time = parsed.tz_convert("UTC").tz_localize(None).isoformat()
            request_data = {
                "file_time": upstream_file_time,
                "product": latency,
                "file_type": "raw",
            }

        cache_key = (cache_time, latency)
        cached = type(self)._aida_raw_cache.get(cache_key)
        if cached is not None:
            return True, f"Loaded cached AIDA raw state for {cache_time}.", cached

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
            return (
                False,
                f"SERENE AIDA raw-output API returned status {response.status_code}.",
                None,
            )

        content = bytes(getattr(response, "content", b""))
        headers = getattr(response, "headers", {}) or {}
        content_type = str(headers.get("Content-Type", "")).lower()
        if (
            not content
            or "html" in content_type
            or not content.startswith(b"\x89HDF\r\n\x1a\n")
        ):
            return False, "SERENE AIDA raw-output API returned a non-HDF5 response.", None

        type(self)._aida_raw_cache[cache_key] = content
        return True, f"Downloaded AIDA raw state for {cache_time}.", content

    def fetch_available_models(self) -> tuple[bool, str, list[str]]:
        """List models exposed by the API.

        Falls back to a static list when the models endpoint is not yet available.
        """
        ok, msg, data = self._request("GET", ENDPOINTS["models"])
        if ok and data is not None:
            models = _extract_string_list(data, keys=("models", "results", "data"))
            if models:
                return True, msg, models

        # ★ Placeholder until SERENE documents GET /api/models/
        return True, "Using AIDA (models endpoint not available).", ["AIDA"]

    def fetch_available_variables(self, model: str | None = None) -> tuple[bool, str, list[str]]:
        """List variables for a model."""
        params: dict[str, Any] = {}
        if model:
            params["model"] = model

        ok, msg, data = self._request("GET", ENDPOINTS["variables"], params=params or None)
        if ok and data is not None:
            variables = _extract_string_list(data, keys=("variables", "results", "data"))
            if variables:
                return True, msg, variables

        # ★ Placeholder defaults for dashboard prototyping
        defaults = ["TEC", "foF2", "MUF3000F2", "NmF2", "hmF2"]
        note = "Using default variable list (variables endpoint not available)."
        if not ok and "404" in msg:
            return True, note, defaults
        if ok:
            return True, note, defaults
        return False, msg, defaults

    def fetch_kp_ap_indices(
        self,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> tuple[bool, str, pd.DataFrame]:
        """Fetch SERENE Kp/ap API resource data and return dashboard rows."""
        cached = type(self)._kp_ap_csv_cache
        if cached and time.monotonic() - cached[0] < KP_AP_CACHE_TTL_SECONDS:
            ok, msg, data = True, "OK (cached)", cached[1]
        else:
            ok, msg, data = self._request_from_base(
                "GET",
                "https://serene.bham.ac.uk",
                ENDPOINTS["kp_ap"],
            )
            if ok and isinstance(data, str):
                type(self)._kp_ap_csv_cache = (time.monotonic(), data)
        if not ok or not isinstance(data, str):
            return False, msg, pd.DataFrame()

        df = self.parse_kp_ap_csv(data, start_time=start_time, end_time=end_time)
        if df.empty:
            return False, "SERENE Kp/ap API returned no rows for the selected range.", df

        return True, f"Loaded {len(df)} Kp/ap row(s) from SERENE API.", df

    @staticmethod
    def parse_kp_ap_csv(
        csv_text: str,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> pd.DataFrame:
        """Parse SERENE ``Kp_ap.csv`` into the dashboard long-form schema."""
        raw = pd.read_csv(StringIO(csv_text))
        if raw.empty or "time" not in raw.columns:
            return pd.DataFrame()

        raw["time"] = pd.to_datetime(raw["time"], errors="coerce", utc=True)
        raw = raw.dropna(subset=["time"])

        start = _parse_optional_utc(start_time)
        end = _parse_optional_utc(end_time)
        if start is not None and end is not None and start > end:
            start, end = end, start
        if start is not None:
            raw = raw[raw["time"] >= start]
        if end is not None:
            raw = raw[raw["time"] <= end]

        rows: list[dict[str, Any]] = []
        for _, row in raw.iterrows():
            for variable in ("Kp", "ap"):
                if variable not in raw.columns:
                    continue
                value = pd.to_numeric(pd.Series([row[variable]]), errors="coerce").iloc[0]
                if pd.isna(value):
                    continue
                rows.append({
                    "time": row["time"],
                    "lat": None,
                    "lon": None,
                    "alt": None,
                    "variable": variable,
                    "value": float(value),
                    "model": "SERENE Indices",
                    "source": "SERENE API Kp/ap",
                })

        return pd.DataFrame(rows)

    def _request_from_base(
        self,
        method: str,
        base_url: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> tuple[bool, str, Any]:
        """Execute a request against a non-/api/calc SERENE base URL."""
        url = f"{base_url.rstrip('/')}{endpoint}"
        try:
            response = self._session.request(
                method=method.upper(),
                url=url,
                headers={},
                params=params,
                timeout=self.timeout,
            )
        except requests.exceptions.RequestException as exc:
            msg = f"SERENE resource request failed: {exc}"
            logger.warning(msg)
            return False, msg, None

        if not response.ok:
            msg = f"SERENE resource unexpected status {response.status_code}: {url}"
            logger.warning(msg)
            return False, msg, None

        text = response.text.strip()
        if not text:
            return False, "SERENE resource returned an empty response.", None
        return True, "OK", text

    # ── Response parsing ────────────────────────────────────────────────────

    def parse_response_to_dataframe(
        self,
        response_data: Any,
        model: str | None = None,
    ) -> pd.DataFrame:
        """Convert API JSON into the standard long-form schema."""
        if response_data is None:
            logger.warning("parse_response_to_dataframe received None.")
            return pd.DataFrame()

        # Batch wrapper for gridded point sampling.
        if isinstance(response_data, list) and response_data and isinstance(response_data[0], dict):
            if "response" in response_data[0]:
                frames = []
                for item in response_data:
                    sub = self.parse_response_to_dataframe(
                        item.get("response"),
                        model=item.get("model") or model,
                    )
                    if sub.empty:
                        continue
                    if item.get("lat") is not None:
                        if "lat" not in sub.columns:
                            sub["lat"] = item["lat"]
                        else:
                            sub["lat"] = sub["lat"].fillna(item["lat"])
                    if item.get("lon") is not None:
                        if "lon" not in sub.columns:
                            sub["lon"] = item["lon"]
                        else:
                            sub["lon"] = sub["lon"].fillna(item["lon"])
                    frames.append(sub)
                if frames:
                    return pd.concat(frames, ignore_index=True)
                return pd.DataFrame()

        records = _extract_records(response_data)
        if not records:
            logger.warning("Could not extract records from SERENE response.")
            return pd.DataFrame()

        df = pd.DataFrame(records)
        df = _normalise_columns(df)

        if model and "model" not in df.columns:
            df["model"] = model

        for col in ("time", "timestamp", "date", "datetime"):
            if col in df.columns:
                try:
                    df["time"] = pd.to_datetime(df[col])
                except (ValueError, TypeError):
                    pass
                break

        return df

    # ── Backward-compatible helpers (used by scripts / tests) ───────────────

    def fetch_space_weather(self, lat: float, lon: float) -> tuple[bool, str, Any]:
        """Single-point query — official ``POST /api/calc/`` format."""
        return self._request(
            "POST",
            ENDPOINTS["calc"],
            data=self._calc_form(lat, lon),
        )


# ── Internal helpers ────────────────────────────────────────────────────────


def _extract_string_list(data: Any, keys: tuple[str, ...]) -> list[str]:
    if isinstance(data, list):
        return [str(x) for x in data]
    if isinstance(data, dict):
        for key in keys:
            if key in data and isinstance(data[key], list):
                return [str(x) for x in data[key]]
    return []


def _parse_optional_utc(value: str | None) -> pd.Timestamp | None:
    if not value:
        return None
    try:
        parsed = pd.to_datetime(value, errors="coerce", utc=True)
    except (TypeError, ValueError):
        return None
    if pd.isna(parsed):
        return None
    return parsed


def _parse_calc_text_response(text: str) -> list[dict[str, Any]]:
    """Parse official /api/calc/ plain-text lines, e.g. ``TEC: 7.85``."""
    records: list[dict[str, Any]] = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        name, _, raw_val = line.partition(":")
        name = name.strip()
        raw_val = raw_val.strip()
        try:
            value = float(raw_val)
        except ValueError:
            value = raw_val
        records.append({"variable": name, "value": value})
    if not records and text.strip():
        records.append({"value": text.strip()})
    return records


def _extract_records(response_data: Any) -> list[dict[str, Any]]:
    if isinstance(response_data, str):
        parsed = _parse_calc_text_response(response_data)
        return parsed if parsed else [{"value": response_data}]

    if isinstance(response_data, list):
        if response_data and isinstance(response_data[0], dict) and "response" in response_data[0]:
            return []
        return [r for r in response_data if isinstance(r, dict)]

    if isinstance(response_data, dict):
        for key in ("data", "results", "records", "output", "variables", "grid", "parameters"):
            if key not in response_data:
                continue
            candidate = response_data[key]
            if isinstance(candidate, list):
                return [r for r in candidate if isinstance(r, dict)]
            if isinstance(candidate, dict):
                return _columnar_to_records(candidate)

        flat = _flatten_dict(response_data)
        return flat if flat else [response_data]

    return []


def _columnar_to_records(data: dict[str, Any]) -> list[dict[str, Any]]:
    if not data:
        return []
    arrays = {k: v if isinstance(v, (list, tuple)) else [v] for k, v in data.items()}
    length = max(len(v) for v in arrays.values())
    return [
        {key: values[i] if i < len(values) else None for key, values in arrays.items()}
        for i in range(length)
    ]


def _flatten_dict(data: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for key, val in data.items():
        if isinstance(val, dict) and "value" in val:
            record: dict[str, Any] = {"variable": key}
            record.update(val)
            records.append(record)
    return records


def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    mapping = {
        "timestamp": "time",
        "date": "time",
        "datetime": "time",
        "t": "time",
        "latitude": "lat",
        "longitude": "lon",
        "long": "lon",
        "altitude": "alt",
        "height": "alt",
        "h": "alt",
        "var": "variable",
        "param": "variable",
        "parameter": "variable",
        "field": "variable",
        "val": "value",
        "data_value": "value",
    }
    rename = {k: v for k, v in mapping.items() if k in df.columns and v not in df.columns}
    return df.rename(columns=rename)
