"""Exercise distributed real-data and replay contracts, independent of rendering."""
from pathlib import Path
import hashlib
import json
from urllib.parse import urlparse
import pytest

ROOT=Path(__file__).resolve().parents[1]

def test_quickstart_bytes_match_published_snapshot():
    folder=ROOT/'data/quickstart'
    manifest=json.loads((folder/'manifest.json').read_text())
    for name,expected in manifest['files'].items():
        data=(folder/name).read_bytes()
        assert len(data)==expected['bytes']
        assert hashlib.sha256(data).hexdigest()==expected['sha256']


def test_real_replay_has_complete_distinct_heldout_days_and_bounded_allocations():
    path=ROOT/'app/data/demo.json'
    if not path.exists(): pytest.skip('Annual replay export not generated yet')
    data=json.loads(path.read_text(),parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    assert len(data['days'])>=2
    assert len(set(d['date'] for d in data['days']))==len(data['days'])
    assert data['meta']['horizon_hours']==2
    assert data['meta']['scenario_horizon_hours']==4
    assert len(data['findings'])>=3
    for day in data['days']:
        assert '2024-11-01'<=day['date']<'2025-01-01'
        assert day['cutoffs']
        for cutoff in day['cutoffs']:
            assert {r['code'] for r in cutoff['airports']}=={'ATL','ORD','DFW','DEN'}
            for r in cutoff['airports']:
                assert r['scheduled']>=3 and 0<=r['predicted_stress']<=1
                assert 0<=r['lower']<=r['upper']<=1
                assert r['weather']['available_at']<=cutoff['timestamp']
                for scenario in r['scenarios']:
                    allocation=scenario['allocation']
                    assert all(isinstance(u,int) and 0<=u<=2 for u in allocation.values())
                    if scenario['name']!='No action':
                        assert sum(allocation.values())==scenario['budget']
                    assert scenario['simulated_delay_minutes']>=0
                    assert scenario['improvement_minutes']>=-1e-8


def test_provenance_links_resolve_in_distribution():
    path=ROOT/'app/data/demo.json'
    if not path.exists(): pytest.skip('Annual replay export not generated yet')
    data=json.loads(path.read_text());meta=data['meta']
    links=[l['url'] for l in meta['sql_links']]+[meta['source_snapshot'],meta['model_run'],meta['methods_url']]
    links += [f['sql'] for f in data['findings']]
    for link in links:
        if not urlparse(link).scheme:
            assert (ROOT/'app'/link).is_file(),link
