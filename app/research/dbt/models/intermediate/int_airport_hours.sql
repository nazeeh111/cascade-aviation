-- Grain/key: airport, cutoff. UTC hourly grid with a non-overlapping label bucket.
with bounds as (
    select date_trunc('day',min(sched_dep_utc)) as lo,
           date_trunc('day',max(sched_dep_utc)) + interval '1 day' as hi
    from {{ ref('stg_flights') }} where origin in ('ATL','ORD','DFW','DEN')
), grid as (
    select h.code as airport, r.range as cutoff
    from hubs h cross join bounds b cross join lateral range(b.lo,b.hi,interval '1 hour') r
), scheduled as (
    select origin as airport,date_trunc('hour',sched_dep_utc) as cutoff,
        count(*) as scheduled_hour,
        count(*) filter(where stressed) as stressed_hour,
        count(*) filter(where stressed is null) as unlabelled_hour,
        sum(greatest(dep_delay,0)) filter(where not cancelled::boolean) as delay_minutes_hour,
        max(case when cancelled::boolean then sched_dep_utc+interval '24 hour'
            else actual_dep_utc+interval '1 hour' end) as label_available_at
    from {{ ref('stg_flights') }} where sched_dep_utc is not null
    group by 1,2
), events as (
    select origin as airport,date_trunc('hour',actual_dep_utc) as event_hour,
       count(*) as departures, count(*) filter(where dep_delay>=15) as late,
       sum(dep_delay) as sum_delay
    from {{ ref('stg_flights') }} where actual_dep_utc is not null group by 1,2
)
select g.*,coalesce(s.scheduled_hour,0) as scheduled_hour,
       coalesce(s.stressed_hour,0) as stressed_hour,coalesce(s.unlabelled_hour,0) as unlabelled_hour,
       coalesce(s.delay_minutes_hour,0) as delay_minutes_hour,s.label_available_at,
       -- Only events strictly before cutoff, with conservative one-hour event reporting latency.
       coalesce(e.departures,0) as reported_departures,
       coalesce(e.late,0) as reported_late,coalesce(e.sum_delay,0) as reported_sum_delay
from grid g left join scheduled s using(airport,cutoff)
left join events e on e.airport=g.airport and e.event_hour=g.cutoff-interval '2 hour'
