-- Grain: one unambiguous reported scheduled flight. Key: flight_id.
-- Source snapshot is the final monthly extract, not an operational schedule feed.
with deduplicated as (
    select distinct * from raw_flights
), keyed as (
    select *, md5(concat_ws('|', flight_date::varchar, reporting_airline,
         flight_number_reporting_airline, origin, dest, crs_dep_time::varchar)) as flight_id
    from deduplicated
), joined as (
    select f.*, f.reporting_airline as carrier, a.timezone as origin_timezone,
           b.timezone as dest_timezone, t.sched_dep_utc, coalesce(t.time_status,'missing') as time_status,
           count(*) over (partition by flight_id) as key_versions
    from keyed f
    left join airports a on f.origin = a.code
    left join airports b on f.dest = b.code
    left join departure_times t on f.flight_date=t.flight_date
         and f.crs_dep_time=t.crs_dep_time and a.timezone=t.timezone
), times as (
    select *, sched_dep_utc + crs_elapsed_time * interval '1 minute' as sched_arr_utc,
       case when not cancelled::boolean and dep_delay is not null
           then sched_dep_utc + dep_delay * interval '1 minute' end as actual_dep_utc
    from joined
)
select *, case when not diverted::boolean and not cancelled::boolean and actual_elapsed_time is not null
                   then actual_dep_utc + actual_elapsed_time * interval '1 minute' end as actual_arr_utc,
       case when cancelled::boolean then true when dep_delay is not null then dep_delay>=15 end as stressed,
       -- Reported HHMM vs elapsed-based scheduled arrival, including midnight rollover.
       case when dest_timezone is not null and sched_arr_utc is not null and crs_arr_time is not null
         then (extract(hour from timezone(dest_timezone, timezone('UTC',sched_arr_utc)))::int*100
               + extract(minute from timezone(dest_timezone, timezone('UTC',sched_arr_utc)))::int)
               = (case when crs_arr_time=2400 then 0 else crs_arr_time end) end as arrival_clock_agrees
from times where key_versions=1
