import Link from 'next/link';
import { getTranslations } from 'next-intl/server';
import { api } from '@/lib/api';
import { RiskBadge } from '@/components/RiskBadge';
import { LifecycleRail } from '@/components/LifecycleRail';
import { DomainCard, Domain } from '@/components/DomainCard';

type Project = { id:number; code:string; name:string; country_name:string; country_code:string; domain:string; region:string; status:string; risk_level:string; languages:string[]; phase:string; progress:number; budget:number; committed:number; forecast:number; schedule_variance:number; next_gate:string; gate_date:string };
type Case = { id:string; title:string; type:string; risk:string; status:string; deadline:string };
type Stage = { id:string; name:string; short:string; order:number };
type Workspace = { project:Project; lifecycle:Stage[]; domains:Domain[]; cases:Case[]; trusted_action:string[] };
type ReadinessItem = { title:string; meta:string; value:string };

export default async function ProjectWorkspace({ params }: { params:Promise<{id:string}> }) {
  const { id } = await params;
  const t = await getTranslations('ProjectDetail');
  const w = await api<Workspace>(`/projects/${id}/workspace`); const p = w.project;
  const readinessList = t.raw('readinessList') as ReadinessItem[];
  return <>
    <div className="project-banner">
      <div className="country-code large">{p.country_code}</div><div className="project-banner-main"><div className="eyebrow">{p.region} · {p.domain} · {p.code}</div><h2 className="page-title">{p.name}</h2><p>{p.country_name} · {p.languages.join(' / ')}</p></div>
      <div className="project-banner-status"><RiskBadge risk={p.risk_level}/><span className="badge ok">{p.status}</span></div>
    </div>
    <div className="grid-4 project-kpis">
      <div className="card metric"><span className="label">{t('progress')}</span><strong className="metric-big">{p.progress}%</strong><div className="health-track"><span style={{width:`${p.progress}%`}} /></div></div>
      <div className="card metric"><span className="label">{t('budget')}</span><strong className="metric-big">${(p.budget/1000).toFixed(2)}B</strong><div className="delta">{t('budgetDelta', { committed: p.committed })}</div></div>
      <div className="card metric"><span className="label">{t('forecastTitle')}</span><strong className="metric-big">${(p.forecast/1000).toFixed(2)}B</strong><div className="delta amber-text">{p.forecast > p.budget ? t('forecastDeltaOver', { exposure: p.forecast-p.budget }) : t('forecastDeltaOk')}</div></div>
      <div className="card metric"><span className="label">{t('variance')}</span><strong className="metric-big danger-text">{p.schedule_variance} days</strong><div className="delta">{t('varianceDelta')}</div></div>
    </div>
    <section className="section card lifecycle-card"><div className="section-title"><div><span className="section-kicker">{t('lifecycleKicker')}</span><h3>{t('lifecycleTitle')}</h3></div><span>{t('lifecycleSpan', { gate: p.next_gate, date: p.gate_date })}</span></div><LifecycleRail stages={w.lifecycle} active={p.phase} /></section>
    <section className="section"><div className="outside-title"><div><span className="section-kicker">{t('osKicker')}</span><h3>{t('osTitle')}</h3></div><span>{t('osSpan')}</span></div><div className="domain-grid">{w.domains.map(d=><DomainCard key={d.id} domain={d} compact />)}</div></section>
    <div className="grid-2 section">
      <div className="card"><div className="section-title"><div><span className="section-kicker">{t('casesKicker')}</span><h3>{t('casesTitle')}</h3></div><Link href="/cases">{t('casesLink')}</Link></div><div className="signal-list">{w.cases.length ? w.cases.map((c,i)=><Link className="signal-row" href={`/cases/${c.id}`} key={c.id}><span className="signal-index">{String(i+1).padStart(2,'0')}</span><span className="signal-main"><b>{c.title}</b><small>{c.type} · {c.status}</small></span><span className="signal-deadline">{c.deadline}</span><RiskBadge risk={c.risk}/></Link>) : <div className="empty-state">{t('noCases')}</div>}</div></div>
      <div className="card"><div className="section-title"><div><span className="section-kicker">{t('readinessKicker')}</span><h3>{t('readinessTitle')}</h3></div><span>{t('readinessSpan')}</span></div><div className="readiness-list">{readinessList.map((r,i)=><div className="readiness-row" key={r.title}><span>{String(i+1).padStart(2,'0')}</span><div><b>{r.title}</b><small>{r.meta}</small></div><strong>{r.value}</strong></div>)}</div></div>
    </div>
  </>;
}
