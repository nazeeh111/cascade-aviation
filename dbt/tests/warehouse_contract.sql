-- Tests return only contract violations, not rounded business expectations.
with violations as (
  select 'feature_key_fanout' as issue, airport||cutoff::varchar as detail
  from {{ ref('mart_airport_hour_features') }} group by airport,cutoff having count(*)<>1
  union all
  select 'weather_key_fanout',airport||observed_at::varchar
  from {{ ref('stg_weather') }} group by airport,observed_at having count(*)<>1
  union all
  select 'future_weather',airport||cutoff::varchar from {{ ref('mart_airport_hour_features') }}
  where weather_available_at>cutoff or weather_observed_at>cutoff
  union all
  select 'invalid_rate',airport||cutoff::varchar from {{ ref('mart_airport_hour_features') }}
  where target_rate<0 or target_rate>1 or stressed>scheduled
  union all
  select 'negative_duration',flight_id from {{ ref('stg_flights') }}
  where sched_arr_utc<sched_dep_utc or actual_arr_utc<actual_dep_utc
  union all
  select 'invalid_rotation',flight_id from {{ ref('int_rotations') }}
  where validated and (origin not in ('ATL','ORD','DFW','DEN') or prev_dest<>origin or prev_actual_arr>actual_dep_utc or scheduled_turn_minutes not between 20 and 720)
  union all
  select 'cancelled_actual',flight_id from {{ ref('stg_flights') }}
  where cancelled::boolean and (actual_dep_utc is not null or actual_arr_utc is not null)
  union all
  select 'missing_arrival_zeroed',flight_id from {{ ref('stg_flights') }}
  where (cancelled::boolean or diverted::boolean) and actual_arr_utc is not null
  union all
  select 'invalid_source_flags',flight_id from {{ ref('stg_flights') }}
  where cancelled not in (0,1) or diverted not in (0,1)
  union all
  select 'unexpected_reporting_year',flight_id from {{ ref('stg_flights') }}
  where extract(year from flight_date)<>2024
  union all
  select 'airport_relationship',f.flight_id from {{ ref('stg_flights') }} f
  left join airports a on f.origin=a.code left join airports b on f.dest=b.code
  where a.code is null or b.code is null
)
select * from violations
