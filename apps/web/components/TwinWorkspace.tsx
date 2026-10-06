'use client';

import { useState, type CSSProperties } from 'react';

export type TwinObject = { id:string; parent_id:string|null; object_type:string; name:string; lifecycle_stage:string; status:string; health_score:number; progress:number; geometry_ref:string|null; location:Record<string,string|number>; properties:Record<string,string|number> };
export type TwinEvent = { id:string; twin_id:string; event_type:string; severity:string; title:string; domain:string; status:string; evidence_refs:string[] };
export type Control = { twin_id:string; name:string; wbs_code:string; activity_id:string; planned_progress:number; actual_progress:number; schedule_variance_days:number; budget_m:number; forecast_m:number; cost_variance_m:number };
export type Commissioning = { id:string; twin_id:string; asset:string; system:string; test_pack:string; stage:string; punch_open:number; document_completeness:number; readiness:number };
export type Operations = { sensors:{id:string;twin_id:string;asset:string;type:string;unit:string;value:number;status:string;warning:number;critical:number}[]; maintenance:{id:string;twin_id:string;asset:string;work_type:string;status:string;priority:string;description:string;due_at:string}[] };
export type Scenario = { id:string; name:string; type:string; status:string; assumptions:Record<string,string|number|boolean>; result:Record<string,string|number>; requires_approval:boolean };
export type TwinAgent = { id:string; name:string; scope:string };

type Labels = { tabs:string[]; selectAsset:string; health:string; progress:string; linkedEvents:string; noEvents:string; planned:string; actual:string; scheduleVariance:string; costExposure:string; readiness:string; documents:string; openPunch:string; telemetry:string; maintenance:string; warning:string; runScenario:string; running:string; approvalRequired:string; simulationComplete:string; simulationFailed:string; evidence:string; sceneHint:string; live:string };

