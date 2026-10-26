"""Resumable, checksummed public BTS and NOAA ingestion. No credentials required.

Run from repository root: python -m cascade.ingest --year 2024
Source-level monthly partitions are the resume boundary. Changed snapshots are never
silently substituted: --refresh is required, and manifests retain prior versions.
"""
from __future__ import annotations
import argparse
import concurrent.futures as futures
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import time
import urllib.request
import zipfile

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
HUBS = ('ATL', 'ORD', 'DFW', 'DEN')
CARRIERS = ('AA', 'DL', 'UA', 'WN')
STATIONS = {'ATL':'72219013874','ORD':'72530094846','DFW':'72259003927','DEN':'72565003017'}
BTS_URL = 'https://www.transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_1987_present_{year}_{month}.zip'
NOAA_URL = 'https://noaa-global-hourly-pds.s3.amazonaws.com/{year}/{station}.csv'
AIRPORT_URL = 'https://raw.githubusercontent.com/jpatokal/openflights/master/data/airports.dat'
# Raw field mapping is explicit to preserve the source dictionary contract.
FIELDS = {
 'FlightDate':'flight_date','Reporting_Airline':'reporting_airline','Tail_Number':'tail_number',
 'Flight_Number_Reporting_Airline':'flight_number_reporting_airline','Origin':'origin','Dest':'dest',
 'OriginAirportID':'origin_airport_id','DestAirportID':'dest_airport_id',
 'CRSDepTime':'crs_dep_time','DepTime':'dep_time','DepDelay':'dep_delay',
 'CRSArrTime':'crs_arr_time','ArrTime':'arr_time','ArrDelay':'arr_delay',
 'CRSElapsedTime':'crs_elapsed_time','ActualElapsedTime':'actual_elapsed_time',
 'Cancelled':'cancelled','CancellationCode':'cancellation_code','Diverted':'diverted','Distance':'distance',
 'CarrierDelay':'carrier_delay','WeatherDelay':'weather_delay','NASDelay':'nas_delay',
 'SecurityDelay':'security_delay','LateAircraftDelay':'late_aircraft_delay',
}
NUMERIC = {'dep_delay','arr_delay','crs_elapsed_time','actual_elapsed_time','cancelled','diverted','distance',
           'carrier_delay','weather_delay','nas_delay','security_delay','late_aircraft_delay'}
TIMES = {'crs_dep_time','dep_time','crs_arr_time','arr_time'}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(4*1024*1024), b''): h.update(block)
    return h.hexdigest()


def atomic_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp = path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(obj,indent=2,sort_keys=True)+'\n')
    os.replace(tmp,path)


