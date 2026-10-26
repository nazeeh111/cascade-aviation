-- Grain/key: airport, observed_at. Prefer one quality-filtered report per timestamp.
-- Publication timestamps are unavailable: availability is ASSUMED observed_at + 1h.
select * exclude(rn), observed_at + interval '1 hour' as available_at
from (
    -- Prefer routine METAR (FM-15), then special METAR (FM-16), then SYNOP.
    -- Remaining ties prefer complete accepted measurements, then raw content.
    -- Lexical content tie-break is deterministic; it does not imply superior truth.
    select *, row_number() over(partition by airport,observed_at order by
       case trim(report_type) when 'FM-15' then 0 when 'FM-16' then 1 when 'FM-12' then 2 else 3 end,
       ((temperature is not null)::int+(wind_speed is not null)::int+
        (visibility is not null)::int+(ceiling is not null)::int+(pressure is not null)::int) desc,
       report_type,raw_tmp,raw_wnd,raw_vis,raw_cig,raw_slp,source_snapshot,station) as rn
    from raw_weather
) where rn=1
