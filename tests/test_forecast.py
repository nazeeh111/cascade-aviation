from datetime import datetime, timedelta
import numpy as np
from cascade.forecast import chronological_mask, metrics, FEATURES, NETWORK_FEATURES, Seasonal


def test_training_labels_cannot_cross_cutoff_boundary():
    boundary = datetime(2024, 11, 1)
    times = [boundary-timedelta(hours=3), boundary-timedelta(hours=2), boundary-timedelta(hours=1), boundary]
    assert chronological_mask(times, datetime(2024, 1, 1), boundary).tolist() == [True, False, False, False]


def test_cancellation_and_future_outcomes_are_not_model_inputs():
    forbidden = {"cancelled", "target_rate", "stressed", "target_delay_minutes", "dep_delay", "arr_delay", "actual_arr_utc", "actual_dep_utc", "tail_number", "carrier_delay", "weather_delay", "nas_delay", "late_aircraft_delay"}
    assert not forbidden.intersection(NETWORK_FEATURES)
    assert "airport" in FEATURES
    assert set(NETWORK_FEATURES)-set(FEATURES) == {"neighbor_stress"}


def test_calibration_denominator_weights_and_severe_recall():
    result = metrics(np.array([0.,1.]), np.array([.1,.5]), np.array([9,1]))
    assert np.isclose(result["mae"], .3)
    assert np.isclose(result["weighted_mae"], .14)
    assert result["severe_recall"] == 1.
    assert result["scheduled_denominator"] == 10


def test_seasonal_unseen_cohort_has_training_only_fallback():
    cols = ["airport", "hour", "dow"]
    model = Seasonal().fit([("ATL", 5, 1), ("ORD", 5, 1)], cols, np.array([.1,.9]), np.array([9,1]))
    assert np.isclose(model.predict([("DEN", 10, 2)],cols)[0], .18)


def test_late_departure_or_cancellation_label_cannot_enter_earlier_fit():
    boundary=datetime(2024,11,1)
    times=[boundary-timedelta(hours=5)]*4
    availability=[boundary-timedelta(hours=1),boundary,boundary+timedelta(hours=2),None]
    mask=chronological_mask(times,datetime(2024,1,1),boundary,available_at=availability)
    assert mask.tolist()==[True,False,False,False]


def test_holdout_scoring_keeps_eventual_late_outcomes():
    boundary=datetime(2025,1,1)
    times=[boundary-timedelta(hours=5)]*2
    availability=[boundary+timedelta(hours=1),boundary-timedelta(hours=1)]
    assert chronological_mask(times,datetime(2024,11,1),boundary,available_at=availability).tolist()==[False,True]
    assert chronological_mask(times,datetime(2024,11,1),boundary,available_at=availability,require_available=False).tolist()==[True,True]