export function TwinWorkspace({ objects, events, controls, commissioning, operations, scenarios, agents, labels }: { objects:TwinObject[];events:TwinEvent[];controls:Control[];commissioning:Commissioning[];operations:Operations;scenarios:Scenario[];agents:TwinAgent[];labels:Labels }) {
  const [tab,setTab]=useState(0);
  const [selected,setSelected]=useState('TWIN-MYRAIL-V12-P47');
  const [running,setRunning]=useState('');
  const [result,setResult]=useState<Record<string,string|number>|null>(null);
  const [error,setError]=useState('');
  const current=objects.find(x=>x.id===selected)||objects[0];
  const currentEvents=events.filter(x=>x.twin_id===current?.id);
  const children=objects.filter(x=>x.parent_id===current?.id);

  async function simulate(id:string){
    setRunning(id);setResult(null);setError('');
    try{
      const response=await fetch(`/backend/twin/scenarios/${id}/run`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({adjustment_percent:10})});
      if(!response.ok) throw new Error(String(response.status));
      const data=await response.json();setResult(data.result);
    }catch{
      setError(labels.simulationFailed);
    }finally{setRunning('');}
  }

  return <div className="twin-workspace">
    <div className="twin-tabs" role="tablist">{labels.tabs.map((label,index)=><button role="tab" aria-selected={tab===index} className={tab===index?'active':''} onClick={()=>setTab(index)} key={label}>{String(index+1).padStart(2,'0')} · {label}</button>)}</div>
    {tab===0&&<div className="twin-spatial-grid">
      <div className="twin-scene card">
        <div className="scene-toolbar"><span><i className="live-dot"/>{labels.live} · IFC 4.3 / 3D Tiles</span><small>{labels.sceneHint}</small></div>
        <div className="scene-sky"><div className="scene-grid"/>
          <div className="rail-line"/><div className="station-block"><b>ST-04</b><span>HVAC</span></div>
          {objects.filter(x=>['ASSET','COMPONENT'].includes(x.object_type)).map((object,index)=><button key={object.id} onClick={()=>setSelected(object.id)} className={`twin-node n${index+1} ${selected===object.id?'selected':''} ${object.health_score<70?'risk':''}`} title={object.name}><span>{object.object_type}</span><b>{object.name}</b><i>{Math.round(object.health_score)}</i></button>)}
          <div className="scene-axis">N ↑</div>
        </div>
        <div className="scene-legend"><span><i className="lg-ok"/>Normal</span><span><i className="lg-watch"/>Watch</span><span><i className="lg-risk"/>Risk / Hold</span></div>
      </div>
      {current&&<aside className="card twin-inspector"><div className="twin-id">{current.id}</div><h3>{current.name}</h3><div className="inspector-status"><span className={`badge ${current.health_score<70?'danger':current.health_score<85?'warn':'ok'}`}>{current.status}</span><span>{current.lifecycle_stage}</span></div>
        <div className="twin-gauges"><div><span>{labels.health}</span><b>{current.health_score}</b><i><em style={{width:`${current.health_score}%`}}/></i></div><div><span>{labels.progress}</span><b>{current.progress}%</b><i><em style={{width:`${current.progress}%`}}/></i></div></div>
        <div className="twin-properties">{Object.entries({...current.location,...current.properties}).slice(0,7).map(([k,v])=><div key={k}><span>{k}</span><b>{String(v)}</b></div>)}</div>
        {children.length>0&&<div className="child-assets">{children.map(x=><button onClick={()=>setSelected(x.id)} key={x.id}>{x.name}<span>›</span></button>)}</div>}
        <h4>{labels.linkedEvents}</h4>{currentEvents.length?currentEvents.map(e=><div className="twin-alert" key={e.id}><span className={`risk-dot ${e.severity.toLowerCase()}`}/><div><b>{e.title}</b><small>{e.id} · {e.evidence_refs.join(' · ')}</small></div></div>):<p className="muted">{labels.noEvents}</p>}
      </aside>}
    </div>}
    {tab===1&&<div className="twin-data-grid">{controls.map(x=><div className="card twin-control" key={x.twin_id}><div className="twin-card-head"><div><span>{x.wbs_code} · {x.activity_id}</span><h3>{x.name}</h3></div><b className={x.schedule_variance_days<0?'negative':'positive'}>{x.schedule_variance_days}d</b></div><div className="comparison"><div><span>{labels.planned}</span><b>{x.planned_progress}%</b><i><em style={{width:`${x.planned_progress}%`}}/></i></div><div><span>{labels.actual}</span><b>{x.actual_progress}%</b><i><em style={{width:`${x.actual_progress}%`}}/></i></div></div><div className="cost-row"><span>{labels.scheduleVariance}<b>{x.schedule_variance_days} d</b></span><span>{labels.costExposure}<b>{x.cost_variance_m>0?'+':''}{x.cost_variance_m}M</b></span></div></div>)}</div>}
    {tab===2&&<div className="twin-data-grid">{commissioning.map(x=><div className="card twin-control" key={x.id}><div className="twin-card-head"><div><span>{x.test_pack}</span><h3>{x.system}</h3><small>{x.asset}</small></div><b>{x.readiness}%</b></div><div className="readiness-ring" style={{'--score':`${x.readiness*3.6}deg`} as CSSProperties}><span>{x.readiness}</span></div><div className="cost-row"><span>{labels.openPunch}<b>{x.punch_open}</b></span><span>{labels.documents}<b>{x.document_completeness}%</b></span><span>{labels.readiness}<b>{x.stage}</b></span></div></div>)}</div>}
    {tab===3&&<div className="grid-2"><div className="card"><div className="section-title"><div><span className="section-kicker">IoT / BMS / SCADA</span><h3>{labels.telemetry}</h3></div></div>{operations.sensors.map(s=><div className="telemetry-row" key={s.id}><span className={`sensor-pulse ${s.status==='WARNING'?'warning':''}`}/><div><b>{s.asset}</b><small>{s.type} · {s.id}</small></div><strong>{s.value} <i>{s.unit}</i></strong><span className={`badge ${s.status==='WARNING'?'warn':'ok'}`}>{s.status}</span></div>)}</div><div className="card"><div className="section-title"><div><span className="section-kicker">CMMS</span><h3>{labels.maintenance}</h3></div></div>{operations.maintenance.map(m=><div className="maintenance-row" key={m.id}><span className="step-num">{m.priority.slice(0,1)}</span><div><b>{m.description}</b><small>{m.asset} · {m.work_type} · {new Date(m.due_at).toLocaleDateString()}</small></div><span className="badge info">{m.status}</span></div>)}</div></div>}
    {tab===4&&<><div className="twin-data-grid">{scenarios.map(s=><div className="card scenario-card" key={s.id}><div className="twin-card-head"><div><span>{s.type} · {s.id}</span><h3>{s.name}</h3></div><span className="badge warn">{s.requires_approval?labels.approvalRequired:s.status}</span></div><div className="scenario-assumptions">{Object.entries(s.assumptions).map(([k,v])=><span key={k}>{k}<b>{String(v)}</b></span>)}</div><div className="scenario-result">{Object.entries(s.result).map(([k,v])=><div key={k}><span>{k}</span><b>{String(v)}</b></div>)}</div><button className="button" disabled={!!running} onClick={()=>simulate(s.id)}>{running===s.id?labels.running:labels.runScenario}</button></div>)}</div>{error&&<p role="alert" className="simulation-error">{error}</p>}{result&&<div className="card simulation-output" aria-live="polite"><span className="section-kicker">AI SIMULATION · VERIFIED INPUTS</span><h3>{labels.simulationComplete}</h3><div>{Object.entries(result).map(([k,v])=><span key={k}>{k}<b>{String(v)}</b></span>)}</div><p>✓ {labels.evidence}: Twin object state · 4D/5D baseline · Latest telemetry · Scenario assumptions</p></div>}</>}
    {tab===5&&<div className="agent-grid">{agents.map((agent,index)=><div className="agent-card" key={agent.id}><div className="agent-card-head"><span className="agent-icon">T{index+1}</span><i className="risk-dot"/></div><h4>{agent.name}</h4><p>{agent.scope}</p><div className="tool-list"><span>TWIN GRAPH</span><span>EVIDENCE</span><span>POLICY</span></div></div>)}</div>}
  </div>;
}
