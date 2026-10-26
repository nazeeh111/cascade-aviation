-- Grain/key: cutoff, source, target. Weight from preceding 28 days' schedules only.
-- No realized future tail assignment and no future weather or delay-cause fields.
with daily as (
  select flight_date as day,origin as source,dest as target,count(*) as flights
  from {{ ref('stg_flights') }}
  where origin in ('ATL','ORD','DFW','DEN') and dest in ('ATL','ORD','DFW','DEN')
  group by 1,2,3
), days as (select distinct cutoff::date as day from {{ ref('int_airport_hours') }}),
edges as (select distinct source,target from daily), weights as (
  select d.day,e.source,e.target,coalesce(sum(f.flights),0) as prior_flights
  from days d cross join edges e left join daily f on f.source=e.source and f.target=e.target
      and f.day>=d.day-interval '28 day' and f.day<d.day
  group by 1,2,3
)
select h.cutoff,w.source,w.target,w.prior_flights,
       w.prior_flights/nullif(sum(w.prior_flights) over(partition by h.cutoff,w.target),0) as weight
from (select distinct cutoff from {{ ref('int_airport_hours') }}) h join weights w on w.day=h.cutoff::date
