import Link from 'next/link';
import { notFound } from 'next/navigation';
import { api } from '@/lib/api';
import { Domain } from '@/components/DomainCard';

type Professional = { id:string; name:string; scope:string; intelligence_domain:string };

const scenarios:Record<string, {title:string;meta:string;status:string}[]> = {
  project:[{title:'Critical path recovery · Section C4',meta:'18-day variance · 3 linked work packages',status:'ACTION'},{title:'Forecast at completion exposure',meta:'+76M · driven by design change and acceleration',status:'REVIEW'},{title:'October progress cut-off',meta:'92% data completeness · 6 missing records',status:'OPEN'}],
  engineering:[{title:'Viaduct P47 crack assessment',meta:'4 drawings · 2 specifications · 1 NCR linked',status:'ACTIVE'},{title:'Station MEP interface conflict',meta:'BIM clash cluster · 3 disciplines',status:'REVIEW'},{title:'RFI aging above 14 days',meta:'12 RFIs · 4 affect critical works',status:'ACTION'}],
  delivery:[{title:'Long-lead switchgear exposure',meta:'Supplier forecast +21 days · systems package',status:'ACTION'},{title:'Night shift productivity',meta:'78% of plan · constrained access window',status:'WATCH'},{title:'Track slab workfront readiness',meta:'5 of 6 prerequisites complete',status:'READY'}],
  commercial:[{title:'Owner notice response window',meta:'32 hours remaining · evidence pack 84%',status:'URGENT'},{title:'Potential variation VO-027',meta:'Design change · time and cost linked',status:'REVIEW'},{title:'Payment certificate No. 18',meta:'92% substantiated · 3 exceptions',status:'OPEN'}],
  assurance:[{title:'Critical HSE corrective action',meta:'Working at height · due today',status:'URGENT'},{title:'NCR recurrence cluster',meta:'Concrete finishes · 6 related records',status:'ACTION'},{title:'Permit readiness',meta:'14 active · 2 expire within 30 days',status:'WATCH'}],
  resources:[{title:'Systems competency coverage',meta:'94% qualified · 11 gaps',status:'ACTION'},{title:'Crane utilization imbalance',meta:'Zone C at 91% · Zone A at 44%',status:'REVIEW'},{title:'Localized induction release',meta:'EN / BM / 中文 · revision approved',status:'READY'}],
  knowledge:[{title:'Contract evidence graph',meta:'1,284 nodes · 96% version traceability',status:'LIVE'},{title:'Lessons from pier defects',meta:'8 projects · 23 verified practices',status:'READY'},{title:'Unresolved terminology conflicts',meta:'4 defined terms across 3 languages',status:'REVIEW'}],
  assets:[{title:'Handover data completeness',meta:'67% · 1,248 assets registered',status:'ACTION'},{title:'Commissioning test packs',meta:'82 of 116 ready for execution',status:'OPEN'},{title:'Maintainability review',meta:'14 findings · 9 closed',status:'REVIEW'}],
};

export default async function IntelligencePage({ params }:{params:Promise<{slug:string}>}) {
  const { slug } = await params; const [domains, professional] = await Promise.all([api<Domain[]>('/domains'),api<Professional[]>('/domains/professional')]);
  const domain = domains.find(d=>d.id===slug); if(!domain) notFound(); const disciplines=professional.filter(p=>p.intelligence_domain===slug); const signals=scenarios[slug] || [];
  return <>
    <div className={`domain-hero accent-${domain.accent}`}><div className="domain-hero-number">{domain.number}</div><div><div className="eyebrow">INTELLIGENCE DOMAIN</div><h2 className="page-title">{domain.name}</h2><p className="page-subtitle">{domain.question}</p></div><div className="domain-score"><span>{domain.health}</span><small>DOMAIN HEALTH</small><b>{domain.trend}</b></div></div>
    <div className="grid-3 domain-summary"><div className="card metric"><span className="label">Open signals</span><strong className="metric-big">{domain.open}</strong><div className="delta amber-text">{domain.signal}</div></div><div className="card metric"><span className="label">Evidence coverage</span><strong className="metric-big">96.2%</strong><div className="delta">+2.8% this period</div></div><div className="card metric"><span className="label">Decisions verified</span><strong className="metric-big">148</strong><div className="delta">4 awaiting approval</div></div></div>
    <div className="grid-2 section">
      <div className="card"><div className="section-title"><div><span className="section-kicker">LIVE INTELLIGENCE</span><h3>Signals and decisions</h3></div><span>{signals.length} priority</span></div><div className="intel-list">{signals.map((s,i)=><div className="intel-row" key={s.title}><span className="signal-index">{String(i+1).padStart(2,'0')}</span><div><b>{s.title}</b><small>{s.meta}</small></div><span className="badge info">{s.status}</span></div>)}</div></div>
      <div className="card"><div className="section-title"><div><span className="section-kicker">DOMAIN MODEL</span><h3>Professional disciplines</h3></div><span>{disciplines.length} connected</span></div><div className="discipline-grid">{disciplines.map(d=><div className="discipline" key={d.id}><span>{d.name.slice(0,2).toUpperCase()}</span><div><b>{d.name}</b><small>{d.scope}</small></div></div>)}</div></div>
    </div>
    <section className="section card"><div className="section-title"><div><span className="section-kicker">CAPABILITY MAP</span><h3>Connected intelligence services</h3></div><Link href="/agents">View specialist agents</Link></div><div className="capability-cloud">{domain.capabilities.map((c,i)=><span key={c}><b>{String(i+1).padStart(2,'0')}</b>{c}</span>)}</div></section>
  </>;
}
