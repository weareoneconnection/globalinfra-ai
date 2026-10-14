'use client';

import Link from 'next/link';
import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react';
import { Twin3DViewer } from './Twin3DViewer';
import type { Control, Operations, TwinEvent, TwinObject } from './TwinWorkspace';

export type ShowcaseStep = { id:string;title:string;seconds:number;action:string };
export type ShowcaseManifest = { version:string;coverage:string;provenance:string;disclaimer:string;twin_ids:string[];artifacts:{type:string;url:string;sha256:string|null;bytes:number|null}[] };
export type ShowcaseModels = { versions:{id:string;version:string;format:string;status:string;checksum:string;object_count:number;change_summary:Record<string,number|string>}[];jobs:{id:string;status:string;progress:number;adapter:string}[];external_adapters:Record<string,string> };
export type ShowcaseSummary = { maturity:string;sync_status:string;objects:number;mapped_objects:number;average_health:number;active_events:number;online_sensors:number;schedule_variance_days:number;cost_exposure_m:number;commissioning_readiness:number };

type CopilotResult={answer:string;citations:{type:string;ref:string;source:string|string[]}[];confidence:number;grounded:boolean;requires_approval:boolean};
type LiveReading={sensor_id:string;twin_id:string;type:string;value:number;unit:string;status:string;sampled_at?:string};

const STEP_COPY:Record<string,{eyebrow:string;headline:string;script:string;proof:string}>={
  '8.1':{eyebrow:'NATIVE WEBGL · FEDERATED ID',headline:'One object. One stable Twin ID.',script:'先点选模型构件。几何、工程对象与事件证据通过同一 Twin ID 连接，它不只是一个 3D 浏览器。',proof:'GLTF 2.0 / IFC 4.3 / object picking'},
  '8.2':{eyebrow:'MODEL DATA PLANE · LINEAGE',headline:'Every revision remains explainable.',script:'这里展示模型版本、对象变化、校验值和转换作业。任何决策都可追溯到具体模型版本。',proof:'version diff / checksum / conversion job'},
  '8.3':{eyebrow:'ONE-CLICK PROJECT TWIN',headline:'Six interfaces from one project contract.',script:'没有真实项目也能完整演示：系统为每个项目生成 IFC、GLTF、3D Tiles、GeoJSON、WMS 和 IoT 实例，并保留来源声明。',proof:'6/6 downloadable synthetic interfaces'},
  '8.4':{eyebrow:'LIVE OPERATIONS · SSE',headline:'The twin is receiving live signals.',script:'传感器通过 SSE 持续推送，每条数据带 Sensor ID 和 Twin ID。模型、设备、告警与运维工单因此可以闭环。',proof:'live stream / threshold / asset binding'},
  '8.5':{eyebrow:'4D / 5D CONTROLS',headline:'Time and cost become spatial context.',script:'将计划进度、实际进度、延误天数和成本偏差映射到同一对象。项目团队看到的是“哪里为什么偏离”。',proof:'WBS / activity / schedule / forecast'},
  '8.6':{eyebrow:'GROUNDED TWIN COPILOT',headline:'AI answers with evidence, not guesses.',script:'Copilot 联合查询对象健康、进度、成本和事件，每个结论返回引用；高风险动作仍必须人工审批。',proof:'grounded response / citations / approval gate'},
  '8.7':{eyebrow:'DECISION CLOSE · AUDITABLE',headline:'From signal to governed decision.',script:'最后收口：一个项目数字孪生同时连接模型、进度、成本、IoT 和 AI；证据可追溯，责任边界清晰，现场决策可执行。',proof:'evidence receipt / human authority / full lifecycle'},
};

const formatClock=(seconds:number)=>`${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`;
const compactHash=(value:string)=>value?`${value.slice(0,8)}…${value.slice(-6)}`:'—';

