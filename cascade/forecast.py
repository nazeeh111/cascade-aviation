"""Chronological airport disruption forecasting. Feature engineering lives in SQL."""
from __future__ import annotations
import hashlib
import json
import platform
import time
from datetime import datetime, timedelta
from pathlib import Path
import joblib
import numpy as np
import pyarrow as pa
from threadpoolctl import threadpool_limits
from sklearn import __version__ as sklearn_version
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

FEATURES = ["airport", "recent_departures", "recent_stress", "recent_mean_delay",
            "prior_day_rate", "prior_week_rate", "rolling_rate", "scheduled_next",
            "wind_speed", "visibility", "temperature", "weather_age_hours", "hour", "dow", "month"]
NETWORK_FEATURES = FEATURES + ["neighbor_stress"]
GRAPH_FEATURES = ["recent_stress", "prior_day_rate", "prior_week_rate", "rolling_rate", "neighbor_stress", "scheduled_next", "hour", "dow"]
HORIZON = timedelta(hours=2)
SEVERE = 0.40


def _matrix(rows, columns, names):
    return np.asarray([[({"ATL": 0, "DEN": 1, "DFW": 2, "ORD": 3}[r[columns.index(n)]] if n == "airport" else float(r[columns.index(n)])) if r[columns.index(n)] is not None else np.nan for n in names] for r in rows], dtype=float)


def chronological_mask(times, start, end, purge=True, available_at=None, require_available=True):
    """Fit/selection labels must be known at boundary; scoring uses eventual labels."""
    available_at = times if available_at is None else available_at
    return np.array([start <= t and t + (HORIZON if purge else timedelta()) < end and (not require_available or (available is not None and available < end)) for t, available in zip(times, available_at)])


def metrics(actual, pred, weights, lower=None, upper=None):
    actual, pred, weights = map(np.asarray, (actual, pred, weights))
    if len(actual) == 0:
        return {"n": 0}
    errors = pred - actual
    positive = actual >= SEVERE
    bins = np.minimum((np.clip(pred, 0, 1) * 10).astype(int), 9)
    ece = sum(np.sum(weights[bins == b]) / np.sum(weights) * abs(np.average(actual[bins == b], weights=weights[bins == b]) - np.average(pred[bins == b], weights=weights[bins == b])) for b in range(10) if np.any(bins == b))
    result = {"n": len(actual), "scheduled_denominator": int(weights.sum()), "mae": float(np.mean(abs(errors))), "rmse": float(np.sqrt(np.mean(errors ** 2))), "weighted_mae": float(np.average(abs(errors), weights=weights)), "bias": float(np.mean(errors)), "calibration_error": float(ece), "severe_event_count": int(positive.sum()), "severe_recall": float(np.mean(pred[positive] >= SEVERE)) if positive.any() else None,
              "severe_precision": float(np.mean(actual[pred >= SEVERE] >= SEVERE)) if np.any(pred >= SEVERE) else None}
    if lower is not None:
        result["interval_coverage"] = float(np.mean((actual >= lower) & (actual <= upper)))
        result["mean_interval_width"] = float(np.mean(np.asarray(upper) - np.asarray(lower)))
    return result


class Seasonal:
    def fit(self, rows, cols, target, weights):
        self.global_mean = float(np.average(target, weights=weights))
        self.lookup = {}
        ai, hi, di = (cols.index(x) for x in ("airport", "hour", "dow"))
        for i, r in enumerate(rows):
            key = (r[ai], r[hi], r[di])
            pair = self.lookup.setdefault(key, [0., 0.])
            pair[0] += target[i] * weights[i]
            pair[1] += weights[i]
        return self
    def predict(self, rows, cols):
        indices = [cols.index(x) for x in ("airport", "hour", "dow")]
        return np.asarray([self.lookup.get(tuple(r[i] for i in indices), [self.global_mean, 1.])[0] / self.lookup.get(tuple(r[i] for i in indices), [0., 1.])[1] for r in rows])


def _hgb(params):
    return HistGradientBoostingRegressor(loss="squared_error", max_iter=160, learning_rate=.06, max_leaf_nodes=params["max_leaf_nodes"], l2_regularization=params["l2_regularization"], min_samples_leaf=35, categorical_features=[0], random_state=42)


