import { api } from '@/lib/api';
import { RiskBadge } from '@/components/RiskBadge';
import Link from 'next/link';

type Project = { id:number; code:string; name:string; country_code:string; country_name:string; domain:string; region:string; status:string; risk_level:string; languages:string[]; phase:string; progress:number; budget:number; forecast:number; schedule_variance:number; next_gate:string };
export default async function Projects() {
  const rows = await api<Project[]>('/projects');
  return <><div className="header-row"><div><div className="eyebrow">Global portfolio · 3 active programs</div><h2 className="page-title">Project portfolio</h2><p className="page-subtitle">From tender to operations, each workspace connects scope, schedule, cost, risk and asset outcomes.</p></div><button className="button secondary">Portfolio scenario</button></div>
  <div className="portfolio-grid">{rows.map(p=><Link className="project-card" href={`/projects/${p.id}`} key={p.id}>
    <div className="project-card-top"><span className="country-code">{p.country_code}</span><RiskBadge risk={p.risk_level}/></div>
    <div className="eyebrow">{p.region} · {p.domain} · {p.phase}</div><h3>{p.name}</h3><span className="mono muted">{p.code}</span>
    <div className="project-progress"><div><span>Overall progress</span><b>{p.progress}%</b></div><div className="health-track"><span style={{width:`${p.progress}%`}} /></div></div>
    <div className="project-stats"><div><small>Forecast</small><b>${(p.forecast/1000).toFixed(2)}B</b></div><div><small>Schedule</small><b className={p.schedule_variance < 0 ? 'danger-text' : 'good-text'}>{p.schedule_variance > 0 ? '+' : ''}{p.schedule_variance}d</b></div><div><small>Next gate</small><b>{p.next_gate}</b></div></div>
    <div className="project-card-foot"><span>{p.languages.join(' · ')}</span><b>Open workspace</b></div>
  </Link>)}</div></>;
}
