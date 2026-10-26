-- Optimized: ASOF operator selects exactly one preceding report without the fan-out.
select h.airport,h.cutoff,w.observed_at,w.visibility
from int_airport_hours h asof left join weather w
on h.airport=w.airport and h.cutoff>=w.available_at
order by h.airport,h.cutoff;