function ModelPipeline({models}:{models:ShowcaseModels}){
  const latest=models.versions[0];
  return <div className="showcase-model-plane">
    <div className="showcase-pipeline"><span>IFC / BIM</span><i>→</i><span>NORMALIZE</span><i>→</i><span>GLTF + TILES</span><i>→</i><span>TWIN GRAPH</span></div>
    <div className="showcase-version-grid">{models.versions.slice(0,3).map((version,index)=><article className={index===0?'current':''} key={version.id}><header><span>{index===0?'CURRENT':'BASELINE'}</span><b>{version.status}</b></header><h3>{version.version}</h3><p>{version.object_count} objects · {version.format}</p><dl><div><dt>Added</dt><dd>+{version.change_summary.added||0}</dd></div><div><dt>Modified</dt><dd>{version.change_summary.modified||0}</dd></div><div><dt>Removed</dt><dd>{version.change_summary.removed||0}</dd></div></dl><small>SHA-256 {compactHash(version.checksum)}</small></article>)}</div>
    <div className="showcase-job"><span className="live-dot"/><b>{models.jobs[0]?.status||'READY'}</b><span>{models.jobs[0]?.adapter||'versioned model adapter'}</span><em>{models.jobs[0]?.progress??100}%</em><i><span style={{width:`${models.jobs[0]?.progress??100}%`}}/></i><small>{latest?`Evidence pinned to ${latest.version}`:'Awaiting model version'}</small></div>
  </div>;
}

function FormatPack({manifest,projectId}:{manifest:ShowcaseManifest;projectId:number}){
  return <div className="showcase-format-pack"><div className="format-pack-core"><span>PROJECT CONTRACT</span><strong>{manifest.coverage}</strong><b>interfaces ready</b><small>{manifest.version} · {manifest.twin_ids.length} stable Twin IDs</small></div><div className="format-pack-rays">{manifest.artifacts.map((artifact,index)=><a href={artifact.url} target="_blank" rel="noreferrer" key={artifact.type} style={{'--delay':`${index*80}ms`} as CSSProperties}><span>{artifact.type.replace('_',' ')}</span><b>{artifact.bytes?`${Math.max(1,Math.round(artifact.bytes/1024))} KB`:'LIVE'}</b><small>{artifact.sha256?compactHash(artifact.sha256):'stream endpoint'} ↗</small></a>)}</div><div className="showcase-pack-note"><span>{manifest.provenance}</span><p>{manifest.disclaimer}</p><Link href="/twin/generate">OPEN GENERATOR ↗</Link><a href={`/backend/twin/demo-pack/${projectId}/manifest`} target="_blank" rel="noreferrer">VERIFY MANIFEST ↗</a></div></div>;
}

function LiveTelemetry({projectId,initial,enabled}:{projectId:number;initial:Operations['sensors'];enabled:boolean}){
  const [readings,setReadings]=useState<LiveReading[]>(()=>initial.map(sensor=>({sensor_id:sensor.id,twin_id:sensor.twin_id,type:sensor.type,value:sensor.value,unit:sensor.unit,status:sensor.status})));
  const [sequence,setSequence]=useState(0); const [connected,setConnected]=useState(false);
  useEffect(()=>{if(!enabled)return;const source=new EventSource(`/backend/twin/telemetry/live/${projectId}?events=300`);const onTelemetry=(event:Event)=>{const data=JSON.parse((event as MessageEvent).data);setReadings(data.readings);setSequence(data.sequence);setConnected(true)};source.addEventListener('telemetry',onTelemetry);source.onerror=()=>setConnected(false);return()=>source.close()},[enabled,projectId]);
  return <div className="showcase-telemetry"><div className="telemetry-hero"><span className={`showcase-signal ${connected?'connected':''}`}><i/><i/><i/></span><div><span>EVENT STREAM</span><strong>{connected?'CONNECTED':'CONNECTING'}</strong><small>sequence #{String(sequence).padStart(4,'0')} · globalinfra/project/{projectId}</small></div></div><div className="telemetry-live-list">{readings.slice(0,5).map(row=><article key={row.sensor_id}><span className="sensor-pulse"/><div><b>{row.type}</b><small>{row.sensor_id}<br/>{row.twin_id}</small></div><strong>{row.value}<i>{row.unit}</i></strong><em className={row.status==='WARNING'?'warn':''}>{row.status}</em></article>)}</div><div className="stream-proof"><span>SSE</span><i/>→<span>SENSOR ID</span><i/>→<span>TWIN ID</span><i/>→<span>ALERT / CMMS</span></div></div>;
}

