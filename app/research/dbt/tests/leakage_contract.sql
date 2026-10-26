-- Compare pre-cutoff SQL features against directly censored source event times.
-- Sample every 97th grid hour for a bounded independent recomputation.
with sampled as (
 select * from {{ ref('mart_airport_hour_features') }}
 where date_diff('hour',timestamp '2024-01-01',cutoff)%97=0
), recomputed as (
 select s.airport,s.cutoff,s.recent_departures,s.recent_late,
   count(f.flight_id) as expected_departures,
   count(*) filter(where f.dep_delay>=15) as expected_late
 from sampled s left join {{ ref('stg_flights') }} f
 on s.airport=f.origin and f.actual_dep_utc>=s.cutoff-interval '3 hour'
    and f.actual_dep_utc<s.cutoff-interval '1 hour'
 group by 1,2,3,4
)
select airport,cutoff,'departure_availability' as issue from recomputed
where recent_departures<>expected_departures or recent_late<>expected_late
union all
select s.airport,s.cutoff,'weather_asof' from sampled s
where exists(select 1 from {{ ref('stg_weather') }} w where w.airport=s.airport
 and w.available_at<=s.cutoff and (s.weather_available_at is null or w.available_at>s.weather_available_at))
