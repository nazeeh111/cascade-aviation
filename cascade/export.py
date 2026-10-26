"""Publish small immutable replay exports, with links to their generating artifacts."""
from __future__ import annotations
from collections import defaultdict
import datetime as dt
import hashlib
import json
from pathlib import Path
import shutil

POLICIES={'no_action':'No action','equal':'Equal allocation','demand':'Scheduled demand',
          'recent_stress':'Recent stress','forecast_aware':'Forecast-aware allocation'}

def run(c,root):
    root=Path(root);app=root/'app';assets=app/'data';assets.mkdir(exist_ok=True)
    model=json.loads((root/'artifacts/model_run.json').read_text())
    sim=json.loads((root/'artifacts/simulation.json').read_text())
    tabular=next(m for m in model['models'] if m['name']=='tabular')
    findings=json.loads((root/'artifacts/findings.json').read_text())
    # Days selected from held-out outcomes for coverage; never for model tuning.
    days=c.execute("""select p.cutoff::date AS day,sum(p.actual*p.scheduled)/sum(p.scheduled) AS rate
      from predictions p where p.model='tabular' and exists(select 1 from scenarios s where s.cutoff=p.cutoff)
      group by 1 order by rate""").fetchall()
    choices=[(days[len(days)//2][0],'Ordinary held-out day'),
             (days[int((len(days)-1)*.9)][0],'Elevated disruption day'),
             (days[-1][0],'Most disrupted held-out day')]
    seen=set();selected=[]
    for date,label in choices:
        if date not in seen: selected.append((date,label));seen.add(date)
    airports=[dict(zip(['code','name','lat','lon'],r)) for r in c.execute("SELECT code,name,lat,lon FROM hubs ORDER BY code").fetchall()]
    # Expand each hourly bucket into its two valid forecast windows once.
    # Repeated per-cutoff scans of the full flight relation are unnecessary.
    map_edges=defaultdict(list)
    edge_sql="""WITH hourly AS (
      SELECT date_trunc('hour',sched_dep_utc) AS hour,origin,dest,count(*) AS n FROM flights
      WHERE origin IN ('ATL','ORD','DFW','DEN') AND dest IN ('ATL','ORD','DFW','DEN')
        AND sched_dep_utc IS NOT NULL GROUP BY 1,2,3
    ) SELECT hour-k*INTERVAL '1 hour' AS cutoff,origin,dest,sum(n)::INTEGER AS flights
      FROM hourly CROSS JOIN range(2) r(k) GROUP BY 1,2,3 ORDER BY 1,2,3"""
    for cutoff,source,target,n in c.execute(edge_sql).fetchall():
        map_edges[cutoff].append({'source':source,'target':target,'flights':n})
    (root/'sql/demo_edges.sql').write_text('-- Grain: cutoff/source/target, next two-hour scheduled hub links.\n'+edge_sql+';\n')
    exported=[]
    for date,label in selected:
        cutoffs=[r[0] for r in c.execute("SELECT DISTINCT cutoff FROM scenarios WHERE cutoff::date=? ORDER BY cutoff",[date]).fetchall()]
        day={'date':str(date),'label':label,'cutoffs':[]}
        for cutoff in cutoffs:
            cur=c.execute("""SELECT f.*,p.prediction,p.actual,p.lower,p.upper FROM airport_hour_features f
                 JOIN predictions p USING(airport,cutoff) WHERE cutoff=? AND p.model='tabular' ORDER BY airport""",[cutoff])
            names=[d[0] for d in cur.description];record=[dict(zip(names,r)) for r in cur.fetchall()]
            if len(record)!=4: continue
            scenario_rows=c.execute("""SELECT airport,policy,budget,resources,simulated_delay_minutes,improvement_minutes
                    FROM scenarios WHERE cutoff=? ORDER BY budget,policy,airport""",[cutoff]).fetchall()
            allocations=defaultdict(dict)
            for airport,policy,budget,units,delay,improvement in scenario_rows: allocations[(policy,budget)][airport]=units
            rows=[]
            for r in record:
                row={'code':r['airport'],'scheduled':r['scheduled'],'observed_flights':r['recent_departures'],
                     'observed_stress':r['recent_stress'],'predicted_stress':r['prediction'],'actual_stress':r['actual'],
                     'lower':r['lower'],'upper':r['upper'],
                     'weather':{'temperature_c':r['temperature'],'wind_speed_ms':r['wind_speed'],
                                'visibility_m':r['visibility'],'observed_at':iso(r['weather_observed_at']),
                                'available_at':iso(r['weather_available_at']),'age_hours':r['weather_age_hours']},
                     'scenarios':[{'name':POLICIES[p],'budget':b,'resources':u,'simulated_delay_minutes':d,
                                  'improvement_minutes':i,'allocation':allocations[(p,b)]}
                                  for a,p,b,u,d,i in scenario_rows if a==r['airport']]}
                rows.append(row)
            edges=map_edges.get(cutoff,[])
            day['cutoffs'].append({'timestamp':iso(cutoff),'airports':rows,'edges':edges,
                'scenario_assumptions':f"Selected airport · next {sim['horizon_hours']}h minutes · 15% hypothetical relief/unit · max 2 units/airport · coupling {sim['selected_calibration']['coupling']:.2f}"})
        exported.append(day)
    manifests={p.name:json.loads(p.read_text()) for p in sorted((root/'data/manifests').glob('*.json'))}
    snapshot=hashlib.sha256(json.dumps(manifests,sort_keys=True).encode()).hexdigest()[:16]
    meta={'scope':['2024','ATL','ORD','DFW','DEN','AA · DL · UA · WN'],'year':2024,'horizon_hours':2,'scenario_horizon_hours':sim['horizon_hours'],
          'run_id':model['run_id'],'snapshot_id':snapshot,'interval_coverage':tabular['interval_coverage'],
          'stress_definition':'Departures ≥15 min late or cancelled / all scheduled departures in next 2h',
          'repository_url':'https://github.com/nazeeh111/cascade-aviation',
          'source_snapshot':'./research/source-snapshots.json','model_run':'./research/artifacts/model_run.json',
          'methods_url':'./research/docs/model-card.md',
          'sql_links':[{'label':'Feature SQL','url':'./research/dbt/models/marts/mart_airport_hour_features.sql'},
                       {'label':'EDA + charts','url':'./research/artifacts/investigation.html'},
                       {'label':'Scenario validation','url':'./research/artifacts/simulation.json'},
                       {'label':'Warehouse tests','url':'./research/dbt/tests/warehouse_contract.sql'}],
          'model_note':'Replay uses the predeclared tabular model. Nov–Dec chronological holdout · overlapping 2h targets · per-model inference time (graph includes base prediction). Lowest test error is descriptive; full calibration, intervals and rolling folds are linked.',
          'scenario_limitation':f"Held-out baseline MAE {sim['replay']['mae_delay_minutes']:.0f} minutes vs actual mean {sim['replay']['actual_mean_delay_minutes']:.0f} per airport/4h interval ({sim['replay']['n_days']} days). This coarse aggregate fit limits scenario interpretation. Resource effects are hypothetical; passenger, crew, maintenance and capacity feasibility are absent. Reductions are simulated, not causal savings.",
          'limitations':['Final BTS schedules proxy advance schedules; no historical schedule revisions.',
             'Actual departures and NOAA weather assumed available one hour after occurrence. BTS itself is retrospective.',
             'Four hubs and four reporting carriers; regional affiliates and much of the network are excluded.',
             'Day examples selected after observing holdout outcomes to cover ordinary and severe conditions; models were not tuned on them.',
             'Overlapping windows cannot be added into daily savings. Cancellation delay duration is omitted from simulated minutes.',
             'Retrospective tail chains are diagnostic; forecasts and allocation never use future actual aircraft assignments.']}
    meta['limitations'].append(f"Nominal 90% tabular prediction intervals cover {tabular['interval_coverage']*100:.1f}% of final-holdout outcomes; temporal undercoverage limits uncertainty claims.")
    payload={'meta':meta,'airports':airports,'days':exported,'models':model['models'],
             'findings':[{**f,'sql':'./research/sql/eda.sql'} for f in findings]}
    (assets/'demo.json').write_text(json.dumps(payload,indent=2,allow_nan=False))
    research=app/'research';research.mkdir(exist_ok=True)
    for directory in ['sql','docs','dbt/models','dbt/tests']:
        shutil.copytree(root/directory,research/directory,dirs_exist_ok=True)
    for filename in ['LICENSE','LICENSE-DATA.md']:
        shutil.copy2(root/filename,research/filename)
    shutil.copytree(root/'data/manifests',research/'data/manifests',dirs_exist_ok=True)
    target=research/'artifacts';target.mkdir(exist_ok=True)
    for p in (root/'artifacts').iterdir():
        if p.suffix in ('.json','.png','.html','.txt'):
            shutil.copy2(p,target/p.name)
    (research/'source-snapshots.json').write_text(json.dumps(manifests,indent=2))
    result={'snapshot_id':snapshot,'model_run':model['run_id'],'days':len(exported),
            'cutoffs':sum(len(d['cutoffs']) for d in exported),'bytes':(assets/'demo.json').stat().st_size,
            'demo_sha256':hashlib.sha256((assets/'demo.json').read_bytes()).hexdigest()}
    (root/'artifacts/demo-export.json').write_text(json.dumps(result,indent=2))
    return result

def iso(v):
    return v.isoformat()+'Z' if isinstance(v,dt.datetime) else None
