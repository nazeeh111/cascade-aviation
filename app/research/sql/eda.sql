-- Rerunnable EDA: all denominators are explicit; delays retain their signs.
-- Missingness and cancellation censoring (one reported flight).
select count(*) as reported_flights,
 count(*) filter(where dep_delay is null) as missing_dep_delay,
 count(*) filter(where arr_delay is null) as missing_arr_delay,
 count(*) filter(where cancelled::boolean) as cancelled,
 count(*) filter(where diverted::boolean) as diverted,
 count(*) filter(where tail_number is null or tail_number='') as missing_tail,
 count(*) filter(where dep_delay<0) as early_departures,
 count(*) filter(where time_status<>'valid') as time_exceptions,
 count(*) filter(where arrival_clock_agrees=false) as arrival_clock_mismatches
from flights;

-- Delay tails among non-null reported observations; mean includes early arrivals.
select quantile_cont(dep_delay,[0.1,0.5,0.9,0.95,0.99]) as departure_quantiles,
 quantile_cont(arr_delay,[0.1,0.5,0.9,0.95,0.99]) as arrival_quantiles,
 avg(dep_delay) as mean_departure_delay,avg(arr_delay) as mean_arrival_delay
from flights;

-- Cohort and seasonality: denominator is all scheduled flights originating in scope.
select origin,carrier,extract(month from flight_date)::int as month,count(*) as scheduled,
 avg(cancelled) as cancellation_rate,
 count(*) filter(where dep_delay>=15 or cancelled::boolean)*1.0/count(*) as disruption_rate,
 count(dep_delay) as departure_delay_observations,avg(dep_delay) as mean_observed_delay
from flights where origin in ('ATL','ORD','DFW','DEN') group by 1,2,3 order by 1,2,3;

-- Weather association: lagged observation at the cutoff, not future weather.
-- Overlapping hourly 2h windows are repeated intervals, not independent flights.
select case when visibility<5000 then 'visibility <5 km' else 'visibility >=5 km' end as cohort,
 count(*) as airport_cutoffs,sum(scheduled) as overlapping_scheduled_exposures,
 sum(stressed)*1.0/nullif(sum(scheduled),0) as disruption_rate
from airport_hour_features
where visibility is not null and weather_age_hours<=3 and target_rate is not null
group by 1;

-- Association within validated observed-aircraft hub turns, not causal propagation.
select case when prev_arr_delay>=15 then 'previous arrival >=15 min late' else 'previous arrival <15 min late' end as cohort,
 count(*) as validated_links,avg((dep_delay>=15)::int) as following_departure_late_rate,
 avg(dep_delay) as following_mean_departure_delay
from rotations where validated and prev_arr_delay is not null and dep_delay is not null group by 1;
