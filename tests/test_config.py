"""Tests for the project config: the shipped config.toml, and the validation rules."""

import csv
from pathlib import Path

import pytest
from pydantic import ValidationError

from ns_delay.config import get_config, load_config

# Rijden de Treinen stations list (CC BY 4.0), copied from data/raw so tests run without downloads.
STATIONS_CSV = Path(__file__).parent / "fixtures" / "stations-2023-09-nl.csv"

VALID_TOML = """
[target]
delay_threshold_minutes = 5

[split]
train_start = 2024-01-01
valid_start = 2025-07-01
test_start = 2026-01-01
test_end = 2026-11-01

[scope]
stations = ["ASD", "UT"]
service_types = ["Sprinter", "Intercity"]
"""


@pytest.fixture
def write_config(tmp_path: Path):
    """Write TOML text to a temporary file and return its path."""

    def _write(text: str) -> Path:
        path = tmp_path / "config.toml"
        path.write_text(text, encoding="utf-8")
        return path

    return _write


# --- The shipped config ---------------------------------------------------------------------


def test_shipped_config_loads() -> None:
    config = get_config()
    assert len(config.scope.stations) == 20
    assert config.target.delay_threshold_minutes == 5


def test_every_station_exists_in_stations_file() -> None:
    with STATIONS_CSV.open(encoding="utf-8", newline="") as f:
        known_codes = {row["code"] for row in csv.DictReader(f)}
    unknown = set(get_config().scope.stations) - known_codes
    assert not unknown, f"station codes not in the stations file: {sorted(unknown)}"


def test_get_config_is_loaded_once() -> None:
    assert get_config() is get_config()


# --- Validation rules -----------------------------------------------------------------------


def test_valid_file_loads(write_config) -> None:
    config = load_config(write_config(VALID_TOML))
    assert config.scope.stations == ("ASD", "UT")


def test_station_codes_are_normalised(write_config) -> None:
    config = load_config(write_config(VALID_TOML.replace('"ASD", "UT"', '" asd", "ut"')))
    assert config.scope.stations == ("ASD", "UT")


@pytest.mark.parametrize(
    "stations",
    [
        pytest.param('"ASD", "ASD"', id="exact-duplicate"),
        pytest.param('"ASD", "asd"', id="duplicate-after-uppercasing"),
    ],
)
def test_duplicate_stations_are_rejected(write_config, stations: str) -> None:
    with pytest.raises(ValidationError, match="duplicate station codes"):
        load_config(write_config(VALID_TOML.replace('"ASD", "UT"', stations)))


def test_split_dates_out_of_order_are_rejected(write_config) -> None:
    swapped = VALID_TOML.replace("test_start = 2026-01-01", "test_start = 2025-01-01")
    with pytest.raises(ValidationError, match="split dates must satisfy"):
        load_config(write_config(swapped))


def test_unknown_key_is_rejected(write_config) -> None:
    typo = VALID_TOML.replace("delay_threshold_minutes", "delay_treshold_minutes")
    with pytest.raises(ValidationError, match="delay_treshold_minutes"):
        load_config(write_config(typo))


def test_threshold_must_be_positive(write_config) -> None:
    zero = VALID_TOML.replace("delay_threshold_minutes = 5", "delay_threshold_minutes = 0")
    with pytest.raises(ValidationError, match="greater than 0"):
        load_config(write_config(zero))


def test_config_is_frozen() -> None:
    with pytest.raises(ValidationError, match="frozen"):
        get_config().target.delay_threshold_minutes = 10
