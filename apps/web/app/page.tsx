import Link from 'next/link';
import { getTranslations } from 'next-intl/server';
import { api } from '@/lib/api';
import { Metric } from '@/components/Metric';
import { RiskBadge } from '@/components/RiskBadge';
import { LifecycleRail } from '@/components/LifecycleRail';
import { DomainCard, Domain } from '@/components/DomainCard';

type Summary = { projects:number; countries:number; open_cases:number; critical_risks:number; pending_approvals:number; verified_decisions:number };
type Case = { id:string; title:string; type:string; risk:string; status:string; project_name:string; deadline:string };
type Stage = { id:string; name:string; short:string; order:number };

export default async function Page() {
  const t = await getTranslations('Home');
  const [summary, cases, domains, lifecycle] = await Promise.all([
    api<Summary>('/dashboard/summary'), api<Case[]>('/cases'), api<Domain[]>('/domains'), api<Stage[]>('/lifecycle')
  ]);
  const trustedFlow = t.raw('trustedFlow') as string[];
  return <>
    <div className="command-hero">
      <div><div className="eyebrow">{t('eyebrow')}</div><h2 className="page-title">{t('title')}</h2><p className="page-subtitle">{t('subtitle')}</p></div>
      <div className="hero-actions"><Link className="button secondary" href="/architecture">{t('viewThread')}</Link><Link className="button" href="/cases/CASE-2026-0182">{t('openCase')}</Link></div>
    </div>
    <div className="grid-4 command-metrics">
      <Metric label={t('metricPortfolio')} value={summary.projects} delta={t('metricPortfolioDelta', { countries: summary.countries })} />
      <Metric label={t('metricCases')} value={summary.open_cases} delta={t('metricCasesDelta', { critical: summary.critical_risks })} />
      <Metric label={t('metricApprovals')} value={summary.pending_approvals || 3} delta={t('metricApprovalsDelta')} />
      <Metric label={t('metricVerified')} value={summary.verified_decisions} delta={t('metricVerifiedDelta')} />
    </div>
    <section className="section card lifecycle-card">
      <div className="section-title"><div><span className="section-kicker">{t('lifecycleKicker')}</span><h3>{t('lifecycleTitle')}</h3></div><span>{t('lifecycleSpan')}</span></div>
      <LifecycleRail stages={lifecycle} active="construction" />
    </section>
    <section className="section">
      <div className="outside-title"><div><span className="section-kicker">{t('domainsKicker')}</span><h3>{t('domainsTitle')}</h3></div><Link href="/architecture">{t('domainsLink')}</Link></div>
      <div className="domain-grid">{domains.map(domain => <DomainCard domain={domain} key={domain.id} compact />)}</div>
    </section>
    <div className="grid-2 section command-lower">
      <div className="card">
        <div className="section-title"><div><span className="section-kicker">{t('signalsKicker')}</span><h3>{t('signalsTitle')}</h3></div><Link href="/cases">{t('signalsLink')}</Link></div>
        <div className="signal-list">{cases.slice(0,4).map((c,i)=><Link className="signal-row" href={`/cases/${c.id}`} key={c.id}>
          <span className={`signal-index s${i+1}`}>{String(i+1).padStart(2,'0')}</span><span className="signal-main"><b>{c.title}</b><small>{c.project_name} · {c.type}</small></span><span className="signal-deadline">{c.deadline}</span><RiskBadge risk={c.risk}/>
        </Link>)}</div>
      </div>
      <div className="card trusted-card">
        <div className="section-title"><div><span className="section-kicker">{t('trustedKicker')}</span><h3>{t('trustedTitle')}</h3></div><span>{t('trustedSpan')}</span></div>
        <div className="trusted-flow">{trustedFlow.map((item,index)=><div className="trusted-step" key={item}><span>{String(index+1).padStart(2,'0')}</span><b>{item}</b>{index < 5 && <i />}</div>)}</div>
        <div className="team-assembly"><span className="pulse-ring">AI</span><div><small>{t('teamLabel')}</small><b>{t('teamTitle')}</b><p>{t('teamDesc')}</p></div><span className="badge ok">{t('teamBadge')}</span></div>
      </div>
    </div>
  </>;
}
