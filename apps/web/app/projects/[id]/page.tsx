import Link from 'next/link';
import { api } from '@/lib/api';
import { RiskBadge } from '@/components/RiskBadge';
import { LifecycleRail } from '@/components/LifecycleRail';
import { DomainCard, Domain } from '@/components/DomainCard';

type Project = { id:number; code:string; name:string; country_name:string; country_code:string; domain:string; region:string; status:string; risk_level:string; languages:string[]; phase:string; progress:number; budget:number; committed:number; forecast:number; schedule_variance:number; next_gate:string; gate_date:string };
type Case = { id:string; title:string; type:string; risk:string; status:string; deadline:string };
type Stage = { id:string; name:string; short:string; order:number };
type Workspace = { project:Project; lifecycle:Stage[]; domains:Domain[]; cases:Case[]; trusted_action:string[] };

export default async function ProjectWorkspace({ params }: { params:Promise<{id:string}> }) {
  const { id } = await params; const w = await api<Workspace>(`/projects/${id}/workspace`); const p = w.project;
  return <>
    <div className="project-banner">
      <div className="country-code large">{p.country_code}</div><div className="project-banner-main"><div className="eyebrow">{p.region} · {p.domain} · {p.code}</div><h2 className="page-title">{p.name}</h2><p>{p.country_name} · {p.languages.join(' / ')}</p></div>
      <div className="project-banner-status"><RiskBadge risk={p.risk_level}/><span className="badge ok">{p.status}</span></div>
    </div>
    <div className="grid-4 project-kpis">
      <div className="card metric"><span className="label">Overall progress</span><strong className="metric-big">{p.progress}%</strong><div className="health-track"><span style={{width:`${p.progress}%`}} /></div></div>
      <div className="card metric"><span className="label">Approved budget</span><strong className="metric-big">${(p.budget/1000).toFixed(2)}B</strong><div className="delta">${p.committed}M committed</div></div>
      <div className="card metric"><span className="label">Forecast at completion</span><strong className="metric-big">${(p.forecast/1000).toFixed(2)}B</strong><div className="delta amber-text">{p.forecast > p.budget ? `+${p.forecast-p.budget}M exposure` : 'Within baseline'}</div></div>
      <div className="card metric"><span className="label">Schedule variance</span><strong className="metric-big danger-text">{p.schedule_variance} days</strong><div className="delta">Recovery scenario active</div></div>
    </div>
    <section className="section card lifecycle-card"><div className="section-title"><div><span className="section-kicker">PROJECT LIFECYCLE</span><h3>Stage-gate readiness</h3></div><span>Next: {p.next_gate} · {p.gate_date}</span></div><LifecycleRail stages={w.lifecycle} active={p.phase} /></section>
    <section className="section"><div className="outside-title"><div><span className="section-kicker">PROJECT OPERATING SYSTEM</span><h3>Connected domain performance</h3></div><span>Health combines risk, latency, evidence and decision status</span></div><div className="domain-grid">{w.domains.map(d=><DomainCard key={d.id} domain={d} compact />)}</div></section>
    <div className="grid-2 section">
      <div className="card"><div className="section-title"><div><span className="section-kicker">PRIORITY CASES</span><h3>Cross-domain work queue</h3></div><Link href="/cases">View all</Link></div><div className="signal-list">{w.cases.length ? w.cases.map((c,i)=><Link className="signal-row" href={`/cases/${c.id}`} key={c.id}><span className="signal-index">{String(i+1).padStart(2,'0')}</span><span className="signal-main"><b>{c.title}</b><small>{c.type} · {c.status}</small></span><span className="signal-deadline">{c.deadline}</span><RiskBadge risk={c.risk}/></Link>) : <div className="empty-state">No active cases in this workspace.</div>}</div></div>
      <div className="card"><div className="section-title"><div><span className="section-kicker">NEXT 30 DAYS</span><h3>Integrated readiness</h3></div><span>6 gates</span></div><div className="readiness-list">{[['Systems integration readiness','Engineering · Interfaces','82%'],['Long-lead switchgear delivery','Procurement · Logistics','68%'],['Viaduct inspection release','Quality · Construction','91%'],['Monthly payment application','Commercial · Cost','76%']].map((r,i)=><div className="readiness-row" key={r[0]}><span>{String(i+1).padStart(2,'0')}</span><div><b>{r[0]}</b><small>{r[1]}</small></div><strong>{r[2]}</strong></div>)}</div></div>
    </div>
  </>;
}
