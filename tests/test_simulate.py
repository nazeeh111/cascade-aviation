import itertools
import numpy as np
import pytest
from cascade.simulate import feasible_allocations, pressure, scenario, optimizer, greedy_allocation


def test_zero_budget_identity_and_policy_constraint():
    b=np.array([10.,20.,30.,40.])
    a=np.array([[0,.3,0,0],[0,0,.4,0],[0,0,0,.6],[.3,0,0,0]])
    baseline=pressure(b,a,.2)
    allocation=optimizer(b,a,.2,0)
    assert allocation.sum()==0
    np.testing.assert_allclose(scenario(b,a,.2,allocation),baseline)
    for budget in range(5):
        allocation=optimizer(b,a,.2,budget)
        assert allocation.sum()==budget
        assert (allocation<=2).all()
        assert (scenario(b,a,.2,allocation)<=baseline+1e-9).all()


def test_exact_optimizer_matches_all_feasible_actions():
    b=np.array([50.,1.,10.,35.])
    a=np.array([[0,.5,0,0],[0,0,1,0],[0,0,0,0],[.2,0,0,0]])
    allocation=optimizer(b,a,.3,3)
    score=scenario(b,a,.3,allocation).sum()
    candidates=[v for v in itertools.product(range(3),repeat=4) if sum(v)==3]
    assert score<=min(scenario(b,a,.3,np.array(v)).sum() for v in candidates)+1e-9


def test_propagation_conserves_direction_and_resource_effect():
    a=np.zeros((4,4));a[0,1]=1
    result=pressure([100,0,0,0],a,.2)
    np.testing.assert_allclose(result,[100,20,0,0])
    reduced=scenario([100,0,0,0],a,.2,[1,0,0,0],.15)
    np.testing.assert_allclose(reduced,[85,17,0,0])


def test_invalid_capacity_or_unstable_graph_is_rejected():
    with pytest.raises(ValueError): feasible_allocations(-1)
    with pytest.raises(ValueError): feasible_allocations(9)
    with pytest.raises(ValueError): pressure([1,2,3,4],np.ones((4,4)),.2)
    with pytest.raises(ValueError): pressure([1,2,3,4],np.eye(4),1)
    with pytest.raises(ValueError): scenario([1,2,3,4],np.eye(4),.2,[3,0,0,0])
    assert greedy_allocation([1,1,1,1],4).tolist()==[1,1,1,1]


def test_only_one_hop_can_transmit_within_scenario():
    a=np.zeros((4,4));a[0,1]=1;a[1,2]=1
    np.testing.assert_allclose(pressure([100,0,0,0],a,.2),[100,20,0,0])


def test_schedule_edges_require_arrival_and_turn_within_four_hours():
    import duckdb
    from cascade.simulate import _matrices, AIRPORTS
    from datetime import datetime
    c=duckdb.connect()
    c.execute("CREATE TABLE airport_hour_features(cutoff TIMESTAMP)")
    c.execute("INSERT INTO airport_hour_features VALUES ('2024-11-01 12:00:00')")
    c.execute("CREATE TABLE flights(origin VARCHAR,dest VARCHAR,sched_dep_utc TIMESTAMP,sched_arr_utc TIMESTAMP)")
    c.execute("""INSERT INTO flights VALUES
        ('ATL','ORD','2024-11-01 12:15:00','2024-11-01 14:15:00'),
        ('ATL','DEN','2024-11-01 12:30:00','2024-11-01 15:30:00'),
        ('ATL','BOS','2024-11-01 13:00:00','2024-11-01 15:00:00')""")
    matrices,_=_matrices(c)
    a=matrices[datetime(2024,11,1,12)]
    assert np.isclose(a[AIRPORTS.index('ATL'),AIRPORTS.index('ORD')],1/3)
    assert a[AIRPORTS.index('ATL'),AIRPORTS.index('DEN')]==0
    c.close()
