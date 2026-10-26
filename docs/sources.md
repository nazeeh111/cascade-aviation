# Sources, scope and field contracts

CASCADE freezes the **2024 reporting year**, four hubs (**ATL, ORD, DFW, DEN**) and four reporting carriers (**AA, DL, UA, WN**). A flight is included if its origin or destination is one of the four hubs and its reporting carrier is selected. This is a tractable hub/carrier study, not a census of the US airline network. Regional affiliates reporting under another carrier code are excluded. Flights between two selected hubs appear once in the flight table.

## BTS reported flights

Primary source: [Reporting Carrier On-Time Performance field dictionary](https://www.transtats.bts.gov/Fields.asp?gnoyr_VQ=FGJ), [BTS On-Time portal](https://www.transtats.bts.gov/ontime/).

Current verified bulk download pattern:

```text
https://www.transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_1987_present_2024_1.zip
```

The month is an unpadded integer from 1 through 12. The January endpoint returned a real ZIP (27,573,265 bytes), containing one CSV and its source readme. This route requires no API key. These are source reports retrieved for retrospective research, not messages from an operational flight feed.

| Source field | Interpretation and handling |
|---|---|
| FlightDate, Reporting_Airline, Flight_Number_Reporting_Airline, Origin, Dest, CRSDepTime | Candidate scheduled-flight key; retain source IDs and let warehouse tests check collisions. A row is a reported scheduled flight, not a passenger or aircraft movement count. |
| Reporting_Airline | Reporting certificate carrier. Do not silently expand to marketing/codeshare carrier. |
| OriginAirportID, DestAirportID | BTS airport IDs retained alongside IATA codes; airport codes can be reused across history. |
| CRSDepTime, DepTime, CRSArrTime, ArrTime | Local HHMM integers, including source 2400 convention. UTC reconstruction is downstream, using IANA zones and elapsed times. Do not cast HHMM to decimal hours. |
| DepDelay, ArrDelay | Signed minutes. Negative early departures and arrivals are preserved. A missing value remains null. |
| DepDelayMinutes, ArrDelayMinutes | Clipped at zero in the source. Intentionally not substituted for the signed delay fields. |
| CRSElapsedTime, ActualElapsedTime | Minutes between departure and arrival. ActualElapsedTime is null for diverted flights under the source dictionary. |
| Cancelled, CancellationCode, Diverted | Explicit status flags and cancellation reason; downstream outcomes need appropriate denominators. Cancellation time is not reported. |
| CarrierDelay, WeatherDelay, NASDelay, SecurityDelay, LateAircraftDelay | Retrospective attributed delay minutes. Retained for EDA only; forbidden as forecasting features. These do not reveal passenger/crew connections. |
| Tail_Number | Reported actual tail. Missingness is preserved. Useful for retrospective continuity checks; future actual assignments cannot be treated as cutoff-known forecasts. |

`cascade/ingest.py` projects these fields with PyArrow, filters only the documented cohort, and writes `data/flights/year=2024/month=MM/part.parquet`. It neither fills absent delays nor deduplicates or invents tail values. The downstream warehouse owns deduplication, timestamp disambiguation, validity filters, and audit counts.

Every monthly durable manifest records the source URL, ZIP SHA-256, CSV member, compressed/uncompressed bytes, total source rows, selected rows, signed aggregate sums, non-null counts, output SHA-256, schema version and measured elapsed time. Monthly partition completion is atomic; a rerun verifies the output hash before skipping it. A failed download leaves no completed snapshot. Raw ZIPs are reacquirable and stored outside synced Documents in a project-specific `/tmp/cascade-source-cache-<path hash>` directory (the initial verification run used `/tmp/cascade-source-cache`).

The source may publish corrections. `--refresh` explicitly downloads a replacement and retains the prior manifest under `data/manifests/history/` and checksum-verified prior selected Parquet bytes under `data/history/`; it does not claim that a new source revision is identical. Archive original source bytes separately if durable point-in-time restoration of a superseded public file is required.

## NOAA airport observations

Primary source: [NCEI Integrated Surface Database](https://www.ncei.noaa.gov/products/land-based-station/integrated-surface-database), [ISD format specification, January 12, 2018](https://www.ncei.noaa.gov/pub/data/noaa/isd-format-document.pdf), [station history](https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv).

Current verified public object pattern:

```text
https://noaa-global-hourly-pds.s3.amazonaws.com/2024/72219013874.csv
```

The legacy ISD-Lite path redirected to an HTML bucket explorer during this build. Ingestion therefore uses the real Global Hourly CSV objects and explicitly rejects HTML downloads. This matters during [NCEI's documented cloud migration](https://www.ncei.noaa.gov/products/land-based-station/integrated-surface-database).

Station history was checked by full USAF+WBAN identifier, airport ICAO, name and position:

| Airport | USAF+WBAN station | History name | Position |
|---|---|---|---|
| ATL | 72219013874 | HARTSFIELD-JACKSON ATLANTA INTL AP | 33.630, -84.442 |
| ORD | 72530094846 | CHICAGO O'HARE INTERNATIONAL AIRPORT | 41.960, -87.932 |
| DFW | 72259003927 | DALLAS/FT WORTH INTERNATIONAL AP | 32.897, -97.022 |
| DEN | 72565003017 | DENVER INTERNATIONAL AIRPORT | 39.847, -104.656 |

`DATE` is an observation timestamp in UTC. Its parsed `observed_at` column is stored as a timezone-naive timestamp with the **explicit UTC contract**. Global Hourly includes sub-hourly and multiple report types; ingestion retains the source observation rows rather than assuming exactly one row per hour. Downstream staging must establish station/timestamp uniqueness deterministically before any as-of join.

| CSV composite | Parsed column | Units | Missing sentinel |
|---|---|---|---|
| TMP | temperature | degrees C, source integer / 10 | +9999 |
| WND | wind_speed | metres/second, speed token / 10 | 9999 |
| VIS | visibility | metres | 999999 |
| CIG | ceiling | metres | 99999 |
| SLP | pressure | hectopascals, source integer / 10 | 99999 |

Quality tokens `0` and `4` pass gross-limit checks; `1` and `5` pass all specified checks, with `4`/`5` denoting NCEI source variants. This build accepts those four flags and excludes suspect, erroneous, missing and unclassified flags. It also excludes some agency-accepted special flags, a conservative missingness choice. Raw composite strings remain in Parquet so this policy is auditable and revisable. A value passing gross limits is not represented as having passed every check.

Publication receipt times are absent. Forecasting must declare an assumed observation publication lag and use **available_at <= cutoff**, never select realized future weather. This is a retrospective backtest under assumed availability, not evidence of a deployable feed latency. NOAA observation values may have been retrospectively quality controlled or corrected.

Each station/year manifest records full source hash, URL, source and selected row counts, source station name and position, observation bounds, and output hash. Station weather Parquet is partitioned by reporting year and station.

## Airport metadata and licensing

[OpenFlights airport database](https://openflights.org/data.php), [CSV snapshot](https://raw.githubusercontent.com/jpatokal/openflights/master/data/airports.dat), supplies names, coordinates and IANA timezone identifiers for endpoints. The static upstream snapshot is not asserted to be a complete current airport registry. Coordinates and names can be historical; the reporting cohort is determined by BTS, not by the metadata list. Use the IANA zone, never the database's fixed UTC offset or its old DST approximation.

OpenFlights distributes its database under [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/) and individual contents under [DbCL 1.0](https://opendatacommons.org/licenses/dbcl/1-0/). Attribution and the free database license must accompany redistributed metadata and derived databases. Keep code licensing distinct from data licensing. No airport metadata is represented as newly collected CASCADE data. The input URL/hash and attribution are in `data/manifests/airports.json`.

BTS and NOAA are US federal public data; no ownership is asserted over those source facts. Cite Bureau of Transportation Statistics and NOAA/NCEI, include retrieval/snapshot hashes, and do not imply agency endorsement. [US open licensing guidance](https://resources.data.gov/open-licenses/) describes the public-data reuse basis. Data may have reporting errors and are unsuitable for navigation or real airline dispatch.

## Small real-data quickstart

`data/quickstart/` contains actual selected January 15–21 flights, buffered January 14–22 observations, airport metadata, and a per-file SHA-256 manifest. This slice includes winter disruption and ordinary operations; it is a warehouse/EDA smoke-test dataset, not a valid substitute for full-year rolling-origin forecasting evaluation. The full-year path reacquires the agency files and rebuilds the cohort.

No passenger counts, costs, crew links, maintenance restrictions, causal savings, or synthetic source observations are included or inferred by ingestion.

## Verified build scale

The completed 2024 run read **7,079,061 national source flight rows** and retained **1,619,420 cohort flights**, plus **54,368 NOAA observations**. The selected flight key had zero duplicates; all selected endpoints had airport metadata; signed source sums and selected counts matched independent DuckDB re-reads in every month. The raw selected data preserve **881,126 negative departure delays** and **24,539 null arrival delays**. Weather has 93 duplicate station/timestamp excess rows before deterministic warehouse staging.

The source stage consumed 388,161,647 downloaded input bytes and produced 23,150,112 bytes of selected Parquet. Its measured 478.291-second wall time is a **mixed-cache stage**, with January already downloaded during source verification and weather/metadata prepared in parallel. It is not advertised as a cold end-to-end rebuild. A hash-verified resume of all 17 source partitions completed in 0.285 seconds with zero downloads. See `data/ingestion_run.json`, `data/ingestion_audit.json`, and individual manifests for exact inputs and measurement context.

Network-free disposable refresh fixtures verified that flights, weather and airport metadata all preserve byte-identical prior selected snapshots, recover those bytes into separate destinations, and reject a locally modified partition before refresh. These fixtures are safeguards tests, not scientific source observations.
