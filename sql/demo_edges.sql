-- Grain: cutoff/source/target, next two-hour scheduled hub links.
WITH hourly AS (
      SELECT date_trunc('hour',sched_dep_utc) AS hour,origin,dest,count(*) AS n FROM flights
      WHERE origin IN ('ATL','ORD','DFW','DEN') AND dest IN ('ATL','ORD','DFW','DEN')
        AND sched_dep_utc IS NOT NULL GROUP BY 1,2,3
    ) SELECT hour-k*INTERVAL '1 hour' AS cutoff,origin,dest,sum(n)::INTEGER AS flights
      FROM hourly CROSS JOIN range(2) r(k) GROUP BY 1,2,3 ORDER BY 1,2,3;
