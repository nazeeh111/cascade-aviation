'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const state = {data:null, day:0, cutoff:0, airport:null, timer:null, budget:'3'};
  const NS = 'http://www.w3.org/2000/svg';
  const num = value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value)) ? Number(value) : null;
  const fmt = (value, digits = 0) => num(value) === null ? '—' : Number(value).toLocaleString('en-US',{maximumFractionDigits:digits,minimumFractionDigits:digits});
  const pct = value => num(value) === null ? '—' : `${fmt(Number(value) * 100,1)}%`;
  const clock = value => { const d = new Date(value); return Number.isNaN(d.getTime()) ? String(value || '—') : `${String(d.getUTCHours()).padStart(2,'0')}:${String(d.getUTCMinutes()).padStart(2,'0')}`; };
  const dateLabel = value => { const d = new Date(`${String(value).slice(0,10)}T12:00:00Z`); return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric',timeZone:'UTC'}); };
  const text = (id, value) => { if ($(id)) $(id).textContent = value ?? '—'; };
  const array = value => Array.isArray(value) ? value : [];
  const svg = (tag, attrs={}, content) => { const el = document.createElementNS(NS,tag); Object.entries(attrs).forEach(([k,v])=>el.setAttribute(k,String(v))); if (content !== undefined) el.textContent=content; return el; };
  const element = (tag, className, content) => { const e=document.createElement(tag); if(className)e.className=className; if(content !== undefined)e.textContent=content; return e; };
  const safeURL = value => { if(typeof value !== 'string'||!value.trim())return null; try { const url=new URL(value,location.href); return ['http:','https:'].includes(url.protocol)?url.href:null; } catch{return null;} };
  const addLink = (parent,label,url) => { const target=safeURL(url); if(!target)return; const a=element('a','',label); a.href=target; if(new URL(target).origin !== location.origin){a.target='_blank';a.rel='noopener noreferrer';}parent.append(a); };
  const getDay = () => array(state.data?.days)[state.day];
  const getCutoff = () => array(getDay()?.cutoffs)[state.cutoff];
  const airportCode = a => a?.code || a?.airport || a?.iata || '';
  const getAirports = () => array(getCutoff()?.airports);
  const getSelected = () => getAirports().find(a=>airportCode(a)===state.airport) || getAirports()[0];
  const airportMeta = code => array(state.data?.airports).find(a=>airportCode(a)===code) || {code,name:code};
  const stress = a => num(a?.predicted_stress ?? a?.forecast ?? a?.prediction);
  const color = value => num(value) === null ? '#a7b49f' : Number(value)<.2 ? '#8eaf72' : Number(value)<.4 ? '#d5a35e' : Number(value)<.65 ? '#d77d46' : '#ae4b3f';
  const weighted = (rows, key) => { let sum=0,weight=0;rows.forEach(a=>{const value=num(a[key]);if(value===null)return;const w=Math.max(1,num(key==='observed_stress'?a.observed_flights:a.scheduled)??1);sum+=value*w;weight+=w;});return weight?sum/weight:null; };
  const asRows = value => Array.isArray(value) ? value : value&&typeof value==='object' ? Object.entries(value).map(([name,row])=>typeof row==='object'?{name,...row}:{name,simulated_delay_minutes:row}) : [];
  function normalizeData(data){
    if(!data||!Array.isArray(data.days)||!data.days.length)throw new Error('The replay export contains no held-out days. Rebuild the demo export and reload.');
    data.meta=data.meta||{};data.airports=array(data.airports);
    data.days.forEach(day=>{day.cutoffs=array(day.cutoffs);});
    if(!data.days.some(d=>d.cutoffs.length))throw new Error('The replay export contains no prediction cutoffs. Rebuild the demo export and reload.');
    return data;
  }
  function setup(){
    const meta=state.data.meta;
    const scope=Array.isArray(meta.scope)?meta.scope.join(' · '):meta.scope;
    text('scope-label',scope||`${meta.year||''} PUBLIC-DATA STUDY`);
    document.querySelectorAll('.horizon-label').forEach(e=>e.textContent=meta.horizon_hours??2);
    text('airport-stress-definition',meta.stress_definition||'Predicted departure disruption share');
    $('day-select').replaceChildren();
    state.data.days.forEach((day,i)=>{const o=element('option','',dateLabel(day.date));o.value=i;$('day-select').append(o);});
    $('day-select').addEventListener('change',e=>{stop();state.day=Number(e.target.value);state.cutoff=Math.min(state.cutoff,getDay().cutoffs.length-1);render();});
    $('cutoff-range').addEventListener('input',e=>{stop();state.cutoff=Number(e.target.value);render();});
    $('play-button').addEventListener('click',()=>{if(state.timer){stop();return;}if(getDay().cutoffs.length<2)return;state.timer=setInterval(()=>{state.cutoff=(state.cutoff+1)%getDay().cutoffs.length;render();},1600);$('play-button').replaceChildren(element('span','','Ⅱ'),document.createTextNode(' Pause replay'));$('play-button').setAttribute('aria-label','Pause historical replay');});
    $('budget-select').addEventListener('change',e=>{state.budget=e.target.value;renderScenarios();});
    renderModels();renderFindings();renderProvenance();
    $('application').hidden=false;$('load-state').hidden=true;
    render();
  }
  function stop(){if(state.timer){clearInterval(state.timer);state.timer=null;}$('play-button').replaceChildren(element('span','','▶'),document.createTextNode(' Play replay'));$('play-button').setAttribute('aria-label','Play historical replay');}
  function render(){
    const day=getDay(),cutoff=getCutoff();
    if(!cutoff){$('load-state').hidden=false;$('load-state').textContent='No prediction cutoffs are available for this day.';return;}
    $('load-state').hidden=true;
    const rows=getAirports();if(!rows.some(a=>airportCode(a)===state.airport))state.airport=airportCode(rows[0]);
    const cuts=day.cutoffs;$('day-select').value=String(state.day);$('cutoff-range').max=Math.max(0,cuts.length-1);$('cutoff-range').value=state.cutoff;$('cutoff-range').disabled=cuts.length<2;$('play-button').disabled=cuts.length<2;
    text('day-label',day.label||'Held-out replay');text('cutoff-output',`${clock(cutoff.timestamp)} UTC`);text('cutoff-start',`${clock(cuts[0]?.timestamp)} UTC`);text('cutoff-end',`${clock(cuts.at(-1)?.timestamp)} UTC`);text('map-cutoff',`${String(day.date).slice(0,10)} ${clock(cutoff.timestamp)} UTC`);
    const total=rows.reduce((s,a)=>s+(num(a.scheduled)??0),0);
    text('scheduled-value',fmt(total));text('observed-value',pct(weighted(rows,'observed_stress')));text('forecast-value',pct(weighted(rows,'predicted_stress')));text('actual-value',pct(weighted(rows,'actual_stress')));
    text('edge-note',`${fmt(array(cutoff.edges).length)} schedule-based links · line width reflects flight count`);
    renderMap();renderAirport();renderTimeline();renderScenarios();
  }
  function renderMap(){
    const map=$('network-map');map.setAttribute('viewBox',map.clientWidth<550?'260 90 470 300':'0 0 850 470');map.replaceChildren(svg('title',{id:'map-title'},'Airport disruption network'),svg('desc',{id:'map-desc'},'Airport circles show forecast disruption. Lines show scheduled connections at the selected historical cutoff. Use the airport buttons below for keyboard selection.'));
    const defs=svg('defs');const pattern=svg('pattern',{id:'map-grid',width:25,height:25,patternUnits:'userSpaceOnUse'});pattern.append(svg('circle',{cx:1,cy:1,r:.65,fill:'#b8c4ae'}));defs.append(pattern);map.append(defs,svg('rect',{width:850,height:470,fill:'url(#map-grid)'}));
    // Geographic context only: a deliberately simplified contiguous-US outline.
    const outline='M94 77 L155 92 L214 102 L278 108 L343 112 L418 115 L469 119 L505 113 L522 132 L554 133 L575 151 L594 150 L620 129 L643 131 L653 108 L675 108 L688 88 L698 97 L704 126 L687 144 L697 161 L676 180 L673 201 L660 214 L671 238 L650 252 L645 272 L627 288 L613 316 L599 342 L606 365 L597 382 L584 377 L570 347 L558 328 L522 322 L506 311 L483 319 L463 309 L429 310 L415 328 L397 327 L386 312 L372 312 L353 293 L332 290 L320 307 L310 315 L299 305 L290 292 L273 293 L267 280 L228 276 L199 271 L190 257 L179 257 L171 236 L154 231 L148 209 L130 196 L127 179 L112 167 L104 140 L98 124 Z';
    map.append(svg('path',{d:outline,fill:'#e6ecdc',stroke:'#c4d0b8','stroke-width':1.2}));
    const project=(lat,lon)=>({x:98+(Number(lon)+124.7)/58.1*600,y:85+(49.4-Number(lat))/24.8*300});
    // Restrained coordinate references, not claimed state boundaries.
    [-120,-110,-100,-90,-80].forEach(lon=>{const a=project(49,lon),b=project(25,lon);map.append(svg('path',{d:`M${a.x} ${a.y}L${b.x} ${b.y}`,stroke:'#d1dac6','stroke-width':.5,'stroke-dasharray':'3 5',fill:'none'}));});
    const rows=getAirports();const coordinates=new Map();state.data.airports.forEach(a=>{const lat=num(a.lat??a.latitude),lon=num(a.lon??a.longitude);if(lat!==null&&lon!==null)coordinates.set(airportCode(a),project(lat,lon));});
    const edges=array(getCutoff().edges);const maxFlights=Math.max(1,...edges.map(e=>num(e.flights)??1));
    edges.forEach(edge=>{const source=edge.source??edge.origin,target=edge.target??edge.dest;const a=coordinates.get(source),b=coordinates.get(target);if(!a||!b)return;const dx=b.x-a.x,dy=b.y-a.y;const path=svg('path',{d:`M${a.x},${a.y} Q${(a.x+b.x)/2-dy*.15},${(a.y+b.y)/2+dx*.15} ${b.x},${b.y}`,class:`map-edge ${source===state.airport||target===state.airport?'selected':''}`,'stroke-width':.65+Math.sqrt((num(edge.flights)??1)/maxFlights)*3});path.append(svg('title',{},`${source} → ${target}: ${fmt(edge.flights)} scheduled flights`));map.append(path);});
    rows.forEach(a=>{const code=airportCode(a),p=coordinates.get(code);if(!p)return;const selected=code===state.airport;const group=svg('g',{class:'svg-airport',tabindex:0,role:'button','aria-label':`Select ${code}, forecast ${pct(stress(a))}`,'aria-pressed':selected,transform:`translate(${p.x},${p.y})`});group.addEventListener('click',()=>selectAirport(code));group.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();selectAirport(code);}});if(selected)group.append(svg('circle',{r:25,class:'map-airport-halo'}));group.append(svg('circle',{r:16,fill:color(stress(a)),opacity:.18}),svg('circle',{r:selected?8:6.5,fill:color(stress(a)),stroke:'#fcfcf8','stroke-width':2.5,class:'airport-disc'}),svg('text',{x:15,y:-3},code),svg('text',{x:15,y:11,class:'airport-annotation'},pct(stress(a))));map.append(group);});
    $('airport-buttons').replaceChildren();rows.forEach(a=>{const code=airportCode(a),button=element('button','airport-button');button.type='button';button.setAttribute('aria-pressed',String(code===state.airport));const dot=element('i','dot');dot.style.background=color(stress(a));button.append(dot,document.createTextNode(code));button.addEventListener('click',()=>selectAirport(code));$('airport-buttons').append(button);});
  }
  function selectAirport(code){state.airport=code;renderMap();renderAirport();renderTimeline();renderScenarios();}
  function renderAirport(){
    const a=getSelected();if(!a)return;const code=airportCode(a),meta=airportMeta(code);text('airport-code',code);text('airport-name',meta.name||meta.airport_name||code);text('airport-predicted',pct(stress(a)));text('airport-scheduled',fmt(a.scheduled));text('airport-observed-flights',fmt(a.observed_flights));text('airport-observed',pct(a.observed_stress));text('airport-actual',pct(a.actual_stress));$('airport-meter').style.width=`${Math.max(0,Math.min(1,stress(a)??0))*100}%`;$('airport-meter').style.background=color(stress(a));
    text('airport-interval',num(a.lower)!==null&&num(a.upper)!==null?`Nominal 90% interval: ${pct(a.lower)}–${pct(a.upper)} · ${pct(state.data.meta.interval_coverage)} holdout coverage`:'Prediction interval unavailable');
    const weather=a.weather;if(!weather)text('airport-weather','No observation available at this cutoff');else if(typeof weather==='string')text('airport-weather',weather);else{const parts=[];if(num(weather.temperature_c??weather.temp_c)!==null)parts.push(`${fmt(weather.temperature_c??weather.temp_c,1)} °C`);if(num(weather.wind_speed_ms??weather.wind_ms)!==null)parts.push(`wind ${fmt(weather.wind_speed_ms??weather.wind_ms,1)} m/s`);if(num(weather.visibility_m)!==null)parts.push(`visibility ${fmt(weather.visibility_m/1000,1)} km`);if(weather.timestamp||weather.observed_at)parts.push(`observed ${clock(weather.timestamp||weather.observed_at)} UTC`);text('airport-weather',parts.join(' · ')||'Weather observation present; see source snapshot');}
  }
  function timelineRows(){
    const day=getDay(),cutoff=getCutoff();
    const explicit=array(cutoff.timeline).length?array(cutoff.timeline):array(day.timeline);
    if(explicit.length)return explicit.filter(r=>!r.airport||r.airport===state.airport).map(r=>({...r,observed:r.observed??r.observed_stress,predicted:r.predicted??r.predicted_stress,actual:r.actual??r.actual_stress}));
    return day.cutoffs.map(c=>{const a=array(c.airports).find(r=>airportCode(r)===state.airport)||{};return {timestamp:c.timestamp,observed:a.observed_stress,predicted:a.predicted_stress,actual:a.actual_stress};});
  }
  function renderTimeline(){
    text('timeline-airport',state.airport||'Network');const chart=$('timeline-chart');chart.replaceChildren();const rows=timelineRows();if(!rows.length){chart.append(svg('text',{x:40,y:80,fill:'#66736e','font-size':14},'No timeline is available in this export.'));return;}
    const W=Math.max(320,chart.clientWidth||1150),H=215,left=45,right=18,top=20,bottom=37;chart.setAttribute('viewBox',`0 0 ${W} ${H}`);const plotW=W-left-right,plotH=H-top-bottom;const max=Math.min(1,Math.max(.3,...rows.flatMap(r=>[num(r.observed),num(r.predicted),num(r.actual)]).filter(v=>v!==null))*1.15);
    const timestamps=rows.map(r=>new Date(r.timestamp).getTime());const validTime=timestamps.every(Number.isFinite)&&new Set(timestamps).size>1;const first=validTime?Math.min(...timestamps):0,last=validTime?Math.max(...timestamps):Math.max(1,rows.length-1);const x=(r,i)=>left+((validTime?timestamps[i]:i)-first)/(last-first)*plotW;const y=v=>top+(1-Math.min(max,Math.max(0,v))/max)*plotH;
    [0,.25,.5,.75,1].map(f=>max*f).forEach(v=>{const py=y(v);chart.append(svg('line',{x1:left,y1:py,x2:W-right,y2:py,stroke:'#dce2d4','stroke-width':.8}),svg('text',{x:left-9,y:py+3,'text-anchor':'end',fill:'#7c8978','font-family':'IBM Plex Mono, monospace','font-size':11},`${Math.round(v*100)}%`));});
    let cutoffX;if(validTime){const time=new Date(getCutoff().timestamp).getTime();cutoffX=left+(time-first)/(last-first)*plotW;}else cutoffX=x(rows[state.cutoff]||rows[0],state.cutoff);
    if(cutoffX>=left&&cutoffX<=W-right){chart.append(svg('rect',{x:cutoffX,y:top,width:W-right-cutoffX,height:plotH,fill:'#e8ecdf',opacity:.6}),svg('line',{x1:cutoffX,y1:top-3,x2:cutoffX,y2:H-bottom,stroke:'#849679','stroke-width':1,'stroke-dasharray':'3 4'}),svg('text',{x:Math.min(W-100,cutoffX+6),y:top-6,fill:'#6b8060','font-size':11,'font-family':'IBM Plex Mono, monospace'},'CUTOFF'));}
    const series=[['actual','#5982a4','5 4'],['observed','#376b51',null],['predicted','#d87a42',null]];
    series.forEach(([key,stroke,dash])=>{let d='',open=false;rows.forEach((r,i)=>{const value=num(r[key]);const knownAtCutoff=!validTime||timestamps[i]<=new Date(getCutoff().timestamp).getTime();if(value===null||(key!=='actual'&&!knownAtCutoff)){open=false;return;}d+=`${open?'L':'M'}${x(r,i).toFixed(2)} ${y(value).toFixed(2)} `;open=true;});if(!d)return;const path=svg('path',{d,fill:'none',stroke,'stroke-width':key==='predicted'?2.4:1.8,'stroke-linejoin':'round','stroke-linecap':'round'});if(dash)path.setAttribute('stroke-dasharray',dash);chart.append(path);rows.forEach((r,i)=>{if(num(r[key])===null||(key!=='actual'&&validTime&&timestamps[i]>new Date(getCutoff().timestamp).getTime()))return;const dot=svg('circle',{cx:x(r,i),cy:y(Number(r[key])),r:i===state.cutoff?3.5:2,fill:stroke,stroke:'#fcfcf8','stroke-width':1});dot.append(svg('title',{},`${clock(r.timestamp)} UTC · ${key}: ${pct(r[key])}`));chart.append(dot);});});
    const step=Math.max(1,Math.ceil(rows.length/(W<550?5:9)));rows.forEach((r,i)=>{if(i%step&&i!==rows.length-1)return;chart.append(svg('text',{x:x(r,i),y:H-13,'text-anchor':'middle',fill:'#74826e','font-family':'IBM Plex Mono, monospace','font-size':11},clock(r.timestamp)));});
    text('timeline-caption',`${state.airport||'Airport'} · ${state.data.meta.stress_definition||'Departure disruption share'} · Each forecast uses its own historical cutoff. Later outcomes are shown only for evaluation. All times UTC.`);
  }
  function getScenarios(){
    const cutoff=getCutoff(),airport=getSelected();let rows=asRows(airport?.scenarios);if(!rows.length)rows=asRows(cutoff?.scenarios);if(!rows.length)rows=asRows(getDay()?.scenarios);if(!rows.length)rows=asRows(state.data.scenarios);return rows;
  }
  function renderScenarios(){
    const all=getScenarios();const budgets=[...new Set(all.map(s=>num(s.budget??s.resources)).filter(v=>v!==null))].sort((a,b)=>a-b);const current=state.budget;$('budget-select').replaceChildren();const option=element('option','','Reported experiment');option.value='all';$('budget-select').append(option);budgets.forEach(b=>{const o=element('option','',`${fmt(b)} resource${b===1?'':'s'}`);o.value=String(b);$('budget-select').append(o);});state.budget=current==='all'||budgets.includes(Number(current))?current:'all';$('budget-select').value=state.budget;$('budget-select').disabled=budgets.length<2;
    const rows=all.filter(s=>state.budget==='all'||num(s.budget??s.resources)===Number(state.budget));const cards=$('scenario-cards');cards.replaceChildren();
    if(!rows.length){cards.append(element('p','empty-state','No recovery experiment is available for this cutoff. Forecast results above remain observational research.'));return;}
    const unique=rows.slice(0,6);unique.forEach((s,i)=>{const name=s.name||s.strategy||s.policy||`Scenario ${i+1}`;const card=element('article',`scenario-card ${/optim|forecast/i.test(name)?'recommended':''}`);card.append(element('span','mini-label',`SCENARIO ${String(i+1).padStart(2,'0')} · SIMULATED`),element('h3','',name));const value=s.simulated_delay_minutes??s.total_delay_minutes??s.delay_minutes??s.objective;const strong=element('strong','',fmt(value));if(num(value)!==null)strong.append(element('small','','min'));card.append(strong,element('p','scenario-unit',s.unit||'Simulated departure delay'));const allocation=s.allocation;if(allocation){const detail=typeof allocation==='string'?allocation:Object.entries(allocation).map(([k,v])=>`${k} ${v}`).join(' · ');card.append(element('p','scenario-detail',detail));}else card.append(element('p','scenario-detail',s.description||`${fmt(s.budget??s.resources)} hypothetical recovery resources`));const improvement=num(s.improvement_minutes??s.reduction_minutes??s.benefit_minutes);card.append(element('div','scenario-improvement',improvement===null?(s.note||'Compare under the stated replay assumptions'):`${fmt(improvement)} simulated minutes reduced vs. baseline`));cards.append(card);});
    text('scenario-assumptions',getCutoff()?.scenario_assumptions||state.data.meta.scenario_assumptions||'Observed schedules · bounded propagation · no passenger or crew model');text('scenario-limit',state.data.meta.scenario_limitation||'Simulation outcomes depend on replay assumptions and omit unobserved passenger, maintenance, crew, and airport-capacity constraints.');
  }
  function renderModels(){
    const rows=array(state.data.models);const tbody=$('model-table').querySelector('tbody');tbody.replaceChildren();if(!rows.length){const tr=element('tr'),td=element('td','','Model evaluation is not included in this export.');td.colSpan=4;tr.append(td);tbody.append(tr);return;}
    const maes=rows.map(r=>num(r.mae)).filter(v=>v!==null);const best=maes.length?Math.min(...maes):null;rows.forEach(r=>{const tr=element('tr',num(r.mae)===best?'best':'');const runtime=num(r.runtime_seconds??r.runtime_s);[r.name||r.model||'Unnamed model',fmt(r.mae,3),pct(r.severe_recall??r.severe_event_recall),runtime===null?'—':`${fmt(runtime,runtime<1?2:1)} s`].forEach(v=>tr.append(element('td','',v)));tbody.append(tr);});
    text('model-note',state.data.meta.model_note||`${rows.find(r=>r.split)?.split||'Chronological holdout'} · MAE is mean absolute error on the target scale. Full calibration, rolling-origin, and runtime evidence is linked in the model run.`);
  }
  function renderFindings(){
    const parent=$('findings');parent.replaceChildren();const rows=array(state.data.findings);if(!rows.length){parent.append(element('p','empty-state','No analytical findings are included in this export. Follow the research artifacts for the current evidence.'));return;}
    rows.forEach((f,i)=>{const article=element('article','finding');article.append(element('span','finding-number',`FINDING ${String(i+1).padStart(2,'0')}`),element('h3','',f.question||f.title||'Analytical finding'),element('p','finding-text',f.finding||f.summary||''));const dl=element('dl');[['Denominator',f.denominator],['Limitation',f.limitation],['Decision implication',f.implication||f.decision_implication]].forEach(([label,value])=>{if(value===null||value===undefined)return;const row=element('div');row.append(element('dt','',label),element('dd','',String(value)));dl.append(row);});article.append(dl);addLink(article,'Generating SQL ↗',f.sql||f.sql_url);parent.append(article);});
  }
  function renderProvenance(){
    const meta=state.data.meta;const dl=$('provenance-list');dl.replaceChildren();const scope=Array.isArray(meta.scope)?meta.scope.join(', '):meta.scope;
    [['Reporting year',meta.year],['Scope',scope],['Prediction horizon',`${meta.horizon_hours??2} hours`],['Model run',meta.run_id],['Source snapshot',meta.snapshot_id||meta.source_snapshot_id],['Target',meta.stress_definition]].forEach(([label,value])=>{if(value===null||value===undefined)return;const row=element('div');row.append(element('dt','',label),element('dd','',String(value)));dl.append(row);});
    const parent=$('provenance-links');parent.replaceChildren();const links=meta.sql_links;if(Array.isArray(links))links.forEach(l=>typeof l==='string'?addLink(parent,'Generating SQL ↗',l):addLink(parent,l.label||l.name||'Generating SQL ↗',l.url||l.href));else if(links&&typeof links==='object')Object.entries(links).forEach(([label,url])=>addLink(parent,label,url));addLink(parent,'Source snapshot ↗',meta.source_snapshot||meta.source_snapshot_url);addLink(parent,'Model run ↗',meta.model_run||meta.model_run_url);addLink(parent,'Source code ↗',meta.repository_url);addLink(parent,'Method + assumptions ↗',meta.methods_url||meta.simulation_url);
    const limits=$('limitations-list');limits.replaceChildren();const list=array(meta.limitations);if(list.length){const ul=element('ul');list.forEach(v=>ul.append(element('li','',String(v))));limits.append(ul);}else limits.append(element('p','','This is a scoped historical study. Source reporting, event-availability assumptions, selection bias, and missing operational constraints limit what can be concluded. Recovery benefits are simulated.'));
    if(meta.repository_url){const a=$('source-link'),url=safeURL(meta.repository_url);if(url){a.href=url;a.target='_blank';a.rel='noopener noreferrer';a.replaceChildren(document.createTextNode('Source + research '),element('span','','↗'));}}
  }
  window.addEventListener('resize',()=>{if(state.data){renderMap();renderTimeline();}});
  fetch('./data/demo.json',{cache:'no-cache'}).then(response=>{if(!response.ok)throw new Error(`Replay export could not be loaded (HTTP ${response.status}). Build the real-data export, then reload.`);return response.json();}).then(data=>{state.data=normalizeData(data);setup();}).catch(error=>{const node=$('load-state');node.classList.add('error');node.setAttribute('role','alert');node.textContent=error.message||'The real-data replay could not be loaded. Please reload or inspect the source export.';});
})();
