"""Client for the NS Reisinformatie API."""

import os
from typing import Any

import httpx
from dotenv import load_dotenv

BASE_URL = "https://gateway.apiportal.ns.nl/reisinformatie-api/api/v2/departures"
TIMEOUT_SECONDS = 10


class MissingApiKeyError(RuntimeError):
    """Raised when the NS API key is not configured."""


def _get_api_key() -> str:
    """Return the NS API key from the environment, or raise a clear error."""
    load_dotenv()
    api_key = os.getenv("NS_API_KEY")
    if not api_key:
        raise MissingApiKeyError(
            "NS_API_KEY is not set. Copy .env.example to .env and add your key."
        )
    return api_key


def fetch_departures(station: str) -> dict[str, Any]:
    """Fetch live departures for a station code (e.g. 'ASD') as raw JSON.

    Raises:
        MissingApiKeyError: if NS_API_KEY is not configured.
        httpx.HTTPStatusError: on a 4xx/5xx response (e.g. 404 for an unknown station).
        httpx.RequestError: on network problems or timeouts.
    """
    response = httpx.get(
        BASE_URL,
        params={"station": station},
        headers={"Ocp-Apim-Subscription-Key": _get_api_key()},
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()
