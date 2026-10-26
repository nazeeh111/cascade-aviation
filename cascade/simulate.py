"""A bounded schedule-network pressure sandbox, not an airline recovery model."""
from __future__ import annotations
import hashlib
import itertools
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np
import pyarrow as pa
from threadpoolctl import threadpool_limits
from scipy.optimize import nnls

AIRPORTS = ("ATL", "DEN", "DFW", "ORD")
MAX_PER_AIRPORT = 2
DEFAULT_BUDGET = 3
DEFAULT_RELIEF = .15
MODEL = "tabular"
HORIZON_HOURS = 4
TURN_BUFFER_MINUTES = 45


def feasible_allocations(budget, max_per_airport=MAX_PER_AIRPORT):
    if not isinstance(budget, int) or not 0 <= budget <= len(AIRPORTS) * max_per_airport:
        raise ValueError("Budget must be an integer within total per-airport capacity")
    return [np.asarray(v, dtype=int) for v in itertools.product(range(max_per_airport + 1), repeat=len(AIRPORTS)) if sum(v) == budget]


def pressure(exogenous, adjacency, coupling):
    exogenous, adjacency = np.asarray(exogenous, float), np.asarray(adjacency, float)
    if exogenous.shape != (len(AIRPORTS),) or adjacency.shape != (len(AIRPORTS), len(AIRPORTS)):
        raise ValueError("Expected four airport pressures and a 4x4 schedule adjacency")
    if not np.all(np.isfinite(exogenous)) or not np.all(np.isfinite(adjacency)) or np.any(exogenous < 0) or np.any(adjacency < 0):
        raise ValueError("Pressures and schedule edge weights must be finite and nonnegative")
    if not 0 <= coupling < 1 or np.any(adjacency.sum(axis=1) > 1 + 1e-9):
        raise ValueError("Substochastic schedule graph and coupling <1 required")
    # At most one scheduled transmission in this four-hour scenario.
    # Recursive equilibrium would imply impossible instantaneous multi-leg turns.
    return exogenous + coupling * adjacency.T @ exogenous


def scenario(exogenous, adjacency, coupling, allocation, relief=DEFAULT_RELIEF):
    allocation = np.asarray(allocation)
    if allocation.shape != (len(AIRPORTS),) or np.any(allocation < 0) or np.any(allocation > MAX_PER_AIRPORT) or np.any(allocation != allocation.astype(int)):
        raise ValueError("Allocation must contain 0..2 integer units per airport")
    if not 0 <= relief <= 1:
        raise ValueError("Relief must be a fraction")
    return pressure(np.asarray(exogenous) * (1 - relief) ** allocation, adjacency, coupling)


def optimizer(risk_exogenous, adjacency, coupling, budget, relief=DEFAULT_RELIEF):
    # Exact finite search: 3^4=81 possibilities before the budget constraint.
    candidates = feasible_allocations(budget)
    scores = [float(scenario(risk_exogenous, adjacency, coupling, v, relief).sum()) for v in candidates]
    return candidates[int(np.argmin(scores))]


def greedy_allocation(weights, budget):
    weights = np.nan_to_num(np.asarray(weights, float), nan=0.)
    result = np.zeros(len(AIRPORTS), dtype=int)
    for _ in range(budget):
        scores = np.where(result < MAX_PER_AIRPORT, weights / (result + 1), -np.inf)
        result[int(np.argmax(scores))] += 1
    return result


def _features(row):
    # Depend only on event-time-censored state and the final schedule proxy.
    n = row["scheduled"]
    return [n, max(0., row.get("recent_mean_delay") or 0.) * n,
            (row.get("recent_stress") or 0.) * n,
            (row.get("neighbor_stress") or 0.) * n]


# Grain: airport, UTC cutoff; next4h labels built from four disjoint hourly buckets.
RECORD_SQL = """WITH label4 AS (
    SELECT airport,cutoff,
      sum(scheduled_hour) OVER future AS scheduled,
      sum(stressed_hour) OVER future AS stressed,
      sum(unlabelled_hour) OVER future AS unknown_labels,
      sum(delay_minutes_hour) OVER future AS target_delay_minutes,
      max(label_available_at) OVER future AS target_available_at,
      count(*) OVER future AS label_hours
    FROM int_airport_hours
    WINDOW future AS (PARTITION BY airport ORDER BY cutoff ROWS BETWEEN CURRENT ROW AND 3 FOLLOWING)
) SELECT h.* EXCLUDE(scheduled,target_rate,target_delay_minutes,target_available_at),
         s.scheduled,s.stressed/nullif(s.scheduled,0) AS target_rate,
         s.target_delay_minutes,s.target_available_at
  FROM airport_hour_features h JOIN label4 s USING(airport,cutoff)
  WHERE s.scheduled>=3 AND s.unknown_labels=0 AND s.label_hours=4
  ORDER BY h.cutoff,h.airport"""


