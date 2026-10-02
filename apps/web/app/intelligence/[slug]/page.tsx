import Link from 'next/link';
import { notFound } from 'next/navigation';
import { getLocale, getTranslations } from 'next-intl/server';
import { api } from '@/lib/api';
import { Domain } from '@/components/DomainCard';
import { getScenarios } from '@/lib/scenarios';

type Professional = { id:string; name:string; scope:string; intelligence_domain:string };

export default async function IntelligencePage({ params }:{params:Promise<{slug:string}>}) {
  const { slug } = await params;
  const [t, locale, domains, professional] = await Promise.all([
    getTranslations('Intelligence'), getLocale(), api<Domain[]>('/domains'), api<Professional[]>('/domains/professional')
  ]);
  const domain = domains.find(d=>d.id===slug); if(!domain) notFound(); const disciplines=professional.filter(p=>p.intelligence_domain===slug); const signals=getScenarios(locale, slug);
  return <>
    <div className={`domain-hero accent-${domain.accent}`}><div className="domain-hero-number">{domain.number}</div><div><div className="eyebrow">{t('eyebrow')}</div><h2 className="page-title">{domain.name}</h2><p className="page-subtitle">{domain.question}</p></div><div className="domain-score"><span>{domain.health}</span><small>{t('healthLabel')}</small><b>{domain.trend}</b></div></div>
    <div className="grid-3 domain-summary"><div className="card metric"><span className="label">{t('openSignals')}</span><strong className="metric-big">{domain.open}</strong><div className="delta amber-text">{domain.signal}</div></div><div className="card metric"><span className="label">{t('evidenceCoverage')}</span><strong className="metric-big">{t('evidenceCoverageValue')}</strong><div className="delta">{t('evidenceCoverageDelta')}</div></div><div className="card metric"><span className="label">{t('decisionsVerified')}</span><strong className="metric-big">{t('decisionsVerifiedValue')}</strong><div className="delta">{t('decisionsVerifiedDelta')}</div></div></div>
    <div className="grid-2 section">
      <div className="card"><div className="section-title"><div><span className="section-kicker">{t('liveKicker')}</span><h3>{t('liveTitle')}</h3></div><span>{t('liveSpan', { count: signals.length })}</span></div><div className="intel-list">{signals.map((s,i)=><div className="intel-row" key={s.title}><span className="signal-index">{String(i+1).padStart(2,'0')}</span><div><b>{s.title}</b><small>{s.meta}</small></div><span className="badge info">{s.status}</span></div>)}</div></div>
      <div className="card"><div className="section-title"><div><span className="section-kicker">{t('modelKicker')}</span><h3>{t('modelTitle')}</h3></div><span>{t('modelSpan', { count: disciplines.length })}</span></div><div className="discipline-grid">{disciplines.map(d=><div className="discipline" key={d.id}><span>{d.name.slice(0,2).toUpperCase()}</span><div><b>{d.name}</b><small>{d.scope}</small></div></div>)}</div></div>
    </div>
    <section className="section card"><div className="section-title"><div><span className="section-kicker">{t('capabilityKicker')}</span><h3>{t('capabilityTitle')}</h3></div><Link href="/agents">{t('capabilityLink')}</Link></div><div className="capability-cloud">{domain.capabilities.map((c,i)=><span key={c}><b>{String(i+1).padStart(2,'0')}</b>{c}</span>)}</div></section>
  </>;
}
