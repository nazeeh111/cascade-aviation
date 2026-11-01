# Cascade

**Trace disruption. Test a forecast. Bound the recovery claim.**

Cascade is a reproducible, SQL-first aviation research system built on actual 2024 BTS flight reports and NOAA weather. It links source snapshots to a tested DuckDB/dbt warehouse, a SQL investigation, chronological two-hour forecasts, a compact graph residual comparison, and a bounded hypothetical recovery sandbox.

[Public replay](https://cascade-aviation-replay.nazeeh1.chatgpt.site) · [SQL investigation](artifacts/investigation.html) · [Model protocol](docs/model-card.md) · [Scenario assumptions](docs/simulator.md) · [Source dictionaries and methods](docs/sources.md)

The replay is historical. BTS publishes retrospectively; final schedules proxy advance schedules, and one-hour event/weather latency is an explicit assumption. Scenario reductions are **simulated minutes per overlapping airport interval**, not causal savings or feasible airline recovery plans. No passenger, crew, maintenance or cost quantities are invented.

## Run the small real-data quickstart

Requires Python 3.12 and the free [uv](https://docs.astral.sh/uv/) package manager. No API key, account or billed service is needed.

```sh
uv sync --locked --extra test --python 3.12
uv run cascade quickstart
uv run pytest -q
```

The included quickstart contains 28,260 real selected flights from January 15–21, 2024, buffered NOAA observations, and attributed airport metadata. It builds `data/quickstart.duckdb` from the supplied Parquet, resolves time zones, executes every dbt model, and runs the warehouse contracts. This sample exercises the actual pipeline and preserves any full-run warehouse. Annual model comparisons require the full-year data; the quickstart does not substitute a tiny random-split model evaluation.

## Reproduce the full year

```sh
uv run python -m cascade.ingest --year 2024
uv run cascade all
python -m http.server 8765 --directory app
```

Open `http://localhost:8765`. Each monthly download and weather station is an atomic, checksum-verified resume boundary. Rerunning ingestion reuses verified partitions. Explicit `--refresh` preserves previous selected bytes and manifests; see `uv run python -m cascade.ingest --help`. Raw reacquirable ZIP/CSV downloads live in a task-specific temporary cache. The retained Parquet, dictionaries, source URLs, hashes and reconciliation counts live under `data/`. The full warehouse is excluded from Git; it is generated locally.

Scope: the full 2024 reporting year; reporting carriers AA, DL, UA, WN; flights touching ATL, ORD, DFW or DEN. Regional affiliates with separate reporting codes are excluded. Forecasts and scenarios cover departures from these four hubs. Weather uses the corresponding airport observation stations. See [measured scale](artifacts/warehouse-run.json) and [ingestion evidence](data/ingestion_run.json); no billion-row claim is made.

## Measured result

The final November–December holdout contains 4,604 airport intervals. The tabular model has **7.57 percentage points MAE**, versus 13.58 for seasonal and 11.25 for rolling baselines. Adding the network feature does not demonstrate an MAE gain; the compact graph residual reaches 7.52 pp, a small descriptive difference. Severe-event recall is 51.9%, and nominal 90% intervals cover only **81.5%** of outcomes.

The four-hour scenario baseline was evaluated across 61 held-out days. Its 920-minute MAE per airport interval is large against 1,699 observed mean delay minutes, limiting interpretation of modeled benefits. At budget three, forecast-aware allocation reduces simulated pressure by 274.9 minutes per airport interval versus 269.2 for recent-stress allocation. These are hypothetical, overlapping-window comparisons, never causal savings.

The ASOF weather-join benchmark preserves the exact ordered result hash and reduces median runtime from 0.146s to 0.068s (2.16×), with measured peak buffer memory of 71.4MB versus 63.0MB. This is a bounded 676-row cutoff benchmark, not a claim about every warehouse query. Complete EXPLAIN plans and run evidence are in `artifacts/`.

## What lives where

| Path | Purpose |
|---|---|
| `cascade/ingest.py` | Streaming BTS filter, NOAA QC parsing, resumable source snapshots |
| `dbt/models/staging/` | Grain, keys, signed delays, UTC, deterministic weather reports |
| `dbt/models/intermediate/` | Validated retrospective rotations, event buckets, prior schedule edges |
| `dbt/models/marts/` | Rolling windows, as-of weather, two-hour targets and cutoff features |
| `dbt/tests/` | Reconciliation, uniqueness, validity, fan-out and direct temporal audit |
| `sql/eda.sql` | Missingness, distributions, cohorts, seasonality, weather and chain associations |
| `sql/query_before.sql`, `query_after.sql` | Result-identical measured ASOF optimization |
| `cascade/forecast.py` | Seasonal/rolling/tree baselines, network ablation, graph residual, chronological evaluation |
| `cascade/simulate.py` | Bounded aggregate pressure replay, exact feasible allocation search, sensitivities |
| `app/` | Buildless synchronized network, cutoff replay, drilldown and scenario comparison |
| `artifacts/` | Real measured outputs, charts, run identifiers and provenance |

Table grains, missingness and DST policies are declared in [warehouse contracts](docs/warehouse.md). The simulator enumerates at most 81 possible allocations, so a larger solver adds no value at this four-node scale. Graph learning uses schedule-weighted neighborhood aggregation plus a temporal residual model; it does not claim a deep GNN or assume network features improve results.

## Evidence and limits

The model protocol uses January–September training, October selection/calibration blocks, November–December final holdout, and three earlier rolling-origin evaluations. Fit boundaries exclude targets whose labels would not yet be available. Departure labels assume actual departure plus one hour; final cancellation labels assume scheduled departure plus 24 hours because cancellation announcement timestamps are absent. These are declared replay assumptions, not observed live feeds.

MAE, RMSE, severe-event recall, calibration error, prediction intervals, model runtime and network ablation are saved in `artifacts/model_run.json`. The scenario baseline is tested against held-out positive departure-delay minutes; cancellation duration is unobserved and omitted. Aggregate replay fit does not validate individual-flight feasibility. Reported policy reductions depend on hypothetical resource effectiveness and are accompanied by a sensitivity grid.

Code: [MIT](LICENSE). Underlying federal observations: US public domain; attributed OpenFlights metadata and assembled database: [ODbL/DbCL terms](LICENSE-DATA.md). Government agencies and data contributors do not endorse the project.