def _records(connection):
    cur = connection.execute(RECORD_SQL)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, values)) for values in cur.fetchall()]


def _matrices(connection):
    # For a cutoff, edges are scheduled departures in the next 4 hours. A row's
    # denominator includes departures to airports outside the four-node graph.
    query = """WITH departures AS (
      SELECT origin,dest,sched_dep_utc,sched_arr_utc FROM flights
      WHERE origin IN ('ATL','DEN','DFW','ORD') AND sched_dep_utc IS NOT NULL
    ), expanded AS (
      SELECT d.*,date_trunc('hour',d.sched_dep_utc)-r.k*INTERVAL 1 HOUR AS cutoff
      FROM departures d CROSS JOIN range(4) r(k)
    ) SELECT e.cutoff,e.origin,e.dest,count(*) AS n,
        count(*) FILTER(WHERE e.sched_arr_utc+INTERVAL 45 MINUTE <= e.cutoff+INTERVAL 4 HOUR) AS transmissions
      FROM expanded e JOIN (SELECT DISTINCT cutoff FROM airport_hour_features) h USING(cutoff)
      GROUP BY e.cutoff,e.origin,e.dest"""
    matrices = {}
    denom = {}
    index = {a: i for i, a in enumerate(AIRPORTS)}
    for cutoff, origin, dest, n, transmissions in connection.execute(query).fetchall():
        matrix = matrices.setdefault(cutoff, np.zeros((4, 4)))
        denom[(cutoff, origin)] = denom.get((cutoff, origin), 0) + n
        if dest in index:
            matrix[index[origin], index[dest]] += transmissions
    for cutoff, matrix in matrices.items():
        for a, i in index.items():
            matrix[i] /= max(denom.get((cutoff, a), 0), 1)
    return matrices, query


