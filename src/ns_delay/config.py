"""Typed, validated project configuration loaded from config.toml."""

import tomllib
from datetime import date, timedelta
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _Frozen(BaseModel):
    """Base for config sections: read-only, and unknown keys are an error (catches typos)."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class TargetConfig(_Frozen):
    delay_threshold_minutes: int = Field(gt=0)


class SplitConfig(_Frozen):
    train_start: date
    valid_start: date
    test_start: date
    test_end: date

    @model_validator(mode="after")
    def _check_order(self) -> Self:
        if not self.train_start < self.valid_start < self.test_start < self.test_end:
            raise ValueError(
                "split dates must satisfy train_start < valid_start < test_start < test_end"
            )
        return self

    @property
    def first_month(self) -> tuple[int, int]:
        """(year, month) of the first month in the split."""
        return self.train_start.year, self.train_start.month

    @property
    def last_month(self) -> tuple[int, int]:
        """(year, month) of the last month in the split. test_end is exclusive."""
        last_day = self.test_end - timedelta(days=1)
        return last_day.year, last_day.month


class ScopeConfig(_Frozen):
    stations: tuple[str, ...] = Field(min_length=1)
    service_types: tuple[str, ...] = Field(min_length=1)

    @field_validator("stations")
    @classmethod
    def _normalise_stations(cls, codes: tuple[str, ...]) -> tuple[str, ...]:
        normalised = tuple(code.strip().upper() for code in codes)
        duplicates = sorted({code for code in normalised if normalised.count(code) > 1})
        if duplicates:
            raise ValueError(f"duplicate station codes: {duplicates}")
        return normalised


class Config(_Frozen):
    target: TargetConfig
    split: SplitConfig
    scope: ScopeConfig


def load_config(path: Path | None = None) -> Config:
    """Load and validate a config file. Without a path, load the config.toml shipped in the package.

    Raises:
        FileNotFoundError: if the file does not exist.
        tomllib.TOMLDecodeError: if the file is not valid TOML.
        pydantic.ValidationError: if the values do not match the schema.
    """
    source = path if path is not None else resources.files("ns_delay") / "config.toml"
    with source.open("rb") as f:
        raw: dict[str, Any] = tomllib.load(f)
    return Config.model_validate(raw)


@cache
def get_config() -> Config:
    """The project config, loaded once on first use and shared afterwards."""
    return load_config()
