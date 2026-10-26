import datetime as dt
from cascade.warehouse import local_departure


def test_midnight_rollover_and_signed_early_event():
    stamp,status=local_departure(dt.date(2024,1,1),2400,'America/Chicago')
    assert stamp==dt.datetime(2024,1,2,6) and status=='valid'
    assert stamp+dt.timedelta(minutes=-10)==dt.datetime(2024,1,2,5,50)


def test_dst_gap_is_quarantined():
    assert local_departure(dt.date(2024,3,10),230,'America/New_York')==(None,'dst_gap')


def test_dst_overlap_is_flagged_and_deterministic():
    stamp,status=local_departure(dt.date(2024,11,3),130,'America/New_York')
    assert stamp==dt.datetime(2024,11,3,5,30) and status=='dst_ambiguous_fold0'


def test_invalid_or_missing_time():
    assert local_departure(dt.date(2024,1,1),1260,'America/Chicago')[0] is None
    assert local_departure(dt.date(2024,1,1),None,'America/Chicago')[0] is None
