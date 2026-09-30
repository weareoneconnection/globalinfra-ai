import { api } from '@/lib/api';
import { RiskBadge } from '@/components/RiskBadge';
import { RunAnalysisButton } from '@/components/RunAnalysisButton';

type Detail = {
  id:string; title:string; description:string; type:string; risk:string; status:string; deadline:string; project_name:string; source_language:string; detected_issues:string[];
  evidence:{id:number;title:string;source_type:string;source_ref:string;excerpt:string;confidence:number;verified:boolean}[];
  agent_runs:{id:number;agent:string;status:string;summary:string;duration_ms:number}[];
  verification?:{status:string;citation_score:number;evidence_score:number;consistency_score:number;findings:string[]} | null;
};
export default async function CasePage({ params }: { params: Promise<{ id:string }> }) {
  const { id } = await params; const c = await api<Detail>(`/cases/${id}`);
  return <><div className="header-row"><div><div className="eyebrow">{c.project_name}</div><h2 className="page-title">{c.id}</h2><p className="page-subtitle">{c.title}</p></div><div style={{display:'flex',gap:10,alignItems:'center'}}><RiskBadge risk={c.risk}/><RunAnalysisButton caseId={c.id}/></div></div>
  <div className="grid-2">
    <div className="card card-pad"><h3 style={{marginTop:0}}>Case intelligence</h3><div className="kv"><span className="k">Status</span><span>{c.status}</span></div><div className="kv"><span className="k">Type</span><span>{c.type}</span></div><div className="kv"><span className="k">Response deadline</span><span>{c.deadline}</span></div><div className="kv"><span className="k">Source language</span><span>{c.source_language}</span></div><div className="kv"><span className="k">Description</span><span>{c.description}</span></div><div className="kv"><span className="k">Detected issues</span><span>{c.detected_issues.join(' · ')}</span></div></div>
    <div className="card card-pad"><h3 style={{marginTop:0}}>Verification gate</h3>{c.verification ? <><div className="kv"><span className="k">Status</span><span className={`badge ${c.verification.status==='PASS'?'ok':'medium'}`}>{c.verification.status}</span></div><div className="kv"><span className="k">Citation score</span><span>{Math.round(c.verification.citation_score*100)}%</span></div><div className="kv"><span className="k">Evidence score</span><span>{Math.round(c.verification.evidence_score*100)}%</span></div><div className="kv"><span className="k">Semantic consistency</span><span>{Math.round(c.verification.consistency_score*100)}%</span></div><div className="kv"><span className="k">Findings</span><span>{c.verification.findings.join(' · ')}</span></div></> : <p className="muted">No verification record yet. Run analysis to generate an evidence-backed candidate action.</p>}</div>
  </div>
  <div className="grid-2 section">
    <div className="card"><div className="section-title"><h3>Specialist agent runs</h3><span>{c.agent_runs.length} runs</span></div><div className="card-pad workflow">{c.agent_runs.length ? c.agent_runs.map((a,i)=><div className="step" key={a.id}><div className="step-num">{String(i+1).padStart(2,'0')}</div><div><h4>{a.agent}</h4><p>{a.summary}</p></div><span className="badge ok">{a.status} · {a.duration_ms}ms</span></div>) : <p className="muted">Run analysis to activate Intake, Contract, Engineering, Standards, Planning and Verification agents.</p>}</div></div>
    <div className="card"><div className="section-title"><h3>Evidence chain</h3><span>{c.evidence.length} items</span></div><div className="card-pad">{c.evidence.length ? c.evidence.map(e=><div className="evidence" key={e.id}><div style={{display:'flex',justifyContent:'space-between',gap:10}}><h4>{e.title}</h4><span className={`badge ${e.verified?'ok':'medium'}`}>{Math.round(e.confidence*100)}%</span></div><p>{e.excerpt}</p><p className="mono" style={{marginTop:8}}>{e.source_type} · {e.source_ref}</p></div>) : <p className="muted">No evidence links yet.</p>}</div></div>
  </div>
  </>;
}
