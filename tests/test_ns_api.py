"""Tests for the NS API module: parsing and delay rules. No network access."""

import copy
import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from ns_delay.ns_api import Departure, parse_departures

FIXTURES_DIR = Path(__file__).parent / "fixtures"
CET = timezone(timedelta(hours=1))
PLANNED = datetime(2026, 11, 16, 18, 54, tzinfo=CET)


# --- Fixtures and helpers -------------------------------------------------------------------


@pytest.fixture
def asd_payload() -> dict[str, Any]:
    """The saved real NS response for Amsterdam Centraal (40 departures)."""
    return json.loads((FIXTURES_DIR / "departures_asd.json").read_text(encoding="utf-8"))


@pytest.fixture
def asd_departures(asd_payload: dict[str, Any]) -> list[Departure]:
    """The fixture payload, parsed. Station passed in lowercase on purpose."""
    return parse_departures(asd_payload, "asd")


def make_departure(**overrides: Any) -> Departure:
    """Build a Departure with sensible defaults; each test overrides only what it tests."""
    fields = {
        "station": "ASD",
        "train_number": 3069,
        "category": "IC",
        "direction": "Nijmegen",
        "planned_departure": PLANNED,
    }
    return Departure(**(fields | overrides))


# --- Parsing the real fixture ---------------------------------------------------------------


def test_parses_all_departures(asd_departures: list[Departure]) -> None:
    assert len(asd_departures) == 40


def test_first_departure_matches_fixture(asd_departures: list[Departure]) -> None:
    first = asd_departures[0]
    assert first.train_number == 3069
    assert first.category == "IC"
    assert first.delay_minutes == 5  # planned 18:54:00, actual 18:59:07


def test_cancelled_departures_have_no_delay(asd_departures: list[Departure]) -> None:
    cancelled = [d for d in asd_departures if d.cancelled]
    assert len(cancelled) == 2
    assert all(d.delay_minutes is None for d in cancelled)


def test_station_code_is_uppercased(asd_departures: list[Departure]) -> None:
    assert {d.station for d in asd_departures} == {"ASD"}


def test_times_are_timezone_aware(asd_departures: list[Departure]) -> None:
    assert all(d.planned_departure.utcoffset() is not None for d in asd_departures)


def test_parse_does_not_modify_payload(asd_payload: dict[str, Any]) -> None:
    before = copy.deepcopy(asd_payload)
    parse_departures(asd_payload, "asd")
    assert asd_payload == before


# --- Delay rules ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("delay", "expected_minutes"),
    [
        pytest.param(timedelta(0), 0, id="on-time"),
        pytest.param(timedelta(seconds=59), 0, id="59s-is-still-0"),
        pytest.param(timedelta(minutes=5), 5, id="exactly-5min"),
        pytest.param(timedelta(minutes=5, seconds=7), 5, id="5min7s-floors-to-5"),
        pytest.param(timedelta(seconds=-30), -1, id="early-floors-to-minus-1"),
    ],
)
def test_delay_is_floored_to_whole_minutes(delay: timedelta, expected_minutes: int) -> None:
    departure = make_departure(actual_departure=PLANNED + delay)
    assert departure.delay_minutes == expected_minutes


def test_missing_actual_time_gives_no_delay() -> None:
    assert make_departure(actual_departure=None).delay_minutes is None


def test_cancelled_gives_no_delay_even_with_actual_time() -> None:
    departure = make_departure(cancelled=True, actual_departure=PLANNED + timedelta(minutes=10))
    assert departure.delay_minutes is None


def test_delay_is_correct_across_timezones() -> None:
    # 17:59 UTC is 18:59 CET, so 5 minutes after the planned 18:54 CET.
    actual_utc = datetime(2026, 11, 16, 17, 59, tzinfo=UTC)
    assert make_departure(actual_departure=actual_utc).delay_minutes == 5


# --- Validation and error handling ----------------------------------------------------------


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        make_departure(planned_departure=datetime(2026, 11, 16, 18, 54))


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"code": 401, "message": "Access denied"}, id="error-response"),
        pytest.param({"payload": None}, id="payload-is-null"),
    ],
)
def test_error_payload_raises_value_error(payload: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="payload.departures"):
        parse_departures(payload, "ASD")


def test_empty_departure_list_is_not_an_error() -> None:
    assert parse_departures({"payload": {"departures": []}}, "ASD") == []


def test_departure_is_frozen() -> None:
    departure = make_departure()
    with pytest.raises(ValidationError, match="frozen"):
        departure.cancelled = True
