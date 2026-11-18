"""Convert the raw monthly Rijden de Treinen CSVs into typed Parquet, one file per month.

Keeps every stop of every trip (all stations, all service types): filtering to the project
scope happens later, so trip context (origin, stop order) stays available for features.
Drops leaky columns and renames everything to snake_case.

Usage:
    uv run python -m ns_delay.process                       # whole split period from config.toml
    uv run python -m ns_delay.process --start 2024-01 --end 2024-03
"""

import argparse
import gzip
import logging
import time
from pathlib import Path

import duckdb

from ns_delay.config import get_config
from ns_delay.download import DEFAULT_RAW_DIR, month_range, parse_month

DEFAULT_PROCESSED_DIR = Path("data/processed/services")

# Every column of the raw file, in file order: (source name, output name, DuckDB type).
# Output name None = read but not written. Types are fixed here instead of guessed per file,
# so all monthly Parquet files share exactly the same schema.
SCHEMA: tuple[tuple[str, str | None, str], ...] = (
    ("Service:RDT-ID", "service_id", "BIGINT"),
    ("Service:Date", "service_date", "DATE"),
    ("Service:Type", "service_type", "VARCHAR"),
    ("Service:Company", "company", "VARCHAR"),
    ("Service:Train number", "train_number", "INTEGER"),
    ("Service:Completely cancelled", "service_completely_cancelled", "BOOLEAN"),
    ("Service:Partly cancelled", "service_partly_cancelled", "BOOLEAN"),
    ("Service:Maximum delay", None, "INTEGER"),  # dropped: computed over the whole trip (leakage)
    ("Stop:RDT-ID", "stop_id", "BIGINT"),
    ("Stop:Station code", "station_code", "VARCHAR"),
    ("Stop:Station name", "station_name", "VARCHAR"),
    ("Stop:Arrival time", "arrival_time", "TIMESTAMPTZ"),
    ("Stop:Arrival delay", "arrival_delay", "INTEGER"),
    ("Stop:Arrival cancelled", "arrival_cancelled", "BOOLEAN"),
    ("Stop:Departure time", "departure_time", "TIMESTAMPTZ"),
    ("Stop:Departure delay", "departure_delay", "INTEGER"),
    ("Stop:Departure cancelled", "departure_cancelled", "BOOLEAN"),
    ("Stop:Platform change", "platform_change", "BOOLEAN"),
    ("Stop:Planned platform", "planned_platform", "VARCHAR"),
    ("Stop:Actual platform", "actual_platform", "VARCHAR"),
)

logger = logging.getLogger(__name__)


class SchemaMismatchError(ValueError):
    """Raised when a raw file's header is not the one SCHEMA expects."""


def _sql_string(value: str | Path) -> str:
    """Quote a value as a SQL string literal: wrap in single quotes, double any inside."""
    return "'" + str(value).replace("'", "''") + "'"


def _check_header(csv_path: Path) -> None:
    """Fail loudly if the file's columns differ from SCHEMA (columns are mapped by position)."""
    with gzip.open(csv_path, "rt", encoding="utf-8") as f:
        header = f.readline().rstrip("\r\n").split(",")
    expected = [source for source, _, _ in SCHEMA]
    if header != expected:
        raise SchemaMismatchError(f"{csv_path.name}: expected columns {expected}, got {header}")


def build_select(csv_path: Path) -> str:
    """The SELECT that reads one raw CSV with the fixed schema and renames the columns."""
    columns = ", ".join(f"{_sql_string(source)}: '{sql_type}'" for source, _, sql_type in SCHEMA)
    select_list = ",\n        ".join(
        f'"{source}" AS {name}' for source, name, _ in SCHEMA if name is not None
    )
    return f"""
    SELECT
        {select_list}
    FROM read_csv(
        {_sql_string(csv_path)},
        header = true,
        auto_detect = false,
        columns = {{{columns}}}
    )
    ORDER BY service_date, service_id, stop_id
    """


def convert_month(csv_path: Path, parquet_path: Path) -> int:
    """Convert one raw CSV to Parquet, overwriting any existing output. Returns the row count.

    Writes to a .tmp file and renames it at the end, so parquet_path is never half-written.

    Raises:
        FileNotFoundError: if csv_path does not exist.
        SchemaMismatchError: if the CSV header is not the expected one.
        duckdb.Error: if a value cannot be parsed as its declared type.
    """
    _check_header(csv_path)
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = parquet_path.with_name(parquet_path.name + ".tmp")
    try:
        with duckdb.connect() as con:
            con.sql(
                f"COPY ({build_select(csv_path)}) TO {_sql_string(tmp)} "
                "(FORMAT parquet, COMPRESSION zstd)"
            )
            rows = con.sql(f"SELECT count(*) FROM read_parquet({_sql_string(tmp)})").fetchall()
        tmp.replace(parquet_path)
    finally:
        tmp.unlink(missing_ok=True)  # no-op after a successful rename
    return rows[0][0]


def main() -> None:
    split = get_config().split
    parser = argparse.ArgumentParser(description="Convert raw monthly CSVs to Parquet.")
    parser.add_argument("--start", type=parse_month, default=split.first_month, help="YYYY-MM")
    parser.add_argument("--end", type=parse_month, default=split.last_month, help="YYYY-MM")
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for year, month in month_range(args.start, args.end):
        name = f"services-{year}-{month:02d}"
        csv_path = args.raw_dir / f"{name}.csv.gz"
        if not csv_path.exists():
            logger.warning("Skip %s: raw file missing (run `make download` first)", csv_path.name)
            continue
        start = time.perf_counter()
        parquet_path = args.processed_dir / f"{name}.parquet"
        rows = convert_month(csv_path, parquet_path)
        logger.info(
            "Wrote %s: %s rows, %.1f MB, %.1fs",
            parquet_path.name,
            f"{rows:,}",
            parquet_path.stat().st_size / 1e6,
            time.perf_counter() - start,
        )


if __name__ == "__main__":
    main()
