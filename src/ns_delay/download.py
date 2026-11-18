"""Idempotent downloader for the Rijden de Treinen open data archive.

Data: Rijden de Treinen (https://www.rijdendetreinen.nl/en/open-data), licensed CC BY 4.0.

Usage:
    uv run python -m ns_delay.download                      # whole split period from config.toml
    uv run python -m ns_delay.download --start 2024-01 --end 2024-03
"""

import argparse
import logging
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import httpx

from ns_delay.config import get_config

BASE_URL = "https://opendata.rijdendetreinen.nl/public"
DEFAULT_RAW_DIR = Path("data/raw")
TIMEOUT = httpx.Timeout(30.0)  # per network operation (connect, each read), not the total time
CHUNK_SIZE = 1024 * 1024  # 1 MiB
HEADERS = {"User-Agent": "ns-delay-downloader"}

logger = logging.getLogger(__name__)


def services_url(year: int, month: int) -> str:
    """URL of the monthly train services file, e.g. services-2024-01.csv.gz."""
    return f"{BASE_URL}/services/services-{year}-{month:02d}.csv.gz"


def month_range(start: tuple[int, int], end: tuple[int, int]) -> Iterator[tuple[int, int]]:
    """Yield (year, month) from start to end, both inclusive."""
    year, month = start
    while (year, month) <= end:
        yield year, month
        month += 1
        if month > 12:
            year, month = year + 1, 1


def download_file(url: str, dest: Path) -> Path:
    """Download url to dest, unless dest already exists. Returns dest.

    Writes to dest + '.part' first and renames only after a complete download,
    so dest either does not exist or is a complete file.

    Raises:
        httpx.HTTPStatusError: on a 4xx/5xx response (e.g. 404 if the file is not published).
        httpx.RequestError: on network problems or timeouts.
        OSError: if the downloaded size does not match the server's Content-Length.
    """
    if dest.exists():
        logger.info("Skip %s (already exists)", dest.name)
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    try:
        with httpx.stream("GET", url, headers=HEADERS, timeout=TIMEOUT) as response:
            response.raise_for_status()
            expected = response.headers.get("Content-Length")
            written = 0
            with part.open("wb") as f:
                for chunk in response.iter_bytes(CHUNK_SIZE):
                    f.write(chunk)
                    written += len(chunk)
        if expected is not None and written != int(expected):
            raise OSError(f"Incomplete download of {url}: got {written} of {expected} bytes")
        part.replace(dest)
    finally:
        part.unlink(missing_ok=True)  # no-op after a successful rename

    logger.info("Downloaded %s (%.1f MB)", dest.name, written / 1e6)
    return dest


def download_services_month(year: int, month: int, raw_dir: Path = DEFAULT_RAW_DIR) -> Path | None:
    """Download one month of train services. Returns None if it is not published yet (404)."""
    url = services_url(year, month)
    dest = raw_dir / url.rsplit("/", 1)[-1]
    try:
        return download_file(url, dest)
    except httpx.HTTPStatusError as err:
        if err.response.status_code == 404:
            logger.warning("Not published yet: %s", url)
            return None
        raise


def _parse_month(value: str) -> tuple[int, int]:
    """argparse type: '2024-01' -> (2024, 1)."""
    try:
        year, month = (int(part) for part in value.split("-"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM, got {value!r}") from None
    if not 1 <= month <= 12:
        raise argparse.ArgumentTypeError(f"month must be 1-12, got {value!r}")
    return year, month


def main() -> None:
    split = get_config().split
    first_month = (split.train_start.year, split.train_start.month)
    last_day = split.test_end - timedelta(days=1)  # test_end is exclusive
    last_month = (last_day.year, last_day.month)

    parser = argparse.ArgumentParser(description="Download Rijden de Treinen monthly services.")
    parser.add_argument("--start", type=_parse_month, default=first_month, help="YYYY-MM")
    parser.add_argument("--end", type=_parse_month, default=last_month, help="YYYY-MM")
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for year, month in month_range(args.start, args.end):
        download_services_month(year, month, args.raw_dir)


if __name__ == "__main__":
    main()
