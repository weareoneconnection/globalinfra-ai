import Link from 'next/link';
import { api } from '@/lib/api';
import { RiskBadge } from '@/components/RiskBadge';

type Case = { id:string; title:string; type:string; risk:string; status:string; project_name:string; deadline:string; detected_issues:string[] };
export default async function Cases() {
  const rows = await api<Case[]>('/cases');
  return <><div className="header-row"><div><div className="eyebrow">Case intelligence</div><h2 className="page-title">Cases</h2><p className="page-subtitle">Every important field issue becomes a governed, evidence-backed unit of work.</p></div><button className="button">New Case</button></div><div className="card"><table className="table"><thead><tr><th>Case</th><th>Project</th><th>Risk</th><th>Issues</th><th>Deadline</th><th>Status</th></tr></thead><tbody>{rows.map(c=><tr key={c.id}><td><Link href={`/cases/${c.id}`}><b className="mono">{c.id}</b></Link><div className="muted" style={{marginTop:4}}>{c.title}</div></td><td>{c.project_name}<div className="muted">{c.type}</div></td><td><RiskBadge risk={c.risk}/></td><td>{c.detected_issues.length}</td><td>{c.deadline}</td><td><span className="badge">{c.status}</span></td></tr>)}</tbody></table></div></>;
}