function ControlsStage({controls}:{controls:Control[]}){
  return <div className="showcase-controls"><div className="showcase-time-axis"><span>DESIGN</span><i/><span>PROCURE</span><i/><span>BUILD</span><i/><span>COMMISSION</span><i/><span>OPERATE</span></div><div className="showcase-control-grid">{controls.slice(0,4).map(control=>{const variance=Math.max(0,Math.min(100,control.actual_progress));return <article key={control.twin_id}><header><div><span>{control.wbs_code} · {control.activity_id}</span><b>{control.name}</b></div><strong className={control.schedule_variance_days<0?'risk':''}>{control.schedule_variance_days}d</strong></header><div className="showcase-bars"><span>PLANNED <b>{control.planned_progress}%</b><i><em style={{width:`${control.planned_progress}%`}}/></i></span><span>ACTUAL <b>{control.actual_progress}%</b><i><em className="actual" style={{width:`${variance}%`}}/></i></span></div><footer><span>Budget <b>{control.budget_m}M</b></span><span>Forecast <b>{control.forecast_m}M</b></span><span>Variance <b className={control.cost_variance_m>0?'risk':''}>+{control.cost_variance_m}M</b></span></footer></article>})}</div></div>;
}

function GroundedCopilot({projectId,enabled}:{projectId:number;enabled:boolean}){
  const [result,setResult]=useState<CopilotResult|null>(null);const [loading,setLoading]=useState(false);const requested=useRef(false);
  const ask=useCallback(async()=>{if(requested.current)return;requested.current=true;setLoading(true);try{const response=await fetch('/backend/twin/copilot/query',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({project_id:projectId,question:'Which asset has the highest delivery risk, why, and what evidence supports the conclusion?'})});if(!response.ok)throw new Error(String(response.status));setResult(await response.json())}catch{requested.current=false;setResult(null)}finally{setLoading(false)}},[projectId]);
  useEffect(()=>{if(enabled)void ask()},[ask,enabled]);
  return <div className="showcase-copilot"><div className="copilot-query"><span>PROJECT DIRECTOR</span><p>Which asset has the highest delivery risk, why, and what evidence supports the conclusion?</p></div><div className="copilot-route"><span>TWIN GRAPH</span><i/>→<span>4D / 5D</span><i/>→<span>EVENTS</span><i/>→<span>MODEL VERSION</span></div><div className={`copilot-response ${loading?'loading':''}`} aria-live="polite"><header><span className="live-dot"/><b>{loading?'GROUNDING ACROSS PROJECT DATA…':result?.grounded?'GROUNDED ANSWER':'READY TO QUERY'}</b>{result?<em>{Math.round(result.confidence*100)}% confidence</em>:null}</header>{result?<><p>{result.answer}</p><div className="showcase-citations">{result.citations.map(citation=><span key={`${citation.type}-${citation.ref}`}><b>{citation.type}</b><strong>{citation.ref}</strong><small>{Array.isArray(citation.source)?citation.source.join(' · '):citation.source}</small></span>)}</div><footer>⚠ HUMAN APPROVAL REQUIRED BEFORE EXECUTION</footer></>:<p>{loading?'Resolving stable Twin IDs, latest events and model lineage.':'Copilot will run automatically when this scene starts.'}</p>}</div></div>;
}

