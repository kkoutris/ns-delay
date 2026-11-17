"""Client for the NS Reisinformatie API."""

import os
from typing import Any

import httpx
from dotenv import load_dotenv
from pydantic import (
    AliasPath,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
)

BASE_URL = "https://gateway.apiportal.ns.nl/reisinformatie-api/api/v2/departures"
TIMEOUT_SECONDS = 10


class Departure(BaseModel):
    """One departure from the NS v2 departures endpoint, in our own field names."""

    model_config = ConfigDict(frozen=True, validate_by_name=True)

    station: str
    train_number: int = Field(validation_alias=AliasPath("product", "number"))
    category: str = Field(validation_alias="trainCategory")
    direction: str
    planned_departure: AwareDatetime = Field(validation_alias="plannedDateTime")
    actual_departure: AwareDatetime | None = Field(default=None, validation_alias="actualDateTime")
    planned_track: str | None = Field(default=None, validation_alias="plannedTrack")
    actual_track: str | None = Field(default=None, validation_alias="actualTrack")
    cancelled: bool = False

    @field_validator("station")
    @classmethod
    def _uppercase_station(cls, value: str) -> str:
        return value.strip().upper()

    @computed_field
    @property
    def delay_minutes(self) -> int | None:
        """Whole minutes late (floored), or None if cancelled or no live time is known.

        Floor is provisional: it must match how the Rijden de Treinen archive rounds (check in B.4).
        """
        if self.cancelled or self.actual_departure is None:
            return None
        delay_seconds = (self.actual_departure - self.planned_departure).total_seconds()
        return int(delay_seconds // 60)


def parse_departures(payload: dict[str, Any], station: str) -> list[Departure]:
    """Turn a raw departures response (as returned by fetch_departures) into Departure objects.

    Pure function: no network, no I/O.

    Raises:
        ValueError: if the response has no payload.departures list.
        pydantic.ValidationError: if a departure is missing required fields or has bad values.
    """
    try:
        raw_departures = payload["payload"]["departures"]
    except (KeyError, TypeError) as err:
        raise ValueError("Response has no payload.departures; is this an error response?") from err
    return [Departure.model_validate({**raw, "station": station}) for raw in raw_departures]


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
