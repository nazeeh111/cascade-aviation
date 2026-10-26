from cascade.ingest import quality_value

def test_noaa_temperature_preserves_sign_and_scales_units():
    assert quality_value('-0123,1','9999',10)==-12.3
    assert quality_value('+9999,1','9999',10) is None
    assert quality_value('+0123,3','9999',10) is None

def test_noaa_wind_position_and_quality_are_independent_of_direction():
    assert quality_value('090,1,N,0051,1','9999',10,4,3)==5.1
    assert quality_value('090,1,N,9999,1','9999',10,4,3) is None
    assert quality_value('090,1,N,0051,3','9999',10,4,3) is None
