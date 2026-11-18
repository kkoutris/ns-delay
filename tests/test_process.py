"""Tests for the raw CSV -> Parquet conversion, using a tiny handmade CSV (no downloads)."""

import gzip
from pathlib import Path

import duckdb
import pytest

from ns_delay.process import SCHEMA, SchemaMismatchError, convert_month

HEADER = ",".join(source for source, _, _ in SCHEMA)

# One trip RTD -> DT -> GV -> GVC. Columns follow HEADER. Max delay (8th column) is 7.
# RTD: origin (no arrival). GV: departure cancelled. GVC: terminus (no departure).
ROWS = [
    "1,2024-01-01,Intercity,NS,1410,false,true,7,11,RTD,Rotterdam Centraal,,,,"
    "2024-01-01T02:00:00+01:00,0,false,false,9,9",
    "1,2024-01-01,Intercity,NS,1410,false,true,7,12,DT,Delft,2024-01-01T02:13:00+01:00,3,false,"
    "2024-01-01T02:13:00+01:00,3,false,false,1,1",
    "1,2024-01-01,Intercity,NS,1410,false,true,7,13,GV,Den Haag HS,2024-01-01T02:20:00+01:00,,true,"
    "2024-01-01T02:21:00+01:00,,true,false,5,5",
    "1,2024-01-01,Intercity,NS,1410,false,true,7,14,GVC,Den Haag Centraal,"
    "2024-01-01T02:25:00+01:00,7,false,,,,false,10,10",
]


def write_csv_gz(path: Path, header: str = HEADER, rows: list[str] = ROWS) -> Path:
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write("\n".join([header, *rows]) + "\n")
    return path


@pytest.fixture
def converted(tmp_path: Path) -> Path:
    """The handmade CSV, converted. Returns the Parquet path."""
    csv_path = write_csv_gz(tmp_path / "services-2024-01.csv.gz")
    parquet_path = tmp_path / "out" / "services-2024-01.parquet"
    convert_month(csv_path, parquet_path)
    return parquet_path


def query(sql: str) -> list[tuple]:
    with duckdb.connect() as con:
        return con.sql(sql).fetchall()


# --- Schema ---------------------------------------------------------------------------------


def test_output_has_renamed_columns_in_order(converted: Path) -> None:
    columns = [row[0] for row in query(f"DESCRIBE SELECT * FROM '{converted}'")]
    assert columns == [name for _, name, _ in SCHEMA if name is not None]


def test_maximum_delay_is_not_written(converted: Path) -> None:
    columns = [row[0] for row in query(f"DESCRIBE SELECT * FROM '{converted}'")]
    assert not any("max" in column for column in columns)


def test_column_types_are_the_declared_ones(converted: Path) -> None:
    types = dict((row[0], row[1]) for row in query(f"DESCRIBE SELECT * FROM '{converted}'"))
    assert types["service_date"] == "DATE"
    assert types["departure_time"] == "TIMESTAMP WITH TIME ZONE"
    assert types["departure_delay"] == "INTEGER"
    assert types["departure_cancelled"] == "BOOLEAN"


# --- Content --------------------------------------------------------------------------------


def test_all_rows_are_kept(tmp_path: Path) -> None:
    csv_path = write_csv_gz(tmp_path / "in.csv.gz")
    assert convert_month(csv_path, tmp_path / "out.parquet") == len(ROWS)


def test_empty_fields_become_null(converted: Path) -> None:
    rows = query(f"""
        SELECT station_code, arrival_time IS NULL, departure_time IS NULL, departure_delay
        FROM '{converted}' ORDER BY stop_id
    """)
    assert rows[0] == ("RTD", True, False, 0)  # origin: no arrival
    assert rows[2] == ("GV", False, False, None)  # cancelled: no delay
    assert rows[3] == ("GVC", False, True, None)  # terminus: no departure


def test_timestamps_keep_the_exact_moment(converted: Path) -> None:
    # 02:00 at +01:00 is 01:00 UTC = 1704070800 seconds since 1970-01-01 UTC.
    rows = query(f"SELECT epoch(departure_time) FROM '{converted}' WHERE station_code = 'RTD'")
    assert rows == [(1704070800.0,)]


# --- Idempotency and failure handling -------------------------------------------------------


def test_rerun_overwrites_instead_of_appending(tmp_path: Path) -> None:
    csv_path = write_csv_gz(tmp_path / "in.csv.gz")
    parquet_path = tmp_path / "out.parquet"
    convert_month(csv_path, parquet_path)
    convert_month(csv_path, parquet_path)
    assert query(f"SELECT count(*) FROM '{parquet_path}'") == [(len(ROWS),)]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["in.csv.gz", "out.parquet"]


def test_reordered_header_is_rejected(tmp_path: Path) -> None:
    # Same column names, different order: reading by position would silently swap the values.
    columns = HEADER.split(",")
    a, b = columns.index("Stop:Arrival delay"), columns.index("Stop:Departure delay")
    columns[a], columns[b] = columns[b], columns[a]
    csv_path = write_csv_gz(tmp_path / "in.csv.gz", header=",".join(columns))
    with pytest.raises(SchemaMismatchError, match="expected columns"):
        convert_month(csv_path, tmp_path / "out.parquet")
    assert not (tmp_path / "out.parquet").exists()


def test_bad_value_fails_and_leaves_no_files(tmp_path: Path) -> None:
    bad_rows = [ROWS[0].replace(",0,false,false,9,9", ",abc,false,false,9,9")]  # delay = "abc"
    csv_path = write_csv_gz(tmp_path / "in.csv.gz", rows=bad_rows)
    with pytest.raises(duckdb.Error):
        convert_month(csv_path, tmp_path / "out.parquet")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["in.csv.gz"]  # no output, no .tmp


def test_path_with_quote_is_handled(tmp_path: Path) -> None:
    folder = tmp_path / "it's here"
    folder.mkdir()
    csv_path = write_csv_gz(folder / "in.csv.gz")
    assert convert_month(csv_path, folder / "out.parquet") == len(ROWS)
