-- Grain/key: airport, cutoff. Label is next 2h scheduled departure disruption share.
-- Target columns must NEVER enter the feature list. Null labels remain null.
with rolling as (
    select *,
      sum(scheduled_hour) over future as scheduled,
      sum(stressed_hour) over future as stressed,
      sum(unlabelled_hour) over future as unlabelled,
      sum(delay_minutes_hour) over future as target_delay_minutes,
      max(label_available_at) over future as target_available_at,
      sum(reported_departures) over recent as recent_departures,
      sum(reported_late) over recent as recent_late,
      sum(reported_sum_delay) over recent as recent_sum_delay,
      sum(reported_late) over past_week / nullif(sum(reported_departures) over past_week,0) as rolling_rate
    from {{ ref('int_airport_hours') }}
    window future as (partition by airport order by cutoff rows between current row and 1 following),
           recent as (partition by airport order by cutoff rows between 1 preceding and current row),
           past_week as (partition by airport order by cutoff rows between 167 preceding and current row)
), rates as (
    select *, recent_late/nullif(recent_departures,0) as recent_stress,
      recent_sum_delay/nullif(recent_departures,0) as recent_mean_delay,
      lag(recent_late/nullif(recent_departures,0),24) over w as prior_day_rate,
      lag(recent_late/nullif(recent_departures,0),168) over w as prior_week_rate,
      case when unlabelled=0 then stressed/nullif(scheduled,0) end as target_rate,
      extract(hour from cutoff)::int as hour,extract(dow from cutoff)::int as dow,
      extract(month from cutoff)::int as month
    from rolling window w as (partition by airport order by cutoff)
), neighbors as (
    select e.cutoff,e.target as airport,sum(e.weight*r.recent_stress) as neighbor_stress
    from {{ ref('int_network_edges') }} e join rates r on e.source=r.airport and e.cutoff=r.cutoff
    where e.weight is not null group by 1,2
), joined as (
    select r.*, r.scheduled as scheduled_next,
      n.neighbor_stress, w.temperature,w.wind_speed,w.visibility,w.ceiling,w.pressure,
      w.observed_at as weather_observed_at,w.available_at as weather_available_at,
      date_diff('minute',w.observed_at,r.cutoff)/60.0 as weather_age_hours
    from rates r left join neighbors n using(airport,cutoff)
    asof left join {{ ref('stg_weather') }} w on r.airport=w.airport and r.cutoff>=w.available_at
)
select *, 0::int as outstanding,
    case airport when 'ATL' then 0 when 'ORD' then 1 when 'DFW' then 2 when 'DEN' then 3 end as airport_index,
    weather_age_hours>3 or weather_age_hours is null as weather_stale
from joined
where cutoff < (select max(cutoff) from {{ ref('int_airport_hours') }})