def fit_bundle(rows, cols, params):
    yi = cols.index("target_rate")
    wi = cols.index("scheduled")
    y = np.array([r[yi] for r in rows], float)
    w = np.array([r[wi] for r in rows], float)
    started = time.perf_counter()
    models = {"seasonal": Seasonal().fit(rows, cols, y, w)}
    timings = {"seasonal": time.perf_counter() - started, "rolling": 0.}
    for name, features in (("tabular", FEATURES), ("network_tabular", NETWORK_FEATURES)):
        started = time.perf_counter()
        model = _hgb(params)
        model.fit(_matrix(rows, cols, features), y, sample_weight=np.sqrt(w))
        models[name] = model
        timings[name] = time.perf_counter() - started
    started = time.perf_counter()
    # A two-stage temporal graph residual: train residuals only on a later inner
    # block, using base predictions from a model fitted before that block.
    boundary = rows[int(len(rows) * .65)][cols.index("cutoff")]
    ti = cols.index("cutoff")
    early = [r for r in rows if r[ti] + HORIZON < boundary and r[cols.index("target_available_at")] is not None and r[cols.index("target_available_at")] < boundary]
    late = [r for r in rows if r[ti] >= boundary]
    inner = _hgb(params).fit(_matrix(early, cols, FEATURES), np.array([r[yi] for r in early]), sample_weight=np.sqrt([r[wi] for r in early]))
    base_late = np.clip(inner.predict(_matrix(late, cols, FEATURES)), 0, 1)
    graph_x = np.column_stack([_matrix(late, cols, GRAPH_FEATURES), base_late])
    residual = np.asarray([r[yi] for r in late]) - base_late
    graph = make_pipeline(SimpleImputer(strategy="median", keep_empty_features=True), StandardScaler(), Ridge(alpha=100.))
    graph.fit(graph_x, residual)
    models["graph_residual"] = graph
    timings["graph_residual"] = time.perf_counter() - started + timings["tabular"]
    models["_fit_seconds"] = timings
    models["graph_training"] = {"inner_boundary": boundary.isoformat(), "early_n": len(early), "residual_n": len(late), "ridge_alpha": 100.0}
    return models


def predict_bundle(bundle, rows, cols, timings=None):
    timings = {} if timings is None else timings
    started = time.perf_counter()
    outputs = {"seasonal": bundle["seasonal"].predict(rows, cols)}
    timings["seasonal"] = time.perf_counter() - started
    started = time.perf_counter()
    rolling_idx = cols.index("rolling_rate")
    outputs["rolling"] = np.array([r[rolling_idx] if r[rolling_idx] is not None else bundle["seasonal"].global_mean for r in rows])
    timings["rolling"] = time.perf_counter() - started
    started = time.perf_counter()
    outputs["tabular"] = bundle["tabular"].predict(_matrix(rows, cols, FEATURES))
    timings["tabular"] = time.perf_counter() - started
    started = time.perf_counter()
    outputs["network_tabular"] = bundle["network_tabular"].predict(_matrix(rows, cols, NETWORK_FEATURES))
    timings["network_tabular"] = time.perf_counter() - started
    started = time.perf_counter()
    graph_x = np.column_stack([_matrix(rows, cols, GRAPH_FEATURES), np.clip(outputs["tabular"], 0, 1)])
    outputs["graph_residual"] = outputs["tabular"] + bundle["graph_residual"].predict(graph_x)
    timings["graph_residual"] = time.perf_counter() - started + timings["tabular"]
    return {name: np.clip(value, 0, 1) for name, value in outputs.items()}


