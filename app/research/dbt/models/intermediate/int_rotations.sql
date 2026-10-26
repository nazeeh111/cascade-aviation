-- Grain/key: following flight_id. Retrospective observed-tail analysis ONLY.
-- Missing tails, diversions, overlaps, discontinuous airports and turns >12h are not valid links.
with ordered as (
    select flight_id,carrier,tail_number,origin,dest,sched_dep_utc,sched_arr_utc,actual_dep_utc,actual_arr_utc,
        lag(flight_id) over w as prev_flight_id,
        lag(dest) over w as prev_dest,
        lag(sched_arr_utc) over w as prev_sched_arr,
        lag(actual_arr_utc) over w as prev_actual_arr,
        lag(arr_delay) over w as prev_arr_delay,
        lead(flight_id) over w as next_flight_id,
        dep_delay
    from {{ ref('stg_flights') }}
    where tail_number is not null and trim(tail_number)<>''
    window w as (partition by carrier,tail_number order by sched_dep_utc,flight_id)
)
select *, date_diff('minute',prev_sched_arr,sched_dep_utc) as scheduled_turn_minutes,
    -- Validate hub turns only: every selected-carrier flight touching a hub is retained.
    -- Nonhub turns could hide omitted nonhub out-and-back flights.
    coalesce(origin in ('ATL','ORD','DFW','DEN') and prev_dest=origin and prev_actual_arr is not null and actual_dep_utc is not null
        and prev_actual_arr<=actual_dep_utc
        and date_diff('minute',prev_sched_arr,sched_dep_utc) between 20 and 720,false) as validated
from ordered
