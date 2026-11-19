# NS Delay Predictor

Predicts whether a Dutch train departure will be **5 or more minutes late**, 30 minutes before it
is planned to leave.

## Problem definition

| | Choice | Why |
|---|---|---|
| **Target** | Departure delay ≥ 5 min, **given that the train runs** | Cancellations are excluded: the archive doesn't record when a cancellation became known, and announced ones (strikes, planned works) already show in the live API. |
| **Prediction time** | 30 min before the planned departure | Enough time to act on it. Every feature must be known at that moment. |
| **Scope** | 20 stations ([`config.toml`](src/ns_delay/config.toml)), domestic passenger trains | Trips that stop abroad are excluded (22.8% late vs 4.9% domestic, delay caused outside the Dutch network). So are replacement buses (their delay isn't measured). |
| **Split** | Train 2024-01 to 2025-06, validate 2025 H2, test 2026-01 to 2026-10 | Time-based: bad days come in runs, so a random split would leak. |
| **Metrics** | PR-AUC, Brier score, calibration | 4.9% positives; the predicted probabilities are shown to users, so they must be calibrated. |

Features must be known 30 minutes before departure: `Service:Maximum delay` and the trip-level
cancellation flags are excluded because they describe the future.

The reasoning behind these choices is in [`notebooks/02_eda.ipynb`](notebooks/02_eda.ipynb).

## Setup

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12.

```bash
make install     # create .venv, install dependencies and git hooks
make test        # run the tests
make download    # download the monthly train archive (~1 GB)
make process     # convert it to Parquet in data/processed/
```

The notebooks also need
[`stations-2023-09-nl.csv`](https://opendata.rijdendetreinen.nl/public/stations/stations-2023-09-nl.csv)
in `data/raw/`. For the live NS API, copy `.env.example` to `.env` and add a key from
[apiportal.ns.nl](https://apiportal.ns.nl/).

## Data

- Train services and stations: [Rijden de Treinen](https://www.rijdendetreinen.nl/en/open-data),
  licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
- Live departures: [NS API](https://apiportal.ns.nl/).
