# Warehouse contracts

The warehouse is an explicit dbt dependency graph, bootstrapped by `cascade/warehouse.py`. Analytical transformations live in reviewed SQL; Python handles downloads, parsers, timezone resolution, model fitting and exports.

| Relation | Grain and key | Meaning |
|---|---|---|
| raw_flights | one retained source row; no assumed unique key | selected final monthly federal records |
| airports | one IATA code, key code | attributed OpenFlights metadata |
| dim_carriers / carriers | one reporting carrier code | four scoped carrier labels and a tested flight relationship |
| departure_times | local flight date + HHMM + IANA timezone | deterministic UTC conversion and status |
| stg_flights / flights | one scheduled reporting flight, key flight_id | MD5 natural key date/carrier/number/origin/destination/scheduled departure; exact duplicates collapse, all conflicting versions are excluded |
| raw_weather | one station source report | accepted QC measurement fields, raw field strings retained |
| stg_weather / weather | airport + observed_at | deterministic report precedence: routine METAR, special METAR, SYNOP, then completeness and raw content |
| int_rotations / rotations | one following flight_id | possible same-carrier/same-tail predecessor; validated flag distinguishes defensible continuity |
| int_airport_hours | airport + UTC cutoff | scheduled outcome bucket and separately reported event bucket |
| int_network_edges | cutoff + source + target | preceding 28 reporting days of scheduled hub-to-hub weights |
| mart_airport_hour_features | airport + UTC cutoff | 2h labels and cutoff-available features, never mixed in the model whitelist |
| predictions | airport + cutoff + model | held-out prediction, later outcome, interval and run ID |
| simulation_replay | airport + cutoff | baseline simulated and actual delay-pressure comparison |
| scenarios | airport + cutoff + policy + budget | bounded simulated resource experiment |

## Time and missingness

BTS clocks are local HHMM. 2400 advances the date. Invalid clock fields, missing timezone metadata, and nonexistent spring-forward local times have no UTC timestamp. Autumn overlaps use the earliest UTC candidate (fold zero) and are explicitly flagged. Scheduled arrival uses scheduled elapsed minutes to infer date rollover and is cross-checked against destination local HHMM. Actual departure is scheduled UTC plus the signed reported departure delay; actual arrival requires observed departure and actual elapsed duration, and is absent for cancellations/diversions. Negative departure and arrival delays are retained. Missing arrival delay is never imputed as zero.

Historical final schedules proxy what would have been scheduled at the cutoff. Actual events and weather have one hour of assumed reporting latency. Final cancellation outcomes are assumed labelable 24 hours after scheduled departure; this is an outcome-availability proxy, not an observed cancellation notification feed. A target has `target_available_at`, the latest of its constituent label availability timestamps. All training/calibration boundaries filter by label availability as well as the two-hour target horizon. Weather age is retained; EDA weather associations require age at most three hours. Raw weather duplicates are not joined directly.

## Aircraft links and corrections

A validated retrospective hub-turn tail link requires a following departure from ATL, ORD, DFW or DEN, plus same reporting carrier and nonempty tail, adjacent selected records, matching destination/origin, observed nondiverted arrival, arrival before next departure, and a scheduled turn between 20 minutes and 12 hours. Every selected-carrier flight touching these hubs is retained; nonhub turns remain unvalidated because omitted out-and-back flights could hide continuity breaks. Missing tails, corrections and cross-carrier operations still limit occupancy inference; such links are neither assumed crew connections nor future operational assignments. These records never enter deployable forecast features or resource allocation.

The monthly BTS final extract may contain corrections that are not historically timestamped. Ingestion uses checksum-verified atomic partitions and explicit refresh; prior selected bytes/manifests are preserved. Exact duplicates collapse. Conflicting natural keys are quarantined from analytics and counted in reconciliation. The release reports the snapshot actually used, not an invented historical revision stream.

## Verification

`dbt build` runs uniqueness, required keys, relationships, accepted carriers, signed aggregate reconciliation, join fan-out, time/flag validity, rotation validity, source missingness and direct event/weather availability recomputations. The ingestion manifests independently reconcile national rows, selected rows, signed delay sums, cancellations and diversions. `sql/query_before.sql` and `query_after.sql` compare an inequality/ranking weather join to ASOF with identical ordered result hashes, measured runtimes, memory, and EXPLAIN ANALYZE artifacts.