def download(url: str, destination: Path, refresh: bool=False) -> dict:
    """Use disposable cache; output hashes and response metadata in durable manifests."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not refresh:
        return {'url':url,'sha256':sha256(destination),'bytes':destination.stat().st_size,
                'cache_reused':True,'retrieved_at':datetime.fromtimestamp(destination.stat().st_mtime,timezone.utc).isoformat()}
    for attempt in range(4):
        try:
            request=urllib.request.Request(url,headers={'User-Agent':'CASCADE-reproducible-public-data/1.0'})
            with urllib.request.urlopen(request,timeout=120) as response:
                content_type=response.headers.get('Content-Type','')
                if 'text/html' in content_type: raise ValueError(f'Expected source bytes, received HTML: {response.url}')
                tmp=destination.with_suffix(destination.suffix+'.part')
                with tmp.open('wb') as f: shutil.copyfileobj(response,f,4*1024*1024)
                metadata={'url':url,'resolved_url':response.url,'content_type':content_type,
                          'etag':response.headers.get('ETag'),'last_modified':response.headers.get('Last-Modified')}
            os.replace(tmp,destination)
            return {**metadata,'sha256':sha256(destination),'bytes':destination.stat().st_size,
                    'retrieved_at':datetime.now(timezone.utc).isoformat(),'cache_reused':False}
        except Exception:
            if attempt==3: raise
            time.sleep(2**attempt)
    raise AssertionError('unreachable')


def reusable(manifest: Path, part: Path, refresh: bool) -> dict | None:
    if manifest.exists() and part.exists() and not refresh:
        record=json.loads(manifest.read_text())
        if sha256(part)==record.get('parquet_sha256'):
            print(f'RESUME {part.relative_to(ROOT)}',flush=True)
            return record
    return None


def preserve_previous(manifest: Path, part: Path, refresh: bool) -> None:
    """Keep the actual prior selected bytes before an explicitly refreshed snapshot."""
    if not refresh or not manifest.exists() or not part.exists(): return
    prior=json.loads(manifest.read_text())
    digest=sha256(part)
    if digest!=prior['parquet_sha256']:
        raise ValueError(f'Refusing refresh: existing partition differs from manifest: {part}')
    history=DATA/'history'; history.mkdir(parents=True,exist_ok=True)
    saved=history/f'{manifest.stem}-{digest[:12]}.parquet'
    if not saved.exists(): shutil.copyfile(part,saved)
    if sha256(saved)!=digest: raise ValueError('Previous snapshot preservation failed')
    atomic_json(history/f'{manifest.stem}-{digest[:12]}.json',prior)


def ingest_month(year: int, month: int, cache: Path, refresh: bool=False) -> dict:
    part=DATA/f'flights/year={year}/month={month:02d}/part.parquet'
    manifest=DATA/f'manifests/bts-{year}-{month:02d}.json'
    old=reusable(manifest,part,refresh)
    if old: return old
    preserve_previous(manifest,part,refresh)
    started=time.perf_counter()
    source=cache/f'bts-{year}-{month:02d}.zip'
    record=download(BTS_URL.format(year=year,month=month),source,refresh)
    snapshot='bts-'+str(year)+'-'+f'{month:02d}'+'-'+record['sha256'][:12]
    part.parent.mkdir(parents=True,exist_ok=True)
    tmp=part.with_suffix('.parquet.tmp')
    sums={k:0.0 for k in ('dep_delay','arr_delay','cancelled','diverted','distance')}
    nonnull={k:0 for k in sums}
    source_rows=selected_rows=0
    writer=None
    try:
        with zipfile.ZipFile(source) as z:
            candidates=[n for n in z.namelist() if n.lower().endswith('.csv')]
            if len(candidates)!=1: raise ValueError(f'Expected one CSV, found {candidates}')
            record['member']=candidates[0]
            record['uncompressed_bytes']=z.getinfo(candidates[0]).file_size
            with z.open(candidates[0]) as stream:
                reader=pacsv.open_csv(stream,read_options=pacsv.ReadOptions(block_size=16*1024*1024),
                  convert_options=pacsv.ConvertOptions(include_columns=list(FIELDS),
                     column_types={k:pa.string() for k in FIELDS},strings_can_be_null=True))
                for batch in reader:
                    source_rows+=batch.num_rows
                    table=pa.Table.from_batches([batch])
                    keep=pc.and_(pc.is_in(table['Reporting_Airline'],value_set=pa.array(CARRIERS)),
                        pc.or_(pc.is_in(table['Origin'],value_set=pa.array(HUBS)),pc.is_in(table['Dest'],value_set=pa.array(HUBS))))
                    table=table.filter(keep)
                    if table.num_rows==0: continue
                    arrays=[]
                    for raw,name in FIELDS.items():
                        arr=table[raw]
                        if name in NUMERIC: arr=pc.cast(arr,pa.float64())
                        elif name in TIMES: arr=pc.cast(pc.cast(arr,pa.float64()),pa.int16())
                        elif name.endswith('_airport_id'): arr=pc.cast(arr,pa.int32())
                        elif name=='flight_date': arr=pc.cast(pc.strptime(arr,format='%Y-%m-%d',unit='s'),pa.date32())
                        arrays.append(arr)
                    normalized=pa.Table.from_arrays(arrays,names=list(FIELDS.values()))
                    normalized=normalized.append_column('flight_month',pa.array([month]*table.num_rows,type=pa.int8()))
                    normalized=normalized.append_column('source_snapshot',pa.array([snapshot]*table.num_rows))
                    if writer is None: writer=pq.ParquetWriter(tmp,normalized.schema,compression='zstd')
                    writer.write_table(normalized)
                    selected_rows+=normalized.num_rows
                    for k in sums:
                        value=pc.sum(normalized[k]).as_py()
                        sums[k]+=value or 0.0
                        nonnull[k]+=normalized[k].length()-normalized[k].null_count
        if writer is None: raise ValueError('Scope selection returned no rows')
    finally:
        if writer is not None: writer.close()
    os.replace(tmp,part)
    record.update(source_snapshot=snapshot,year=year,month=month,source_rows=source_rows,
                  selected_rows=selected_rows,scope_airports=list(HUBS),scope_carriers=list(CARRIERS),
                  selected_sums=sums,selected_nonnull_counts=nonnull,parquet_path=str(part.relative_to(ROOT)),
                  parquet_sha256=sha256(part),parquet_bytes=part.stat().st_size,
                  seconds=round(time.perf_counter()-started,3),schema_version=1,
                  grain='one source reported scheduled flight before downstream deduplication')
    if refresh and manifest.exists():
        prior=json.loads(manifest.read_text())
        archive=manifest.parent/'history'/f"{manifest.stem}-{prior['sha256'][:12]}.json"
        atomic_json(archive,prior)
    atomic_json(manifest,record)
    print(f'BTS {year}-{month:02d}: {selected_rows:,}/{source_rows:,} rows, {record["seconds"]:.1f}s',flush=True)
    return record


def quality_value(value: str, missing: str, scale: float=1.0, quality_index: int=1, value_index: int=0):
    """Accept flags 0/4 (gross limits) and 1/5 (all checks); reject suspect/error/unclassified."""
    bits=value.split(',')
    if len(bits)<=max(quality_index,value_index): return None
    if bits[quality_index] not in {'0','1','4','5'} or bits[value_index].lstrip('+')==missing: return None
    try: return float(bits[value_index])/scale
    except ValueError: return None


def ingest_station(year: int, airport: str, station: str, cache: Path, refresh: bool=False) -> dict:
    part=DATA/f'weather/year={year}/station={station}/part.parquet'
    manifest=DATA/f'manifests/noaa-{year}-{station}.json'
    old=reusable(manifest,part,refresh)
    if old: return old
    preserve_previous(manifest,part,refresh)
    source=cache/f'noaa-{year}-{station}.csv'
    record=download(NOAA_URL.format(year=year,station=station),source,refresh)
    snapshot=f'noaa-{year}-{station}-'+record['sha256'][:12]
    rows=[]
    with source.open(newline='') as f:
        for raw in csv.DictReader(f):
            if raw['STATION']!=station: raise ValueError(f'Wrong NOAA station {raw["STATION"]}')
            observed=datetime.fromisoformat(raw['DATE'])
            if observed.year!=year: raise ValueError('Unexpected observation year')
            rows.append({'airport':airport,'station':station,'observed_at':observed,
             'temperature':quality_value(raw['TMP'],'9999',10),
             'wind_speed':quality_value(raw['WND'],'9999',10,quality_index=4,value_index=3),
             'visibility':quality_value(raw['VIS'],'999999',1),
             'ceiling':quality_value(raw['CIG'],'99999',1),
             'pressure':quality_value(raw['SLP'],'99999',10),
             'report_type':raw['REPORT_TYPE'],'source_snapshot':snapshot,
             # Retain quality strings for source reconciliation / later parsing revisions.
             'raw_tmp':raw['TMP'],'raw_wnd':raw['WND'],'raw_vis':raw['VIS'],
             'raw_cig':raw['CIG'],'raw_slp':raw['SLP']})
    schema=pa.schema([('airport',pa.string()),('station',pa.string()),('observed_at',pa.timestamp('us')),
       ('temperature',pa.float64()),('wind_speed',pa.float64()),('visibility',pa.float64()),
       ('ceiling',pa.float64()),('pressure',pa.float64()),('report_type',pa.string()),('source_snapshot',pa.string()),
       ('raw_tmp',pa.string()),('raw_wnd',pa.string()),('raw_vis',pa.string()),('raw_cig',pa.string()),('raw_slp',pa.string())])
    table=pa.Table.from_pylist(rows,schema=schema)
    part.parent.mkdir(parents=True,exist_ok=True)
    tmp=part.with_suffix('.parquet.tmp'); pq.write_table(table,tmp,compression='zstd'); os.replace(tmp,part)
    record.update(source_snapshot=snapshot,airport=airport,station=station,year=year,source_rows=len(rows),
                  selected_rows=len(rows),parquet_path=str(part.relative_to(ROOT)),parquet_sha256=sha256(part),
                  parquet_bytes=part.stat().st_size,first_observed=min(x['observed_at'] for x in rows).isoformat(),
                  last_observed=max(x['observed_at'] for x in rows).isoformat(),
                  source_station_name=raw['NAME'],source_latitude=raw['LATITUDE'],source_longitude=raw['LONGITUDE'],
                  grain='one station source observation, including sub-hourly and duplicate timestamps',schema_version=1)
    atomic_json(manifest,record)
    print(f'NOAA {airport}: {len(rows):,} observations',flush=True)
    return record


def ingest_airports(cache: Path, refresh: bool=False) -> dict:
    part=DATA/'airports.parquet'; manifest=DATA/'manifests/airports.json'
    old=reusable(manifest,part,refresh)
    if old: return old
    preserve_previous(manifest,part,refresh)
    source=cache/'openflights-airports.dat'; record=download(AIRPORT_URL,source,refresh)
    rows=[]
    with source.open(newline='') as f:
        for r in csv.reader(f):
            if r[4] in ('\\N','') or r[11] in ('\\N',''): continue
            rows.append({'code':r[4],'name':r[1],'city':r[2],'country':r[3],
                         'lat':float(r[6]),'lon':float(r[7]),'timezone':r[11],
                         'source_snapshot':'openflights-'+record['sha256'][:12]})
    table=pa.Table.from_pylist(rows)
    tmp=part.with_suffix('.parquet.tmp')
    pq.write_table(table,tmp,compression='zstd'); os.replace(tmp,part)
    record.update(source_rows=len(rows),selected_rows=len(rows),parquet_path=str(part.relative_to(ROOT)),
                  parquet_sha256=sha256(part),parquet_bytes=part.stat().st_size,
                  license='ODbL-1.0 and DbCL-1.0',attribution='OpenFlights airport database; https://openflights.org/data.php',
                  grain='one IATA airport metadata row; downstream asserts code uniqueness',schema_version=1)
    atomic_json(manifest,record)
    return record


def quickstart(year: int) -> None:
    """Small actual January 15-21 slice; weather buffered 24h either side for as-of joins."""
    import duckdb
    out=DATA/'quickstart'; out.mkdir(exist_ok=True,parents=True)
    con=duckdb.connect()
    flight=DATA/f'flights/year={year}/month=01/part.parquet'
    if not flight.exists(): return
    con.execute(f"COPY (SELECT * FROM read_parquet('{flight}',hive_partitioning=false) WHERE flight_date BETWEEN DATE '{year}-01-15' AND DATE '{year}-01-21') TO '{out/'flights.parquet'}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.execute(f"COPY (SELECT * FROM read_parquet('{DATA}/weather/year={year}/station=*/part.parquet',hive_partitioning=false) WHERE observed_at >= TIMESTAMP '{year}-01-14' AND observed_at < TIMESTAMP '{year}-01-23') TO '{out/'weather.parquet'}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    # Metadata remains a separate licensed database, never relicensed with government observations.
    shutil.copyfile(DATA/'airports.parquet',out/'airports.parquet')
    atomic_json(out/'manifest.json',{'description':'Real BTS and NOAA January 15-21 subset; NOAA includes adjacent day buffers.',
        'year':year,'files':{p.name:{'bytes':p.stat().st_size,'sha256':sha256(p)} for p in out.glob('*.parquet')},
        'source_manifests':['data/manifests/bts-'+str(year)+'-01.json']+
           ['data/manifests/noaa-'+str(year)+'-'+station+'.json' for station in STATIONS.values()]+['data/manifests/airports.json'],
        'license_notes':'BTS and NOAA observations: US federal public data, cite agencies; airports: ODbL-1.0/DbCL-1.0, OpenFlights attribution retained. See LICENSE-DATA.md.',
        'not_suitable_for':'Estimating annual forecasting performance from one week; use full-year rebuild.'})
    con.close()


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--year',type=int,default=2024)
    parser.add_argument('--months',type=int,nargs='+',default=list(range(1,13)))
    parser.add_argument('--cache',type=Path,default=Path('/tmp') / ('cascade-source-cache-'+hashlib.sha256(str(ROOT).encode()).hexdigest()[:10]))
    parser.add_argument('--workers',type=int,default=3)
    parser.add_argument('--refresh',action='store_true')
    parser.add_argument('--skip-weather',action='store_true')
    args=parser.parse_args()
    if any(m<1 or m>12 for m in args.months): parser.error('months must be 1..12')
    started=time.perf_counter()
    DATA.mkdir(parents=True,exist_ok=True)
    with futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs=[pool.submit(ingest_month,args.year,m,args.cache,args.refresh) for m in args.months]
        if not args.skip_weather:
            jobs.extend(pool.submit(ingest_station,args.year,a,s,args.cache,args.refresh) for a,s in STATIONS.items())
        jobs.append(pool.submit(ingest_airports,args.cache,args.refresh))
        results=[job.result() for job in futures.as_completed(jobs)]
    if not args.skip_weather and (DATA/f'flights/year={args.year}/month=01/part.parquet').exists(): quickstart(args.year)
    atomic_json(DATA/'ingestion_run.json',{'year':args.year,'months':args.months,
      'seconds':round(time.perf_counter()-started,3),'snapshots':[r.get('source_snapshot',r['sha256'][:12]) for r in results],
      'flight_source_rows':sum(r['source_rows'] for r in results if 'scope_carriers' in r),
      'flight_selected_rows':sum(r['selected_rows'] for r in results if 'scope_carriers' in r),
      'source_bytes':sum(r['bytes'] for r in results),
      'selected_parquet_bytes':sum(r['parquet_bytes'] for r in results),
      'scope_airports':list(HUBS),'scope_carriers':list(CARRIERS),
      'completed_at':datetime.now(timezone.utc).isoformat(),'cache_path':str(args.cache)})
    print('Ingestion complete: '+json.dumps(json.loads((DATA/'ingestion_run.json').read_text())),flush=True)

if __name__=='__main__': main()
