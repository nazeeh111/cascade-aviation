"""Bootstrap immutable Parquet sources, then execute the reviewed dbt SQL DAG."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

import duckdb

HUBS = ("ATL", "ORD", "DFW", "DEN")


def local_departure(day: dt.date, hhmm: int | None, zone: str | None):
    """Resolve local BTS HHMM; gaps fail closed, ambiguous times use fold 0."""
    if hhmm is None or not zone:
        return None, "missing"
    hhmm = int(hhmm)
    if hhmm == 2400:
        day += dt.timedelta(days=1)
        hhmm = 0
    if not (0 <= hhmm <= 2359 and hhmm % 100 < 60):
        return None, "invalid_hhmm"
    local = dt.datetime.combine(day, dt.time(hhmm // 100, hhmm % 100))
    tz = ZoneInfo(zone)
    candidates = []
    for fold in (0, 1):
        utc = local.replace(tzinfo=tz, fold=fold).astimezone(dt.timezone.utc)
        if utc.astimezone(tz).replace(tzinfo=None) == local:
            candidates.append(utc.replace(tzinfo=None))
    if not candidates:
        return None, "dst_gap"
    distinct = sorted(set(candidates))
    return distinct[0], "dst_ambiguous_fold0" if len(distinct) > 1 else "valid"


def connect(root: Path, read_only=False, quickstart=False):
    filename="quickstart.duckdb" if quickstart else "warehouse.duckdb"
    c = duckdb.connect(str(root / "data" / filename), read_only=read_only)
    c.execute("SET TimeZone='UTC'")
    c.execute("SET threads=4")
    c.execute("SET memory_limit='3GB'")
    return c


def build(root: Path, quickstart=False):
    start = time.perf_counter()
    c = connect(root, quickstart=quickstart)
    data = root / "data"
    database=data / ("quickstart.duckdb" if quickstart else "warehouse.duckdb")
    flights = str(data / ("quickstart/flights.parquet" if quickstart else "flights/**/*.parquet"))
    weather = str(data / ("quickstart/weather.parquet" if quickstart else "weather/**/*.parquet"))
    c.execute("CREATE OR REPLACE TABLE raw_flights AS SELECT * FROM read_parquet(?, hive_partitioning=false)", [flights])
    c.execute("CREATE OR REPLACE TABLE raw_weather AS SELECT * FROM read_parquet(?, hive_partitioning=false)", [weather])
    airport_file=data / ("quickstart/airports.parquet" if quickstart else "airports.parquet")
    c.execute("CREATE OR REPLACE TABLE airports AS SELECT * FROM read_parquet(?)", [str(airport_file)])
    c.execute("CREATE OR REPLACE TABLE hubs AS SELECT * FROM airports WHERE code IN ('ATL','ORD','DFW','DEN')")
    # Resolve only distinct date/time/zone combinations in Python; analytical work is SQL.
    rows = c.execute("""SELECT DISTINCT f.flight_date, f.crs_dep_time, a.timezone
                        FROM raw_flights f LEFT JOIN airports a ON f.origin=a.code""").fetchall()
    import pyarrow as pa
    records = []
    for day, clock, zone in rows:
        stamp, status = local_departure(day, clock, zone)
        records.append({"flight_date": day, "crs_dep_time": clock, "timezone": zone,
                        "sched_dep_utc": stamp, "time_status": status})
    table = pa.Table.from_pylist(records, schema=pa.schema([
        ("flight_date", pa.date32()), ("crs_dep_time", pa.int32()), ("timezone", pa.string()),
        ("sched_dep_utc", pa.timestamp("us")), ("time_status", pa.string())]))
    c.register("times_arrow", table)
    c.execute("CREATE OR REPLACE TABLE departure_times AS SELECT * FROM times_arrow")
    c.close()
    env = dict(os.environ, CASCADE_DATABASE=str(database.resolve()),DBT_SEND_ANONYMOUS_USAGE_STATS="false",DO_NOT_TRACK="1")
    dbt = Path(sys.executable).parent / "dbt"
    result = subprocess.run([str(dbt), "build", "--project-dir", str(root / "dbt"),
                             "--profiles-dir", str(root / "dbt")], env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (root / "artifacts").mkdir(exist_ok=True)
    (root / ("artifacts/dbt-quickstart.log" if quickstart else "artifacts/dbt-build.log")).write_text(result.stdout)
    print(result.stdout)
    if result.returncode:
        raise RuntimeError("dbt build failed; see artifacts/dbt-build.log")
    c = connect(root, quickstart=quickstart)
    # Stable public names for Python consumers; transformations remain visible in dbt.
    for name, model in [("flights", "stg_flights"), ("weather", "stg_weather"),("carriers","dim_carriers"),
                        ("rotations", "int_rotations"), ("airport_hour_features", "mart_airport_hour_features")]:
        c.execute(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM {model}")
    stats = {"seconds": time.perf_counter()-start, "mode": "quickstart" if quickstart else "full",
             "raw_flights": c.execute("SELECT count(*) FROM raw_flights").fetchone()[0],
             "flights": c.execute("SELECT count(*) FROM flights").fetchone()[0],
             "weather": c.execute("SELECT count(*) FROM weather").fetchone()[0],
             "features": c.execute("SELECT count(*) FROM airport_hour_features").fetchone()[0],
             "database_bytes": database.stat().st_size}
    (root / ("artifacts/quickstart-run.json" if quickstart else "artifacts/warehouse-run.json")).write_text(json.dumps(stats, indent=2))
    c.close()
    return stats
