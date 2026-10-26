# Data licenses and attribution

Code is MIT licensed. The data are separately attributed and licensed.

## BTS and NOAA

US Department of Transportation, Bureau of Transportation Statistics, Reporting Carrier On-Time Performance, reporting year 2024. National Oceanic and Atmospheric Administration, National Centers for Environmental Information, Integrated Surface Database / Global Hourly, reporting year 2024. US federal government works are generally public domain under US law. Preserve source attribution and provenance; the agencies do not endorse CASCADE. Underlying federal observations remain public domain, and are provided without a warranty of fitness or accuracy.

Official access and policies:
- [BTS on-time statistics](https://www.transtats.bts.gov/ontime/)
- [BTS field dictionary](https://www.transtats.bts.gov/Fields.asp?gnoyr_VQ=FGJ)
- [NOAA ISD](https://www.ncei.noaa.gov/products/land-based-station/integrated-surface-database)
- [NOAA disclaimer](https://www.noaa.gov/disclaimer)
- [17 USC 105](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title17-section105&num=0&edition=prelim)

## Airport metadata

Airport names, coordinates and time zones are derived from [OpenFlights airport database](https://openflights.org/data.php), copyright OpenFlights contributors. This metadata is available under the [Open Database License 1.0](https://opendatacommons.org/licenses/odbl/1-0/); individual contents are available under the [Database Contents License 1.0](https://opendatacommons.org/licenses/dbcl/1-0/). These terms apply to `data/airports.parquet`, the quickstart metadata copy, and derived metadata in the public app. The source URL, hash and retrieval date are recorded in `data/manifests/airports.json`.

The assembled CASCADE database and its distributed derived database extracts are offered under ODbL 1.0, preserving the OpenFlights share-alike requirement. This does not remove the public-domain status of the separately identifiable federal BTS and NOAA observations. Keep these notices when redistributing the assembled quickstart or a derived database. Documentation and explanatory code remain under MIT unless a separate source notice applies.

The quickstart contains actual observations, not synthetic examples. See `data/quickstart/manifest.json` for scope, hashes and source snapshots. Source correction snapshots must be explicitly refreshed and retain prior selected bytes and manifests.