function DecisionClose({summary,manifest,models}:{summary:ShowcaseSummary;manifest:ShowcaseManifest;models:ShowcaseModels}){
  const checks=[['MODEL',`${summary.mapped_objects}/${summary.objects} mapped`],['LIVE DATA',`${summary.online_sensors} sensors online`],['CONTROL',`${summary.schedule_variance_days}d / +${summary.cost_exposure_m}M`],['AI',`${models.versions.length} version citations`],['HANDOVER',`${summary.commissioning_readiness}% ready`],['INTERFACES',`${manifest.coverage} verified`]];
  return <div className="showcase-close"><div className="close-statement"><span>GLOBALINFRA AI</span><h2>From fragmented project data<br/>to an operational decision twin.</h2><p>DESIGN → CONSTRUCTION → COMMISSIONING → OPERATIONS</p></div><div className="evidence-receipt"><header><span>EVIDENCE RECEIPT</span><b>VERIFIED</b></header>{checks.map(([label,value])=><div key={label}><span>{label}</span><b>{value}</b><i>✓</i></div>)}<footer><span>Authority boundary</span><strong>AI RECOMMENDS · HUMAN APPROVES</strong><small>Synthetic competition dataset · auditable demo chain</small></footer></div></div>;
}

function ShowcaseStage({active,projectId,objects,events,controls,operations,manifest,models,summary}:{active:number;projectId:number;objects:TwinObject[];events:TwinEvent[];controls:Control[];operations:Operations;manifest:ShowcaseManifest;models:ShowcaseModels;summary:ShowcaseSummary}){
  if(active===0)return <div className="showcase-3d"><Twin3DViewer url={manifest.artifacts.find(item=>item.type==='GLTF')?.url||`/backend/twin/demo-pack/${projectId}/model.gltf`} objects={objects} onSelect={()=>undefined}/><div className="showcase-event-proof"><span>LINKED EVIDENCE</span>{events.slice(0,3).map(event=><article key={event.id}><i className={`risk-dot ${event.severity.toLowerCase()}`}/><div><b>{event.title}</b><small>{event.id} · {event.twin_id}</small></div><em>{event.status}</em></article>)}</div></div>;
  if(active===1)return <ModelPipeline models={models}/>;
  if(active===2)return <FormatPack manifest={manifest} projectId={projectId}/>;
  if(active===3)return <LiveTelemetry projectId={projectId} initial={operations.sensors} enabled/>;
  if(active===4)return <ControlsStage controls={controls}/>;
  if(active===5)return <GroundedCopilot projectId={projectId} enabled/>;
  return <DecisionClose summary={summary} manifest={manifest} models={models}/>;
}

