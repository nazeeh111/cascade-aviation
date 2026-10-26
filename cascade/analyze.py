"""Rerunnable SQL EDA and bounded, result-identical query profiling."""
from __future__ import annotations
import hashlib
import html
import json
from pathlib import Path
import platform
import statistics
import time
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

def rows(c, sql):
    cur=c.execute(sql)
    names=[d[0] for d in cur.description]
    return [dict(zip(names,r)) for r in cur.fetchall()]


def run(c, root):
    root=Path(root); out=root/'artifacts'; out.mkdir(exist_ok=True)
    queries=[statement.query for statement in c.extract_statements((root/'sql/eda.sql').read_text())]
    result=[rows(c,q) for q in queries]
    missing,tails,cohorts,weather,chains=result
    summary=missing[0]; n=summary['reported_flights']
    full={'scope':'2024 AA/DL/UA/WN flights touching ATL/ORD/DFW/DEN',
          'queries':'sql/eda.sql','missingness':summary,'delay_distribution':tails[0],
          'airport_carrier_month':cohorts,'weather_association':weather,'retrospective_rotations':chains}
    (out/'eda.json').write_text(json.dumps(full,indent=2,default=str,allow_nan=False))
    plt.rcParams.update({'font.family':'DejaVu Sans','axes.spines.top':False,'axes.spines.right':False,
        'axes.labelcolor':'#34443a','text.color':'#24352b','axes.titleweight':'bold', 'figure.facecolor':'#fafbf7','axes.facecolor':'#fafbf7'})
    findings=[]
    # Each figure has a machine-readable interpretation and the HTML repeats it.
    def save(name,question,denominator,finding,limitation,implication):
        plt.tight_layout();plt.savefig(out/f'{name}.png',dpi=170,bbox_inches='tight');plt.close()
        findings.append(dict(chart=f'{name}.png',question=question,denominator=denominator,finding=finding,
                             limitation=limitation,implication=implication,sql='sql/eda.sql'))
    plt.figure(figsize=(8,3.4))
    labels=['Missing dep delay','Missing arr delay','Cancelled','Diverted','Missing tail']
    vals=[summary[k] for k in ['missing_dep_delay','missing_arr_delay','cancelled','diverted','missing_tail']]
    plt.barh(labels,[100*v/n for v in vals],color='#5f8067');plt.xlabel('Share of reported flights (%)');plt.title('Missing outcomes are part of the disruption story')
    save('missingness','Which observations disappear from delay averages?',f'{n:,} reported flights touching four hubs.',
         f"{summary['missing_arr_delay']:,} arrival delays are missing ({100*summary['missing_arr_delay']/n:.2f}%); {summary['cancelled']:,} flights are cancelled. {summary['early_departures']:,} departures have negative delay.",
         'Missingness categories overlap. Delay observations exclude many cancelled/diverted flights, and this selected subnetwork is not the US system.',
         'Show cancellation rates alongside signed observed delays; never replace missing arrival delay with zero.')
    # Aggregate monthly counts in SQL rather than averaging cohort rates.
    month=rows(c,"SELECT extract(month from flight_date)::int AS month,count(*) AS n,count(*) FILTER(WHERE stressed) late,avg(cancelled) cancellation FROM flights WHERE origin IN ('ATL','ORD','DFW','DEN') GROUP BY 1 ORDER BY 1")
    plt.figure(figsize=(8,3.4));plt.plot([r['month'] for r in month],[100*r['late']/r['n'] for r in month],marker='o',color='#b36639',label='Delayed ≥15min or cancelled')
    plt.plot([r['month'] for r in month],[100*r['cancellation'] for r in month],marker='.',color='#597b99',label='Cancelled');plt.xticks(range(1,13));plt.xlabel('Reporting month, 2024');plt.ylabel('Scheduled departures (%)');plt.legend(frameon=False);plt.title('Seasonality changes the baseline')
    high=max(month,key=lambda r:r['late']/r['n']);low=min(month,key=lambda r:r['late']/r['n'])
    save('seasonality','How much does disruption change by month?',f"{sum(r['n'] for r in month):,} selected-carrier departures from four hubs, grouped by reporting month.",
         f"Month {high['month']} has {100*high['late']/high['n']:.1f}% disrupted departures versus {100*low['late']/low['n']:.1f}% in month {low['month']}.",
         'One reporting year and changing carrier/airport schedules cannot establish a stable long-run seasonal pattern.',
         'Evaluate against seasonal baselines and chronological holdouts; avoid random train/test splits.')
    groups=rows(c,"""SELECT origin,carrier,count(*) n,count(*) FILTER(WHERE stressed)*1.0/count(*) rate
                     FROM flights WHERE origin IN ('ATL','ORD','DFW','DEN') GROUP BY 1,2 ORDER BY 1,2""")
    hubs=sorted({r['origin'] for r in groups});carriers=sorted({r['carrier'] for r in groups})
    matrix=np.full((len(hubs),len(carriers)),np.nan)
    for r in groups: matrix[hubs.index(r['origin']),carriers.index(r['carrier'])]=r['rate']
    fig,ax=plt.subplots(figsize=(7,3.8));im=ax.imshow(matrix*100,cmap='YlOrBr',vmin=0)
    ax.set_xticks(range(len(carriers)),carriers);ax.set_yticks(range(len(hubs)),hubs)
    for i in range(len(hubs)):
        for j in range(len(carriers)):
            if np.isfinite(matrix[i,j]):ax.text(j,i,f'{matrix[i,j]*100:.1f}%',ha='center',va='center',color='white' if matrix[i,j]>np.nanmax(matrix)*.65 else '#24352b')
    fig.colorbar(im,ax=ax,label='Scheduled departures disrupted (%)');ax.set_title('Airport and carrier composition matters')
    lo=min(groups,key=lambda r:r['rate']);hi=max(groups,key=lambda r:r['rate'])
    save('cohorts','How much do airport/carrier cohorts differ?',f"{sum(r['n'] for r in groups):,} hub-origin scheduled departures; cells include their actual cohort schedules.",
         f"{hi['origin']}/{hi['carrier']} has {100*hi['rate']:.1f}% disruption (n={hi['n']:,}), versus {100*lo['rate']:.1f}% for {lo['origin']}/{lo['carrier']} (n={lo['n']:,}).",
         'These unadjusted groups differ in routes, schedule times and exposure. They do not establish carrier quality or causal airport effects.',
         'Compare within cohorts and include airport identity and schedule workload in the forecast; preserve the scope denominator.')
    if len(chains)>=2:
        ordered=sorted(chains,key=lambda r:r['following_departure_late_rate'])
        plt.figure(figsize=(8,3.4));plt.barh([r['cohort'].replace('previous arrival ','') for r in ordered],[100*r['following_departure_late_rate'] for r in ordered],color=['#708a68','#b66e43']);plt.xlabel('Following departure ≥15min late (%)');plt.title('Observed aircraft continuity carries a strong association')
        save('rotation_association','Do late inbound aircraft coincide with late following departures?',f"{sum(r['validated_links'] for r in chains):,} validated adjacent observed-tail hub-turn links with reported preceding arrival and following departure delays.",
             '; '.join(f"{r['cohort']}: {100*r['following_departure_late_rate']:.1f}% following departures late (n={r['validated_links']:,})" for r in chains)+'.',
             'Retrospective same-tail continuity omits flights at nonhub turns, overnight turns, missing tails, crews and passenger connections. Association is not a causal effect.',
             'Use validated chains for retrospective diagnosis; deployable forecasts must use only cutoff-available network state, not future aircraft assignments.')
    if weather:
        plt.figure(figsize=(8,3.4));plt.bar([r['cohort'] for r in weather],[100*r['disruption_rate'] for r in weather],color=['#78908f','#b18e66'][:len(weather)]);plt.ylabel('Disrupted scheduled exposures (%)');plt.title('Lagged weather is associated with future disruption')
        save('weather_association','Does recent visibility separate disruption risk?',f"{sum(r['airport_cutoffs'] for r in weather):,} airport cutoffs with accepted visibility, weather age ≤3h, and a complete target; overlapping two-hour exposures.",
             '; '.join(f"{r['cohort']}: {100*r['disruption_rate']:.1f}% disruption (n={r['airport_cutoffs']:,} cutoffs)" for r in weather)+'.',
             'Unadjusted association confounds seasonality, hubs and storms. Hourly two-hour windows overlap; NOAA publication time is assumed observation time plus one hour.',
             'Use recent weather as a candidate feature and verify added value on chronological holdouts before making operational claims.')
    (out/'findings.json').write_text(json.dumps(findings,indent=2))
    sections=[]
    for f in findings:
        entries=''.join(f'<p><b>{html.escape(k.title())}.</b> {html.escape(f[k])}</p>' for k in ['denominator','finding','limitation','implication'])
        sections.append(f'<section><h2>{html.escape(f["question"])}</h2><img src="{f["chart"]}" alt="{html.escape(f["question"])}">{entries}<a href="../sql/eda.sql">Generating SQL</a></section>')
    body=''.join(sections)
    doc=f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CASCADE | SQL investigation</title><style>body{{max-width:1000px;margin:50px auto;padding:0 24px;font:17px/1.6 system-ui;color:#24352b;background:#fafbf7}}h1{{font-size:44px;line-height:1.1}}section{{margin:70px 0}}img{{max-width:100%;height:auto}}a{{color:#386146}}pre{{overflow:auto;padding:20px;background:#e9eee3}}b{{font-weight:650}}</style><h1>CASCADE<br>What the reported network can tell us</h1><p>Rerunnable SQL EDA, 2024 · AA, DL, UA, WN · ATL, ORD, DFW, DEN</p><p>The extract includes all flights of these carriers touching any hub. It overrepresents major hubs and excludes regional affiliates reported under different carrier codes. Flight-delay averages condition on observed outcomes. No passenger counts, financial costs or crew connections are inferred.</p>{body}<h2>Delay distribution, retaining early values</h2><pre>{html.escape(json.dumps(tails[0],indent=2))}</pre><p>Quantiles and means use non-null reported signed delays. Missing arrival delay is never zero. The public data are final extracts and cannot reconstruct historical schedule revisions or publication latency.</p><a href="eda.json">Full SQL-derived results</a></html>'''
    (out/'investigation.html').write_text(doc)
    return full


def profile(c,root):
    root=Path(root);out=root/'artifacts';profiles=[]
    isolated=c is None
    if isolated:
        from cascade.warehouse import connect
        c=connect(root)
    maximum=c.execute('SELECT max(cutoff) FROM int_airport_hours').fetchone()[0]
    if isolated: c.close()
    for name in ['before','after']:
        if isolated: c=connect(root)
        query=(root/f'sql/query_{name}.sql').read_text().replace('int_airport_hours h',"(SELECT * FROM int_airport_hours WHERE cutoff >= TIMESTAMP '"+str(maximum)+"' - INTERVAL '7 days') h")
        plan=c.execute('EXPLAIN ANALYZE '+query).fetchall()
        (out/f'query_{name}_explain.txt').write_text('\n'.join(str(r) for r in plan))
        timings=[];result=None
        for i in range(3):
            path=out/f'query_{name}_profile.json'
            c.execute("SET enable_profiling='json'")
            c.execute("SET profiling_output=?",[str(path)])
            start=time.perf_counter();result=c.execute(query).fetchall();timings.append(time.perf_counter()-start)
            c.execute("SET enable_profiling='no_output'")
        raw=json.loads(path.read_text())
        digest=hashlib.sha256(repr(result).encode()).hexdigest()
        profiles.append({'name':name,'rows':len(result),'result_sha256':digest,'median_seconds':statistics.median(timings),'timings_seconds':timings,
            'peak_buffer_bytes':raw.get('system_peak_buffer_memory'),'peak_temp_disk_bytes':raw.get('system_peak_temp_dir_size'),'query':query})
        if isolated: c.close()
    if profiles[0]['result_sha256']!=profiles[1]['result_sha256']:
        raise AssertionError('Query optimization changed results')
    payload={'scope':'Last seven UTC days of grid; both joins see the complete weather history. Three warm repeated runs after EXPLAIN ANALYZE. Separate database connections per alternative; peak buffer memory is connection high-water mark including its EXPLAIN, not incremental allocation.',
             'hardware':platform.platform(),'duckdb_version':__import__('duckdb').__version__,'results':profiles,'identical_results':True,
             'speedup':profiles[0]['median_seconds']/max(profiles[1]['median_seconds'],1e-9)}
    (out/'query-benchmark.json').write_text(json.dumps(payload,indent=2,default=str))
    return payload