@threadpool_limits.wrap(limits=4)
def run(connection, root):
    root = Path(root)
    artifacts = root / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    code_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    source_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((root/"data/manifests").glob("*.json"))}
    model_run_ids = [r[0] for r in connection.execute("SELECT DISTINCT run_id FROM predictions ORDER BY run_id").fetchall()]
    records = _records(connection)
    train = [r for r in records if r["cutoff"] + timedelta(hours=HORIZON_HOURS) < datetime(2024, 10, 1) and r["target_available_at"] is not None and r["target_available_at"] < datetime(2024, 10, 1)]
    heldout = [r for r in records if datetime(2024, 11, 1) <= r["cutoff"] and r["cutoff"] + timedelta(hours=HORIZON_HOURS) < datetime(2025, 1, 1)]
    if not train or not heldout:
        raise ValueError("Simulation requires 2024 train and heldout data")
    matrices, edge_query = _matrices(connection)
    grouped_train = {}
    for r in train:
        grouped_train.setdefault(r["cutoff"], {})[r["airport"]] = r
    complete_train = {t: d for t, d in grouped_train.items() if set(d) == set(AIRPORTS)}
    if not complete_train:
        raise ValueError("No complete training cutoffs for four-airport replay")
    # Fit four nonnegative exogenous coefficients jointly with a small
    # predeclared propagation coupling grid. Model is shared across airports.
    candidates = []
    for coupling in (0., .10, .20, .30):
        xs, ys = [], []
        for cutoff, group in complete_train.items():
            x = np.asarray([_features(group[a]) for a in AIRPORTS], float)
            transform = np.eye(4) + coupling * matrices.get(cutoff, np.zeros((4, 4))).T
            xs.extend(transform @ x)
            ys.extend(group[a]["target_delay_minutes"] for a in AIRPORTS)
        coefficients, _ = nnls(np.asarray(xs), np.asarray(ys))
        errors = np.asarray(xs) @ coefficients - ys
        candidates.append({"coupling": coupling, "coefficients": coefficients.tolist(), "training_rmse": float(np.sqrt(np.mean(errors ** 2)))})
    calibration = min(candidates, key=lambda c: c["training_rmse"])
    coupling, coefficients = calibration["coupling"], np.asarray(calibration["coefficients"])
    predictions = {(a, t): p for a, t, p in connection.execute("SELECT airport, cutoff, prediction FROM predictions WHERE model=?", [MODEL]).fetchall()}
    groups = {}
    for row in heldout:
        groups.setdefault(row["cutoff"], {})[row["airport"]] = row
    groups = {t: d for t, d in groups.items() if set(d) == set(AIRPORTS) and all((a, t) in predictions for a in AIRPORTS)}
    scenario_rows, replay_rows, sensitivity_rows = [], [], []
    per_day = {}
    for cutoff, group in groups.items():
        adjacency = matrices.get(cutoff, np.zeros((4, 4)))
        base = np.asarray([_features(group[a]) for a in AIRPORTS]) @ coefficients
        actual = np.asarray([group[a]["target_delay_minutes"] for a in AIRPORTS], float)
        rates = np.asarray([predictions[(a, cutoff)] for a in AIRPORTS])
        demand = np.asarray([group[a]["scheduled"] for a in AIRPORTS])
        recent = np.asarray([group[a].get("recent_stress") or 0. for a in AIRPORTS])
        # A forecast gives the allocation policy a distinct risk estimate;
        # the same baseline replay engine evaluates every chosen allocation.
        risk = np.maximum(1e-6, base) * (.5 + rates)
        baseline = pressure(base, adjacency, coupling)
        replay_rows.extend((a, cutoff, float(baseline[i]), float(actual[i]), float(base[i])) for i, a in enumerate(AIRPORTS))
        per_day.setdefault(str(cutoff.date()), []).append(float(abs(baseline - actual).mean()))
        for budget in (0, 1, 2, 3, 4):
            allocations = {"no_action": np.zeros(4, dtype=int), "equal": greedy_allocation(np.ones(4), budget), "demand": greedy_allocation(demand, budget), "recent_stress": greedy_allocation(recent * demand, budget), "forecast_aware": optimizer(risk, adjacency, coupling, budget)}
            for name, allocation in allocations.items():
                result = scenario(base, adjacency, coupling, allocation)
                for i, a in enumerate(AIRPORTS):
                    scenario_rows.append((a, cutoff, name, budget, int(allocation[i]), float(result[i]), float(baseline[i] - result[i]), float(baseline[i]), DEFAULT_RELIEF, coupling))
        # Parameter sensitivity, no heldout outcome used for policy selection.
        for test_coupling in (0., .15, .30):
            for relief in (.05, .15, .30):
                allocation = optimizer(risk, adjacency, test_coupling, DEFAULT_BUDGET, relief)
                no_action = pressure(base, adjacency, test_coupling)
                outcome = scenario(base, adjacency, test_coupling, allocation, relief)
                sensitivity_rows.append((cutoff, test_coupling, relief, float(no_action.sum()), float(outcome.sum()), float((no_action - outcome).sum())))
    connection.execute("CREATE OR REPLACE TABLE simulation_replay (airport VARCHAR, cutoff TIMESTAMP, simulated_delay_minutes DOUBLE, actual_delay_minutes DOUBLE, exogenous_delay_minutes DOUBLE)")
    replay_arrow = pa.Table.from_arrays([pa.array([r[i] for r in replay_rows]) for i in range(5)], names=["airport", "cutoff", "simulated_delay_minutes", "actual_delay_minutes", "exogenous_delay_minutes"])
    connection.register("replay_rows_arrow", replay_arrow)
    connection.execute("INSERT INTO simulation_replay SELECT * FROM replay_rows_arrow")
    connection.unregister("replay_rows_arrow")
    connection.execute("CREATE OR REPLACE TABLE scenarios (airport VARCHAR, cutoff TIMESTAMP, policy VARCHAR, budget INTEGER, resources INTEGER, simulated_delay_minutes DOUBLE, improvement_minutes DOUBLE, baseline_delay_minutes DOUBLE, relief DOUBLE, coupling DOUBLE)")
    scenario_arrow = pa.Table.from_arrays([pa.array([r[i] for r in scenario_rows]) for i in range(10)], names=["airport", "cutoff", "policy", "budget", "resources", "simulated_delay_minutes", "improvement_minutes", "baseline_delay_minutes", "relief", "coupling"])
    connection.register("scenario_rows_arrow", scenario_arrow)
    connection.execute("INSERT INTO scenarios SELECT * FROM scenario_rows_arrow")
    connection.unregister("scenario_rows_arrow")
    connection.execute("CREATE OR REPLACE TABLE simulation_sensitivity (cutoff TIMESTAMP, coupling DOUBLE, relief DOUBLE, baseline_minutes DOUBLE, simulated_minutes DOUBLE, improvement_minutes DOUBLE)")
    sensitivity_arrow = pa.Table.from_arrays([pa.array([r[i] for r in sensitivity_rows]) for i in range(6)], names=["cutoff", "coupling", "relief", "baseline_minutes", "simulated_minutes", "improvement_minutes"])
    connection.register("sensitivity_rows_arrow", sensitivity_arrow)
    connection.execute("INSERT INTO simulation_sensitivity SELECT * FROM sensitivity_rows_arrow")
    connection.unregister("sensitivity_rows_arrow")
    replay = np.asarray([[r[2], r[3]] for r in replay_rows])
    summaries = connection.execute("SELECT policy,budget,avg(simulated_delay_minutes) mean_simulated_minutes_per_airport_interval, avg(improvement_minutes) mean_simulated_reduction_per_airport_interval FROM scenarios GROUP BY ALL ORDER BY budget,policy").fetchall()
    comparisons = [{"policy": r[0], "budget": r[1], "mean_simulated_minutes_per_airport_interval": r[2], "mean_simulated_reduction_per_airport_interval": r[3]} for r in summaries]
    sensitivity = [{"coupling": c, "relief": r, "mean_simulated_reduction_minutes_per_interval": m} for c,r,m in connection.execute("SELECT coupling,relief,avg(improvement_minutes) FROM simulation_sensitivity GROUP BY ALL ORDER BY ALL").fetchall()]
    digest = hashlib.sha256(repr((code_hash, source_hashes, model_run_ids, calibration, replay_rows)).encode()).hexdigest()
    payload = {"run_id": "simulation-" + digest[:12], "code_sha256": code_hash, "source_manifest_sha256": source_hashes, "forecast_run_ids": model_run_ids, "model": "nonnegative recent-state regression plus one-hop time-bounded scheduled-network pressure", "horizon_hours": HORIZON_HOURS, "forecast_signal_horizon_hours": 2, "turn_buffer_minutes": TURN_BUFFER_MINUTES, "airports": AIRPORTS, "forecast_policy_model": MODEL, "train_end_exclusive": "2024-10-01", "heldout_start": "2024-11-01", "heldout_end_exclusive": "2025-01-01", "purge_hours": HORIZON_HOURS, "label_availability_filter": "target_available_at < Oct1 for training; departures +1h, cancellation schedule+24h proxy", "calibration_candidates": candidates, "selected_calibration": calibration,
       "replay": {"n_airport_intervals": len(replay_rows), "n_network_cutoffs": len(groups), "n_days": len(per_day), "mae_delay_minutes": float(np.mean(abs(replay[:,0]-replay[:,1]))), "rmse_delay_minutes": float(np.sqrt(np.mean((replay[:,0]-replay[:,1])**2))), "bias_delay_minutes": float(np.mean(replay[:,0]-replay[:,1])), "actual_mean_delay_minutes": float(np.mean(replay[:,1])), "simulated_mean_delay_minutes": float(np.mean(replay[:,0]))},
       "day_errors": [{"date": d, "mae_delay_minutes": float(np.mean(v))} for d,v in per_day.items()], "policies": comparisons, "sensitivity": sensitivity, "budget": {"default": DEFAULT_BUDGET, "allowed": [0,1,2,3,4], "per_airport_cap": MAX_PER_AIRPORT}, "resource_assumption": "One abstract unit reduces exogenous airport departure-delay pressure by 15%; each further unit compounds. This percentage is hypothetical, not an empirical effect or a real crew/aircraft resource.", "edge_query": edge_query, "label_query": RECORD_SQL,
       "target": "Sum of positive reported departure-delay minutes for observed noncancelled departures scheduled in next 4h; cancelled flight delay is unobserved and omitted", "overlap": "4h scenario windows at hourly cutoffs overlap; policy averages are per interval and must never be added as daily savings.", "limitations": ["Final reported schedules proxy advance schedules; no historical schedule revisions.", "No passenger, crew, aircraft maintenance, gate, slot, or air-traffic constraints.", "Four hubs and four carriers are a selected subnetwork; external propagation is omitted.", "This aggregate replay validates only delay-pressure fit, not flight-level recovery feasibility.", "Only one hop can transmit pressure, and only scheduled arrival+45min within 4h is eligible. The turn buffer and coupling are hypothetical.", "The allocation policy uses a 2h forecast as a risk signal for a separate 4h scenario; it is not a 4h calibrated forecast.", "Resource and coupling sensitivity are hypothetical. Reported reductions are simulated and not causal savings.", "No future tail assignments or heldout actual outcomes enter the allocation objective.", "Performance on Nov–Dec is reported once and does not tune calibration or resource assumptions."], "runtime_seconds": time.perf_counter()-start}
    (artifacts / "simulation.json").write_text(json.dumps(payload, indent=2, allow_nan=False))
    connection.execute(f"COPY scenarios TO '{(artifacts/'scenarios.parquet').as_posix()}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    return payload
