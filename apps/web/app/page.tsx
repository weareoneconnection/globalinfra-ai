import Link from 'next/link';
import { api } from '@/lib/api';
import { Metric } from '@/components/Metric';
import { RiskBadge } from '@/components/RiskBadge';
import { LifecycleRail } from '@/components/LifecycleRail';
import { DomainCard, Domain } from '@/components/DomainCard';

type Summary = { projects:number; countries:number; open_cases:number; critical_risks:number; pending_approvals:number; verified_decisions:number };
type Case = { id:string; title:string; type:string; risk:string; status:string; project_name:string; deadline:string };
type Stage = { id:string; name:string; short:string; order:number };

export default async function Page() {
  const [summary, cases, domains, lifecycle] = await Promise.all([
    api<Summary>('/dashboard/summary'), api<Case[]>('/cases'), api<Domain[]>('/domains'), api<Stage[]>('/lifecycle')
  ]);
  return <>
    <div className="command-hero">
      <div><div className="eyebrow">Global command center · Portfolio live</div><h2 className="page-title">From every project event to a trusted action.</h2><p className="page-subtitle">跨生命周期、跨专业、跨组织理解工程事件，把进度、技术、商务、风险与资产数据连接成可执行的项目智能。</p></div>
      <div className="hero-actions"><Link className="button secondary" href="/architecture">View digital thread</Link><Link className="button" href="/cases/CASE-2026-0182">Open priority case</Link></div>
    </div>
    <div className="grid-4 command-metrics">
      <Metric label="Active Portfolio" value={summary.projects} delta={`${summary.countries} countries · 3 data planes`} />
      <Metric label="Open Cross-domain Cases" value={summary.open_cases} delta={`${summary.critical_risks} high / critical`} />
      <Metric label="Pending Decisions" value={summary.pending_approvals || 3} delta="Human approval gates active" />
      <Metric label="Verified Decisions" value={summary.verified_decisions} delta="96.2% evidence traceability" />
    </div>
    <section className="section card lifecycle-card">
      <div className="section-title"><div><span className="section-kicker">FULL LIFECYCLE</span><h3>Portfolio delivery horizon</h3></div><span>3 projects distributed across active phases</span></div>
      <LifecycleRail stages={lifecycle} active="construction" />
    </section>
    <section className="section">
      <div className="outside-title"><div><span className="section-kicker">8 INTELLIGENCE DOMAINS</span><h3>Connected project health</h3></div><Link href="/architecture">Explore all 24 disciplines</Link></div>
      <div className="domain-grid">{domains.map(domain => <DomainCard domain={domain} key={domain.id} compact />)}</div>
    </section>
    <div className="grid-2 section command-lower">
      <div className="card">
        <div className="section-title"><div><span className="section-kicker">CROSS-DOMAIN SIGNALS</span><h3>Events requiring coordination</h3></div><Link href="/cases">All cases</Link></div>
        <div className="signal-list">{cases.slice(0,4).map((c,i)=><Link className="signal-row" href={`/cases/${c.id}`} key={c.id}>
          <span className={`signal-index s${i+1}`}>{String(i+1).padStart(2,'0')}</span><span className="signal-main"><b>{c.title}</b><small>{c.project_name} · {c.type}</small></span><span className="signal-deadline">{c.deadline}</span><RiskBadge risk={c.risk}/>
        </Link>)}</div>
      </div>
      <div className="card trusted-card">
        <div className="section-title"><div><span className="section-kicker">TRUSTED EXECUTION</span><h3>One operating model across every domain</h3></div><span>Governed AI</span></div>
        <div className="trusted-flow">{['Project Event','Case','Evidence','Decision','Action','Verification'].map((item,index)=><div className="trusted-step" key={item}><span>{String(index+1).padStart(2,'0')}</span><b>{item}</b>{index < 5 && <i />}</div>)}</div>
        <div className="team-assembly"><span className="pulse-ring">AI</span><div><small>CASE ROUTER · TEAM ASSEMBLY</small><b>Quality + Engineering + Contract + Planning</b><p>Dynamic specialist team assembled for NCR-2026-084</p></div><span className="badge ok">ACTIVE</span></div>
      </div>
    </div>
  </>;
}
