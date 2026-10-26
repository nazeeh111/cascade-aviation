-- Baseline: inequality join materializes all eligible preceding reports, then ranks.
select airport,cutoff,observed_at,visibility from (
  select h.airport,h.cutoff,w.observed_at,w.visibility,
    row_number() over(partition by h.airport,h.cutoff order by w.available_at desc) as rn
  from int_airport_hours h left join weather w
  on h.airport=w.airport and h.cutoff>=w.available_at
) where rn=1 order by airport,cutoff;
