import { StrictMode, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import Markdown from 'react-markdown';
import registryData from './registry.json';
import help from './help.md?raw';
import type { Registry } from './Registry';
import type { RunStatus } from './RunStatus';
import type { RunEvent } from './RunEvent';
import type { IndexSnapshot } from './IndexSnapshot';
import './style.css';

import {validRegistry,validIndex} from './validators.js';
if (!validRegistry(registryData)) throw new Error('Invalid registry fixture');
const registry: Registry = registryData as unknown as Registry;
type Page = 'Pipeline'|'Quality'|'Optimise'|'Help';
const nav: Page[] = ['Pipeline','Quality','Optimise','Help'];

function App() {
 const [page,setPage]=useState<Page>('Pipeline');
 const [mode,setMode]=useState<'live'|'replay'>('live');
 const [dark,setDark]=useState(false);
 const [workflow,setWorkflow]=useState('demo');
 const [selected,setSelected]=useState('demo');
 const [csrf,setCsrf]=useState('');
 const [runs,setRuns]=useState<RunStatus[]>([]);
 const [events,setEvents]=useState<RunEvent[]>([]);
 const [index,setIndex]=useState<IndexSnapshot>({version:'v1',label:'index-level proxies',source:'pipeline',status:'unavailable',snapshots:[]});
 const [quality,setQuality]=useState<Record<string,unknown>>({});
 const [optimise,setOptimise]=useState<Record<string,unknown>>({});
 const [error,setError]=useState('');
 const [connectionError,setConnectionError]=useState('');
 const [traceAvailable,setTraceAvailable]=useState(false);
 const [trace,setTrace]=useState<unknown>(null);
 const [busy,setBusy]=useState(false);
 const active=runs[0];
 const definition=registry.workflows.find(w=>w.id===workflow)!;
 const node=registry.nodes.find(n=>n.id===selected);
 async function api(path:string,body?:unknown) {
  const response=await fetch('/api/v1/'+path,{method:body===undefined?'GET':'POST',
   headers:body===undefined?{}:{'Content-Type':'application/json','x-tresata-csrf':csrf},
   body:body===undefined?undefined:JSON.stringify(body)});
  if(!response.ok) { const data=await response.json(); throw new Error(typeof data.detail==='string'?data.detail:'Request rejected'); }
  return response.json();
 }
 useEffect(()=>{document.documentElement.dataset.theme=dark?'dark':'light'},[dark]);
 useEffect(()=>{
  if(mode!=='live') return;
  let alive=true;
  async function refresh() {
   try {
    const session=await api('session');
    const [list,snapshot,q,o,liveRegistry]=await Promise.all([api('runs'),api('index'),api('quality'),api('optimise'),api('registry')]);
    if(!validRegistry(liveRegistry)) throw new Error('Server registry schema rejected');
    if(JSON.stringify(liveRegistry)!==JSON.stringify(registryData)) throw new Error('Registry changed. Rebuild the website before running jobs.');
    if(!validIndex(snapshot)) throw new Error('Index schema rejected');
    const ev=list[0]?await api('runs/'+list[0].id+'/events'):[];
    if(alive){setCsrf(session.csrf_token);setTraceAvailable(session.internal_trace_available);setRuns(list);setEvents(ev);setIndex(snapshot);setQuality(q);setOptimise(o);setConnectionError('')}
   }catch(e){if(alive)setConnectionError((e as Error).message)}
  }
  void refresh(); const timer=setInterval(refresh,2000);
  return ()=>{alive=false;clearInterval(timer)};
 },[mode]);
 async function mutate(path:string,body:unknown={}) {
  setBusy(true);setError('');
  try { const result=await api(path,body);setRuns(old=>[result,...old.filter(r=>r.id!==result.id)]); }
  catch(e){setError((e as Error).message)} finally {setBusy(false)}
 }
 function exportIndex(){
  if(!validIndex(index)){setError('Export failed schema validation');return}
  const url=URL.createObjectURL(new Blob([JSON.stringify(index,null,2)],{type:'application/json'}));
  const a=document.createElement('a');a.href=url;a.download='tresata-index.json';a.click();URL.revokeObjectURL(url);
 }
 async function loadReplay(file:File|undefined){
  if(!file)return;
  try {const data=JSON.parse(await file.text());if(!validIndex(data))throw new Error('Replay schema rejected');
   setMode('replay');setIndex(data);setRuns([]);setEvents([]);setTrace(null);setError('');
  }catch(e){setError((e as Error).message)}
 }
 return <div className="shell">
  <a href="#main" className="skip">Skip to workspace</a>
  <aside className="sidebar"><a className="brand" href="#main"><span className="brand-mark">t</span> tresata<span className="small">RESEARCH WORKSPACE</span></a>
   <div className="workspace-label">WORKSPACE <span>01</span></div>
   <nav aria-label="Main navigation">{nav.map((p,i)=><button key={p} aria-current={page===p?'page':undefined} className={page===p?'active':''} onClick={()=>setPage(p)}><span className="nav-number">0{i+1}</span>{p}<span className="nav-arrow">↗</span></button>)}</nav>
   <div className="sidebar-foot"><span className="dot"/> PRIVATE WORKSTATION<p>Index-level earnings proxies.<br/>Evidence before inference.</p><button className="theme" onClick={()=>setDark(!dark)}>{dark?'Light appearance':'Dark appearance'}</button></div>
  </aside>
  <div className="content"><header><span>Research / <strong>{page}</strong></span><span className="session"><button className="mobile-theme" onClick={()=>setDark(!dark)}>{dark?'Light appearance':'Dark appearance'}</button><span className="dot"/> Local session <span className="avatar">OP</span></span></header>
   <main id="main"><div className="eyebrow">EARNINGS INTELLIGENCE / {mode.toUpperCase()}</div>
    <div className="title-row"><div><h1>{page==='Pipeline'?'From release to signal.':page==='Quality'?'Know what holds up.':page==='Optimise'?'Measure the work.':'A shared field guide.'}</h1><p className="intro">{page==='Pipeline'?'A traceable workflow for index-level earnings proxies.':page==='Quality'?'Coverage, review reasons and acceptance gates.':page==='Optimise'?'Observed calls and token use. Missing measurements stay unavailable.':'The same definitions used by the pipeline, controls and documentation.'}</p></div><span className={'mode-badge '+mode}>{mode==='live'?'LIVE CONTROLS':'REPLAY · NO EXECUTION'}</span></div>
    {(error||connectionError)&&<div role="alert" className="error">{error||connectionError}</div>}
    <section className="stats" aria-label="Workspace summary"><div><span>EXECUTION</span><strong>{mode==='replay'?'Replay':active?.status??'Ready'}</strong><small>{active?`${active.completed} of ${active.total} stages`:'No job running'}</small></div><div><span>INDEX SNAPSHOTS</span><strong>{index.snapshots.length.toString().padStart(2,'0')}</strong><small>{index.status==='unavailable'?'Unavailable':index.source==='synthetic'?'Synthetic verification':'Validated index view'}</small></div><div><span>QUALITY GATE</span><strong className="amber">Open</strong><small>Gate R0 requires review</small></div><div><span>VISIBILITY</span><strong>{trace?'Internal trace':'Index only'}</strong><small>{trace?'Session only · private':'Identifier-free exports'}</small></div></section>
    {page==='Pipeline'&&<>
     <section className="panel"><div className="panel-head"><div><span className="eyebrow">01 / WORKFLOW</span><h2>The pipeline</h2></div><label>Workflow<select value={workflow} onChange={e=>{setWorkflow(e.target.value);setSelected(registry.workflows.find(w=>w.id===e.target.value)!.nodes[0])}}>{registry.workflows.map(w=><option key={w.id} value={w.id}>{w.label}</option>)}</select></label></div>
      <div className="canvas" aria-label="Workflow graph"><div className="graph">{definition.nodes.map((id,i)=>{const n=registry.nodes.find(x=>x.id===id)!;return <div className="node-wrap" key={id}><button className={'node '+(selected===id?'selected':'')} aria-pressed={selected===id} onClick={()=>setSelected(id)}><span className="node-step">{String(i+1).padStart(2,'0')}<span>{active?.stage===id?'RUNNING':n.capability.toUpperCase()}</span></span><strong>{n.label}</strong><small>{n.inputs.join(', ')||'Start'} → {n.output}</small></button>{i<definition.nodes.length-1&&<span className="connector" aria-hidden="true">→</span>}</div>})}</div></div>
      <div className="run-bar"><span>{mode==='replay'?'Loaded artifacts · execution disabled':'Validated dependencies · server-side execution'}</span><div>{mode==='replay'?<button onClick={()=>{setMode('live');setTrace(null)}}>Return to live</button>:<button className="primary" disabled={busy||!csrf||!!active&&['running','queued'].includes(active.status)} onClick={()=>void mutate('runs',{version:'v1',workflow_id:workflow,submission_id:crypto.randomUUID()})}>{busy?'Starting…':'Run workflow'} <span>↗</span></button>}</div></div>
     </section>
     <div className="two-columns"><section className="panel inspector"><div className="eyebrow">02 / INSPECTOR</div><h2>{node?.label}</h2><p>{node?.help}</p><dl><dt>Input ports</dt><dd>{node?.inputs.join(', ')||'None'}</dd><dt>Output artifact</dt><dd>{node?.output}</dd><dt>Capability</dt><dd>{node?.capability}</dd></dl>{(node?.parameters??[]).length?<dl>{(node?.parameters??[]).map(p=><div key={p.config_path}><dt>{p.label}</dt><dd>{Array.isArray(p.value)?p.value.join(', '):p.value??'Unavailable'}</dd></div>)}</dl>:null}<p className="muted">Inspector execution checks server-owned upstream artifact fingerprints.</p><button disabled={mode!=='live'||busy||!csrf||!!active&&['running','queued'].includes(active.status)} onClick={()=>void mutate('runs',{version:'v1',workflow_id:workflow,submission_id:crypto.randomUUID(),node_id:selected,upstream_run_id:active?.id??null})}>Run selected stage</button></section>
      <section className="panel"><div className="eyebrow">03 / ACTIVITY</div><h2>Run events</h2>{events.length?<ol className="events">{events.slice(-8).map(e=><li key={e.sequence}><span>{e.stage||'Workflow'}</span><strong>{e.kind}</strong></li>)}</ol>:<div className="empty">Your next run starts here.<p>Stage progress is retained across restarts.</p></div>}{active&&mode==='live'&&<div className="actions">{['queued','running'].includes(active.status)?<button onClick={()=>void mutate('runs/'+active.id+'/cancel')}>Cancel between items</button>:['interrupted','failed','cancelled'].includes(active.status)?<button onClick={()=>void mutate('runs/'+active.id+'/resume')}>Resume with fingerprint check</button>:null}</div>}</section></div>
    </>}
    {page==='Quality'&&<section className="panel"><div className="eyebrow">COVERAGE & ACCEPTANCE</div><h2>Evidence quality</h2><p>Gate R0 remains failed until live validation and the separate human spot-check pass.</p><dl>{Object.entries(quality).map(([key,value])=><div key={key}><dt>{key.replaceAll('_',' ')}</dt><dd>{typeof value==='object'?JSON.stringify(value):String(value)}</dd></div>)}</dl><h3>Index observations</h3><p>{index.snapshots.length?JSON.stringify(index.snapshots[index.snapshots.length-1]):'No aggregate artifacts available. Run the pipeline or load a validated replay.'}</p></section>}
    {page==='Optimise'&&<section className="panel"><div className="eyebrow">MEASURED OPPORTUNITIES</div><h2>Request efficiency</h2><dl>{Object.entries(optimise).map(([key,value])=><div key={key}><dt>{key.replaceAll('_',' ')}</dt><dd>{value===null?'Unavailable':String(value)}</dd></div>)}</dl><p>Truncation retries consume requests. XBRL token savings do not by themselves demonstrate saved calls.</p></section>}
    {page==='Help'&&<article className="panel markdown"><Markdown>{help}</Markdown></article>}
    <section className="artifact-bar"><div><strong>Artifacts & visibility</strong><p>Exports contain the Index view. Replay files are validated before loading.</p></div><div className="actions"><button onClick={exportIndex}>Export Index JSON ↓</button><label className="file-button">Load replay<input type="file" accept="application/json,.json" onChange={e=>void loadReplay(e.target.files?.[0])}/></label></div></section>
    {traceAvailable&&mode==='live'&&<section className="panel"><label><input type="checkbox" checked={trace!==null} onChange={async e=>{if(!e.target.checked){setTrace(null);return}try{const response=await fetch('/api/v1/trace',{headers:{'x-tresata-trace':'session'}});if(!response.ok)throw new Error('Trace unavailable');setTrace(await response.json())}catch(e){setError((e as Error).message)}}}/> Internal trace for this session</label>{trace!==null&&<pre>{JSON.stringify(trace,null,2)}</pre>}</section>}
    <footer><span>TRESATA / PRERELEASE 0.1</span><span>Built for evidence. Human acceptance remains explicit.</span></footer>
   </main></div>
 </div>
}

createRoot(document.getElementById('root')!).render(<StrictMode><App/></StrictMode>);
