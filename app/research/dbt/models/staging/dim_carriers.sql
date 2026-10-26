-- Grain/key: reporting carrier code, scoped to the four selected BTS carriers.
-- Stable display labels; reporting_airline remains the historical analytical key.
select * from (values
 ('AA','American Airlines'), ('DL','Delta Air Lines'),
 ('UA','United Airlines'), ('WN','Southwest Airlines')
) as t(carrier,carrier_name)
