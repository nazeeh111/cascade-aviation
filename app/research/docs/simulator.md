# Bounded recovery scenario engine

The engine compares hypothetical allocations of a small, abstract recovery-resource budget. Its output is simulated departure-delay pressure in minutes per airport and four-hour scenario interval. It is a research sandbox for comparing bounded policies; it is not a dispatch or airline recovery recommendation.

## State, network and replay

For each UTC cutoff, the source is the observed 2024 schedule, using all selected-carrier departures from the four hubs. Scheduled hub-to-hub flights form a directed matrix. A connection can transmit pressure only when its scheduled arrival plus a hypothetical 45-minute turn buffer is within the four-hour scenario horizon. Each row is divided by all departures from its origin, including flights to airports outside the four-node graph, so row sums never exceed one. This avoids transmitting pressure along flights that cannot reach a downstream hub within the scenario horizon. These edges describe scheduled connectivity available under the final-schedule proxy. They do not use future actual aircraft assignments or infer crew/passenger connections.

A shared nonnegative regression estimates exogenous pressure, meaning initial airport pressure before modeled network effects, from the upcoming scheduled workload, recently reported stress, recently reported mean delay and earlier-neighbor stress. Its coefficients and a predeclared coupling grid (0, 0.10, 0.20, 0.30) are calibrated using data ending strictly before October 1. Training rows must also have labels available before October 1: departure labels use actual departure plus one hour, with scheduled departure plus 24 hours as an explicit cancellation-availability proxy where needed. The full four-hour scenario window must also finish before the boundary. A window purge alone does not admit a late label. The coupling is an aggregate assumption, not an estimate of aircraft propagation or causal passenger connectivity.

If b is the four-airport exogenous pressure vector and A is the row-normalized scheduled connectivity matrix, pressure is x = b + coupling × Aᵀb. Only one scheduled hop can transmit pressure. The matrix is substochastic and coupling is below one, so total transmitted pressure is bounded by coupling times exogenous pressure. A recursive equilibrium would imply instantaneous multi-leg turns, so it is deliberately excluded. A zero coupling is permitted and may be selected if network propagation does not improve training replay.

The engine is replayed once against November–December reported positive departure-delay minutes for departures scheduled in the next four hours, using only inputs available at each cutoff under the stated latency assumption. Replay uses simultaneous four-hub cutoffs with at least three scheduled departures per hub. Sparse overnight cutoffs are omitted, so the reported fit does not cover all hours. The replay report includes interval count, day count, MAE, RMSE, bias, observed mean, simulated mean and per-day errors. The replay target omits cancellations because their departure-delay duration is unobserved. It therefore measures completed-departure pressure, not total disruption or passenger impact. Aggregate replay fit does not validate individual-flight feasibility.

## Policy comparison

The total budget is 0–4 integer units; no airport may receive more than two. A unit is assumed to reduce an airport's exogenous delay pressure by 15%, with compounding for a second unit. This is a hypothetical resource effect, not a measured recovery intervention. No passenger count, dollar cost, crew availability, maintenance, gates, slots or air-traffic restrictions are fabricated.

The engine compares no action, equal allocation, demand-weighted allocation, recent-stress allocation and forecast-aware allocation. The forecast policy uses a predeclared two-hour tabular forecast as a risk signal for a separate four-hour scenario, not a final-holdout-selected winner or a calibrated four-hour forecast. It adjusts baseline risk by (0.5 + predicted disruption share) and exactly enumerates every feasible allocation (at most 81 before applying the budget). Every policy is then evaluated in the same baseline engine. The optimizer never uses held-out realized delay or future tails to select resources.

Policy averages are reported per airport interval. Four-hour scenario windows at hourly cutoffs overlap. **Do not add overlapping simulated reductions as daily or annual savings.** All improvements are simulated differences from the same baseline. They are not causal savings, empirical resource productivity, feasible airline recovery schedules or evidence of operational readiness.

## Sensitivity and reproduction

A predeclared sensitivity grid varies coupling across 0, 0.15 and 0.30 and per-unit relief across 5%, 15% and 30%, at budget three. It recalculates the forecast-aware allocation for every parameter combination without tuning on outcomes. Run `cascade.simulate.run(connection, root)` after forecasts; it writes `artifacts/simulation.json`, `scenarios.parquet`, and warehouse tables `simulation_replay`, `scenarios` and `simulation_sensitivity`. Run IDs, calibration alternatives and the schedule-edge SQL are retained.

The engine intentionally excludes retrospective tail rotations from the policy. Validated aircraft rotations belong to a separate retrospective analysis. Missing tail, cancelled, diverted, impossible-turn or outside-scope rotations cannot silently establish a deployable connection. Larger operational claims would require archived schedules and actual live availability records plus passenger, crew and maintenance constraints.

## Query verification

The four-hour target uses four disjoint hourly SQL label buckets. Scheduled edges expand each departure into exactly four eligible hourly cutoffs, avoiding an all-cutoffs range join. On real held-out data for November 15, the replacement label query returned all 86 eligible airport intervals exactly equal to the direct flight-range query, and all 24 network-cutoff matrices were exactly equal. The bounded label comparison measured 15.90 seconds for the direct range join and 0.688 seconds for the hourly-window query in this run. The optimized annual schedule matrices took 34.5 seconds. The original full annual range query was interrupted after more than two minutes; no completed full-baseline runtime or full-year equality claim is inferred from that interruption. See [`artifacts/simulator-query-check.json`](../artifacts/simulator-query-check.json).

## Verified replay results

Run `simulation-e313548d03ae` replays 4,092 airport intervals at 1,023 simultaneous four-hub cutoffs across 61 held-out days. The four-hour delay-pressure replay has MAE 920.0 minutes, RMSE 1,775.3 minutes and signed bias +286.4 minutes per airport interval. Mean observed pressure is 1,698.8 minutes and mean simulated pressure is 1,985.2 minutes. These are overlapping aggregate delay-minute totals, not individual flight delays.

Training selected coupling 0.30 from the predeclared grid. Replay error quantifies an important limit: the engine is an aggregate comparative sandbox, not a calibrated flight-level recovery model. No real intervention effects have been validated.

At the default three-unit budget:

| Policy | Mean simulated minutes per airport interval | Mean simulated reduction from no action |
|---|---:|---:|
| demand | 1,736.8 | 248.5 |
| equal | 1,738.0 | 247.2 |
| forecast_aware | 1,710.4 | 274.9 |
| no_action | 1,985.2 | 0.0 |
| recent_stress | 1,716.1 | 269.2 |

Every reduction in this table is simulated under the stated 15% resource assumption. These overlapping interval averages must not be summed into daily or annual savings. The full nine-cell coupling/relief sensitivity grid, day-level replay errors, calibration alternatives, generating SQL, source hashes and forecast run references are in [`artifacts/simulation.json`](../artifacts/simulation.json).