export function ShowcasePlayer({projectId,projectCode,projectName,steps,objects,events,controls,operations,manifest,models,summary}:{projectId:number;projectCode:string;projectName:string;steps:ShowcaseStep[];objects:TwinObject[];events:TwinEvent[];controls:Control[];operations:Operations;manifest:ShowcaseManifest;models:ShowcaseModels;summary:ShowcaseSummary}){
  const total=steps.reduce((sum,step)=>sum+step.seconds,0);const [elapsed,setElapsed]=useState(0);const [playing,setPlaying]=useState(false);const rootRef=useRef<HTMLDivElement>(null);
  let active=steps.length-1;let boundary=0;for(let index=0;index<steps.length;index++){boundary+=steps[index].seconds;if(elapsed<boundary){active=index;break}}
  const step=steps[active];const stepStart=steps.slice(0,active).reduce((sum,item)=>sum+item.seconds,0);const stepElapsed=Math.min(step.seconds,Math.max(0,elapsed-stepStart));const progress=total?Math.min(100,(elapsed/total)*100):0;const copy=STEP_COPY[step.id]||{eyebrow:step.id,headline:step.title,script:step.action,proof:''};
  useEffect(()=>{if(!playing)return;const started=performance.now()-elapsed*1000;const timer=window.setInterval(()=>{const next=Math.min(total,Math.floor((performance.now()-started)/1000));setElapsed(next);if(next>=total)setPlaying(false)},250);return()=>window.clearInterval(timer)},[elapsed,playing,total]);
  useEffect(()=>{const onKey=(event:KeyboardEvent)=>{if(event.target instanceof HTMLInputElement||event.target instanceof HTMLTextAreaElement)return;if(event.code==='Space'){event.preventDefault();setPlaying(value=>!value)}if(event.key==='ArrowRight'){event.preventDefault();setPlaying(false);setElapsed(Math.min(total,stepStart+step.seconds))}if(event.key==='ArrowLeft'){event.preventDefault();setPlaying(false);setElapsed(stepStart>0?Math.max(0,stepStart-1):0)}};window.addEventListener('keydown',onKey);return()=>window.removeEventListener('keydown',onKey)},[step.seconds,stepStart,total]);
  const jump=(index:number)=>{setPlaying(false);setElapsed(steps.slice(0,index).reduce((sum,item)=>sum+item.seconds,0))};
  const toggle=()=>{if(elapsed>=total)setElapsed(0);setPlaying(value=>!value)};
  const fullscreen=()=>{if(document.fullscreenElement)void document.exitFullscreen();else void rootRef.current?.requestFullscreen()};
  return <div className="showcase-player" ref={rootRef}>
    <header className="showcase-header"><div className="showcase-brand"><span>GLOBALINFRA AI · 180-SECOND JURY MODE</span><h1>{projectCode}<small>{projectName}</small></h1></div><div className="showcase-status"><span><i className={playing?'live-dot':''}/>{playing?'AUTO PLAYING':'PRESENTATION READY'}</span><b>{step.id} / 8.7</b></div><strong>{formatClock(Math.max(0,total-elapsed))}</strong></header>
    <div className="showcase-progress"><i style={{width:`${progress}%`}}/><span style={{left:`${progress}%`}}/></div>
    <main><section className="showcase-scene"><div className="showcase-scene-title"><div><span>{copy.eyebrow}</span><h2>{copy.headline}</h2></div><em>{String(stepElapsed).padStart(2,'0')} / {step.seconds}s</em></div><div className="showcase-stage"><ShowcaseStage active={active} projectId={projectId} objects={objects} events={events} controls={controls} operations={operations} manifest={manifest} models={models} summary={summary}/></div><div className="showcase-script"><span>讲解词</span><p>{copy.script}</p><b>{copy.proof}</b></div></section><nav className="showcase-steps" aria-label="180 second demo scenes"><div><span>7 SCENES</span><b>180 SECONDS</b></div><ol>{steps.map((item,index)=><li className={index===active?'active':index<active?'done':''} key={item.id}><button onClick={()=>jump(index)} aria-current={index===active?'step':undefined}><span>{item.id}</span><b>{item.title}</b><small>{item.seconds}s</small><i/></button></li>)}</ol><div className="showcase-shortcuts"><span>SPACE</span> play / pause <span>← →</span> scenes</div></nav></main>
    <footer className="showcase-footer"><button className="button showcase-play" onClick={toggle}>{playing?'Ⅱ  PAUSE':elapsed>=total?'↻  REPLAY 180s':'▶  START / RESUME'}</button><button className="showcase-icon-button" onClick={()=>jump(Math.max(0,active-1))} aria-label="Previous scene">← PREV</button><button className="showcase-icon-button" onClick={()=>jump(Math.min(steps.length-1,active+1))} aria-label="Next scene">NEXT →</button><button className="showcase-icon-button" onClick={()=>setElapsed(0)}>↺ RESET</button><button className="showcase-icon-button" onClick={fullscreen}>⛶ FULLSCREEN</button><Link className="button secondary" href={`/twin?project_id=${projectId}`}>OPEN WORKSPACE ↗</Link><span>SYNTHETIC DEMO DATA · NO CUSTOMER DATA</span></footer>
  </div>;
}