@threadpool_limits.wrap(limits=4)
def run(connection, root):
    root = Path(root)
    artifacts = root / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    query = "SELECT * FROM airport_hour_features WHERE scheduled >= 3 AND target_rate IS NOT NULL ORDER BY cutoff, airport"
    cur = connection.execute(query)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    if not rows:
        raise ValueError("No airport-hour features with at least 3 scheduled departures")
    ti, yi, wi, ai = [cols.index(x) for x in ("cutoff", "target_rate", "scheduled", "airport")]
    times = [r[ti] for r in rows]
    availability = [r[cols.index("target_available_at")] for r in rows]
    digest = hashlib.sha256(repr(rows).encode()).hexdigest()
    code_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    run_id = "forecast-" + hashlib.sha256((digest + code_hash).encode()).hexdigest()[:12]
    def subset(start, end, require_available=True):
        return [r for r, keep in zip(rows, chronological_mask(times, datetime.fromisoformat(start), datetime.fromisoformat(end), available_at=availability, require_available=require_available)) if keep]
    train = subset("2024-01-01", "2024-10-01")
    tune = subset("2024-10-01", "2024-10-16")
    calibration = subset("2024-10-16", "2024-11-01")
    test = subset("2024-11-01", "2025-01-01", require_available=False)
    if min(map(len, [train, tune, calibration, test])) < 10:
        raise ValueError("Full chronological partitions unavailable; cannot silently replace with random split")
    tuning = []
    for params in ({"max_leaf_nodes": 15, "l2_regularization": 2.}, {"max_leaf_nodes": 31, "l2_regularization": 10.}):
        start = time.perf_counter()
        model = _hgb(params).fit(_matrix(train, cols, FEATURES), [r[yi] for r in train], sample_weight=np.sqrt([r[wi] for r in train]))
        predictions = np.clip(model.predict(_matrix(tune, cols, FEATURES)), 0, 1)
        score = metrics(np.array([r[yi] for r in tune]), predictions, np.array([r[wi] for r in tune]))
        tuning.append({"parameters": params, "mae": score["mae"], "seconds": time.perf_counter() - start})
    selected = min(tuning, key=lambda x: x["mae"])["parameters"]
    final_train = subset("2024-01-01", "2024-10-16")
    start = time.perf_counter()
    bundle = fit_bundle(final_train, cols, selected)
    fit_seconds = time.perf_counter() - start
    cal = predict_bundle(bundle, calibration, cols)
    start = time.perf_counter()
    prediction_timings = {}
    pred = predict_bundle(bundle, test, cols, prediction_timings)
    predict_seconds = time.perf_counter() - start
    actual = np.array([r[yi] for r in test], float)
    weights = np.array([r[wi] for r in test], float)
    cal_actual = np.array([r[yi] for r in calibration], float)
    results = []
    prediction_rows = []
    for name, values in pred.items():
        radius = float(np.quantile(abs(cal[name] - cal_actual), .9, method="higher"))
        lower, upper = np.clip(values - radius, 0, 1), np.clip(values + radius, 0, 1)
        result = {"name": name, "split": "2024-11-01 to 2024-12-31", **metrics(actual, values, weights, lower, upper), "fit_seconds_bundle": fit_seconds, "prediction_seconds_bundle": predict_seconds, "fit_seconds": bundle["_fit_seconds"][name], "prediction_seconds": prediction_timings[name], "runtime_seconds": prediction_timings[name], "interval_radius": radius}
        results.append(result)
        prediction_rows.extend((r[ai], r[ti], name, float(values[i]), float(actual[i]), int(weights[i]), float(lower[i]), float(upper[i]), "test", run_id) for i, r in enumerate(test))
    folds = []
    for start_date, end_date in [("2024-05-01", "2024-06-01"), ("2024-07-01", "2024-08-01"), ("2024-09-01", "2024-10-01")]:
        fold_train = subset("2024-01-01", start_date)
        fold_test = subset(start_date, end_date, require_available=False)
        fold_start = time.perf_counter()
        # Predeclared parameters prevent any final-holdout or later tuning influence.
        fold_bundle = fit_bundle(fold_train, cols, {"max_leaf_nodes": 15, "l2_regularization": 2.})
        fold_pred = predict_bundle(fold_bundle, fold_test, cols)
        folds.append({"train_end_exclusive": start_date, "test_end_exclusive": end_date, "train_n": len(fold_train), "test_n": len(fold_test), "runtime_seconds": time.perf_counter() - fold_start, "models": [{"name": name, **metrics(np.array([r[yi] for r in fold_test]), values, np.array([r[wi] for r in fold_test]))} for name, values in fold_pred.items()]})
    connection.execute("CREATE OR REPLACE TABLE predictions (airport VARCHAR, cutoff TIMESTAMP, model VARCHAR, prediction DOUBLE, actual DOUBLE, scheduled INTEGER, lower DOUBLE, upper DOUBLE, split VARCHAR, run_id VARCHAR)")
    table = pa.Table.from_arrays([pa.array([r[i] for r in prediction_rows]) for i in range(10)], names=["airport", "cutoff", "model", "prediction", "actual", "scheduled", "lower", "upper", "split", "run_id"])
    connection.register("forecast_rows_arrow", table)
    connection.execute("INSERT INTO predictions SELECT * FROM forecast_rows_arrow")
    connection.unregister("forecast_rows_arrow")
    connection.execute(f"COPY predictions TO '{(artifacts/'predictions.parquet').as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    joblib.dump({"models": bundle, "columns": cols, "parameters": selected, "feature_names": FEATURES, "run_id": run_id}, artifacts / "forecast.joblib")
    # Airport-day paired uncertainty respects serially overlapping 2h targets.
    grouped = {}
    for i, row in enumerate(test):
        grouped.setdefault((row[ai], row[ti].date()), []).append(i)
    daily_delta = np.array([np.mean(abs(pred["network_tabular"][ids] - actual[ids]) - abs(pred["tabular"][ids] - actual[ids])) for ids in grouped.values()])
    rng = np.random.default_rng(42)
    boots = np.mean(rng.choice(daily_delta, size=(2000, len(daily_delta)), replace=True), axis=1)
    contribution = {"comparison": "network_tabular minus tabular MAE; negative favors network", "paired_airport_days": len(daily_delta), "mean_daily_mae_difference": float(daily_delta.mean()), "bootstrap_95_interval": [float(v) for v in np.quantile(boots, [.025, .975])], "bootstrap_seed": 42, "limitations": "Airport-days remain correlated across hubs. Descriptive uncertainty, not a causal test."}
    payload = {"run_id": run_id, "input_sha256": digest, "code_sha256": code_hash, "source_manifest_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((root/"data/manifests").glob("*.json"))}, "feature_query": query, "target": "Share of scheduled departures in [cutoff, cutoff+2h) with departure delay >=15min or cancellation", "minimum_scheduled": 3, "severe_threshold": SEVERE, "target_overlap": "Hourly cutoffs have overlapping 2h targets; day-block comparisons used", "splits": {"tuning_train": ["2024-01-01", "2024-10-01"], "tuning": ["2024-10-01", "2024-10-16"], "final_train": ["2024-01-01", "2024-10-16"], "calibration": ["2024-10-16", "2024-11-01"], "test": ["2024-11-01", "2025-01-01"], "purge_hours": 2, "label_availability_filter": "Fit/selection only: target_available_at < partition end; scoring uses eventual observed labels; actual departures +1h, cancelled schedule +24h proxy"}, "tuning": tuning, "selected_parameters": selected, "models": results, "rolling_origin": folds, "network_contribution": contribution, "features": FEATURES, "network_features": NETWORK_FEATURES, "graph_features": GRAPH_FEATURES, "graph_residual_training": bundle["graph_training"], "versions": {"python": platform.python_version(), "sklearn": sklearn_version, "thread_limit": 4}, "availability_assumptions": ["Final reported BTS schedules proxy schedules known at cutoff; no historical schedule revisions are available.", "BTS actual departure events are assumed available one hour after occurrence, although BTS publishes retrospectively.", "NOAA observation timestamps plus a declared latency proxy availability; ingestion timestamps are not supplied by the archive.", "No delay-cause fields, realized future weather, future actual aircraft assignments, or arrival outcomes are model features.", "Training/tuning/calibration labels must be available before each boundary. Departure labels use actual departure+1h; cancellation availability uses an explicitly hypothetical schedule+24h proxy because BTS has no cancellation announcement timestamps. Labels still unavailable at fit/selection boundaries are excluded from those partitions. Final and rolling-origin test scores use eventual observed labels, retaining severe late outcomes."], "calibration": "Symmetric 90% split-conformal absolute residual intervals from Oct16–31; temporal shift may invalidate nominal coverage."}
    (artifacts / "metrics.json").write_text(json.dumps(payload, indent=2, allow_nan=False))
    (artifacts / "model_run.json").write_text(json.dumps(payload, indent=2, allow_nan=False))
    return payload
