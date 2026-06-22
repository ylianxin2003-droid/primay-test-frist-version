"""
Application configuration.

Loads settings from (in order of priority):
1. Streamlit Cloud Secrets (``st.secrets``) — used when deployed
2. Local ``.env`` file — used for development
3. System environment variables

No API token is hardcoded in this file.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent
_ENV_PATH = PROJECT_ROOT / ".env"

SERENE_API_BASE_URL: str = ""
SERENE_API_TOKEN: str = ""
SERENE_API_TIMEOUT: int = 30
SERENE_AUTH_SCHEME: str = "Token"


def _parse_timeout(value: object, default: int = 30) -> int:
    """Return a positive timeout without crashing app startup on bad secrets."""
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _load_env_file() -> None:
    """Load .env from this repository root only."""
    if not _ENV_PATH.exists():
        return

    for encoding in ("utf-8", "utf-8-sig", "utf-16", "utf-16-le"):
        try:
            load_dotenv(_ENV_PATH, encoding=encoding)
            return
        except UnicodeDecodeError:
            continue

    logger.warning(
        "Could not decode .env — re-save as UTF-8. "
        "Using environment / Streamlit secrets only."
    )


def _read_os_env() -> None:
    """Read from OS environment (and values set by dotenv)."""
    global SERENE_API_BASE_URL, SERENE_API_TOKEN, SERENE_API_TIMEOUT, SERENE_AUTH_SCHEME

    SERENE_API_BASE_URL = os.getenv("SERENE_API_BASE_URL", SERENE_API_BASE_URL).strip()
    SERENE_API_TOKEN = os.getenv("SERENE_API_TOKEN", SERENE_API_TOKEN).strip()
    SERENE_API_TIMEOUT = _parse_timeout(
        os.getenv("SERENE_API_TIMEOUT", str(SERENE_API_TIMEOUT)),
    )
    SERENE_AUTH_SCHEME = (
        os.getenv("SERENE_AUTH_SCHEME", SERENE_AUTH_SCHEME).strip() or "Token"
    )


def _get_secret(secrets: object, key: str) -> str | None:
    """Read a key from flat or ``[serene]`` nested Streamlit secrets."""
    try:
        if key in secrets:
            return str(secrets[key]).strip()
        if "serene" in secrets and key in secrets["serene"]:
            return str(secrets["serene"][key]).strip()
    except Exception:
        return None
    return None


def _load_streamlit_secrets() -> None:
    """Override with Streamlit Cloud secrets when the app is running on Streamlit."""
    try:
        import streamlit as st
    except ImportError:
        return

    try:
        secrets = st.secrets
    except Exception:
        return

    global SERENE_API_BASE_URL, SERENE_API_TOKEN, SERENE_API_TIMEOUT, SERENE_AUTH_SCHEME

    base = _get_secret(secrets, "SERENE_API_BASE_URL")
    token = _get_secret(secrets, "SERENE_API_TOKEN")
    timeout = _get_secret(secrets, "SERENE_API_TIMEOUT")
    scheme = _get_secret(secrets, "SERENE_AUTH_SCHEME")

    if base:
        SERENE_API_BASE_URL = base
    if token:
        SERENE_API_TOKEN = token
    if timeout:
        SERENE_API_TIMEOUT = _parse_timeout(timeout)
    if scheme:
        SERENE_AUTH_SCHEME = scheme


def reload_config() -> None:
    """Reload settings (.env + Streamlit secrets). Call once at app startup."""
    _load_env_file()
    _read_os_env()
    _load_streamlit_secrets()


reload_config()


def validate_config() -> list[str]:
    """Return user-facing warnings when SERENE settings are missing."""
    messages: list[str] = []

    if not SERENE_API_BASE_URL:
        messages.append(
            "SERENE_API_BASE_URL is not set. "
            "For local dev: copy .env.example to .env. "
            "For Streamlit Cloud: add secrets in the app settings."
        )

    if not SERENE_API_TOKEN:
        messages.append(
            "SERENE_API_TOKEN is not set. "
            "Without it, authenticated SERENE API endpoints may be unavailable."
        )

    return messages
