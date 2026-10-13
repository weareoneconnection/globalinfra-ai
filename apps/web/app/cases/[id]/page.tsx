import { getTranslations } from 'next-intl/server';
import { api } from '@/lib/api';
import { RiskBadge } from '@/components/RiskBadge';
import { RunAnalysisButton } from '@/components/RunAnalysisButton';
import { GovernedActionControls } from '@/components/GovernedActionControls';

type Detail = {
  id:string; title:string; description:string; type:string; risk:string; status:string; deadline:string; project_name:string; source_language:string; detected_issues:string[];
  evidence:{id:number;title:string;source_type:string;source_ref:string;excerpt:string;confidence:number;verified:boolean}[];
  agent_runs:{id:number;agent:string;status:string;summary:string;duration_ms:number}[];
  verification?:{status:string;citation_score:number;evidence_score:number;consistency_score:number;findings:string[]} | null;
  action?:{id:string;action_type:string;status:string;approval_id:number;evidence_refs:string[];artifact_ref:string|null} | null;
  execution_receipt?:{status:string;artifact_ref:string|null;output_digest:string|null} | null;
  verification_receipt?:{status:string;findings:string[];artifact_ref:string|null;artifact_digest:string|null} | null;
};
export default async function CasePage({ params }: { params: Promise<{ id:string }> }) {
  const { id } = await params;
  const t = await getTranslations('CaseDetail');
  const c = await api<Detail>(`/cases/${id}`);
  return <><div className="header-row"><div><div className="eyebrow">{c.project_name}</div><h2 className="page-title">{c.id}</h2><p className="page-subtitle">{c.title}</p></div><div style={{display:'flex',gap:10,alignItems:'center'}}><RiskBadge risk={c.risk}/><RunAnalysisButton caseId={c.id}/></div></div>
  <div className="grid-2">
    <div className="card card-pad"><h3 style={{marginTop:0}}>{t('intelligenceTitle')}</h3><div className="kv"><span className="k">{t('labelStatus')}</span><span>{c.status}</span></div><div className="kv"><span className="k">{t('labelType')}</span><span>{c.type}</span></div><div className="kv"><span className="k">{t('labelDeadline')}</span><span>{c.deadline}</span></div><div className="kv"><span className="k">{t('labelSourceLanguage')}</span><span>{c.source_language}</span></div><div className="kv"><span className="k">{t('labelDescription')}</span><span>{c.description}</span></div><div className="kv"><span className="k">{t('labelIssues')}</span><span>{c.detected_issues.join(' · ')}</span></div></div>
    <div className="card card-pad"><h3 style={{marginTop:0}}>{t('verificationTitle')}</h3>{c.verification ? <><div className="kv"><span className="k">{t('labelStatus')}</span><span className={`badge ${c.verification.status==='PASS'?'ok':'medium'}`}>{c.verification.status}</span></div><div className="kv"><span className="k">{t('labelCitationScore')}</span><span>{Math.round(c.verification.citation_score*100)}%</span></div><div className="kv"><span className="k">{t('labelEvidenceScore')}</span><span>{Math.round(c.verification.evidence_score*100)}%</span></div><div className="kv"><span className="k">{t('labelConsistencyScore')}</span><span>{Math.round(c.verification.consistency_score*100)}%</span></div><div className="kv"><span className="k">{t('labelFindings')}</span><span>{c.verification.findings.join(' · ')}</span></div></> : <p className="muted">{t('noVerification')}</p>}</div>
  </div>
  {c.action && <GovernedActionControls actionId={c.action.id} status={c.action.status}/>}
  {(c.execution_receipt || c.verification_receipt) && <div className="grid-2 section">
    {c.execution_receipt && <div className="card card-pad"><h3 style={{marginTop:0}}>{t('executionReceiptTitle')}</h3><div className="kv"><span className="k">{t('labelStatus')}</span><span className="badge ok">{c.execution_receipt.status}</span></div><div className="kv"><span className="k">{t('labelArtifact')}</span><span className="mono">{c.execution_receipt.artifact_ref || '—'}</span></div><div className="kv"><span className="k">{t('labelDigest')}</span><span className="mono">{c.execution_receipt.output_digest || '—'}</span></div></div>}
    {c.verification_receipt && <div className="card card-pad"><h3 style={{marginTop:0}}>{t('verificationReceiptTitle')}</h3><div className="kv"><span className="k">{t('labelStatus')}</span><span className="badge ok">{c.verification_receipt.status}</span></div><div className="kv"><span className="k">{t('labelArtifact')}</span><span className="mono">{c.verification_receipt.artifact_ref || '—'}</span></div><div className="kv"><span className="k">{t('labelDigest')}</span><span className="mono">{c.verification_receipt.artifact_digest || '—'}</span></div><div className="kv"><span className="k">{t('labelFindings')}</span><span>{c.verification_receipt.findings.join(' · ') || '—'}</span></div></div>}
  </div>}
  <div className="grid-2 section">
    <div className="card"><div className="section-title"><h3>{t('runsTitle')}</h3><span>{t('runsCount', { count: c.agent_runs.length })}</span></div><div className="card-pad workflow">{c.agent_runs.length ? c.agent_runs.map((a,i)=><div className="step" key={a.id}><div className="step-num">{String(i+1).padStart(2,'0')}</div><div><h4>{a.agent}</h4><p>{a.summary}</p></div><span className="badge ok">{a.status} · {a.duration_ms}ms</span></div>) : <p className="muted">{t('noRuns')}</p>}</div></div>
    <div className="card"><div className="section-title"><h3>{t('evidenceTitle')}</h3><span>{t('evidenceCount', { count: c.evidence.length })}</span></div><div className="card-pad">{c.evidence.length ? c.evidence.map(e=><div className="evidence" key={e.id}><div style={{display:'flex',justifyContent:'space-between',gap:10}}><h4>{e.title}</h4><span className={`badge ${e.verified?'ok':'medium'}`}>{Math.round(e.confidence*100)}%</span></div><p>{e.excerpt}</p><p className="mono" style={{marginTop:8}}>{e.source_type} · {e.source_ref}</p></div>) : <p className="muted">{t('noEvidence')}</p>}</div></div>
  </div>
  </>;
}
