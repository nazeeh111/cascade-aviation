-- Verify deduplication/quarantine accounting and that signed delay totals survive normalization.
with distinct_rows as (select distinct * from raw_flights),
keys as (
 select *,count(*) over(partition by flight_date, reporting_airline,
 flight_number_reporting_airline,origin,dest,crs_dep_time) as versions from distinct_rows
), expected as (
 select count(*) as n,sum(dep_delay) as signed_dep,sum(arr_delay) as signed_arr,
        count(*) filter(where dep_delay<0) as early,
        count(dep_delay) as dep_observations,count(arr_delay) as arr_observations,
        sum(cancelled) as cancellations,sum(diverted) as diversions from keys where versions=1
), actual as (
 select count(*) as n,sum(dep_delay) as signed_dep,sum(arr_delay) as signed_arr,
        count(*) filter(where dep_delay<0) as early,
        count(dep_delay) as dep_observations,count(arr_delay) as arr_observations,
        sum(cancelled) as cancellations,sum(diverted) as diversions from {{ ref('stg_flights') }}
)
select 'source_reconciliation' as issue from expected e cross join actual a
where e.n<>a.n or abs(e.signed_dep-a.signed_dep)>0.0001
or abs(e.signed_arr-a.signed_arr)>0.0001 or e.early<>a.early
or e.dep_observations<>a.dep_observations or e.arr_observations<>a.arr_observations
or e.cancellations<>a.cancellations or e.diversions<>a.diversions
