import { getTranslations } from 'next-intl/server';
import { api } from '@/lib/api';
import { ApprovalButton } from '@/components/ApprovalButton';
import { RiskBadge } from '@/components/RiskBadge';

type Approval = { id:number; case_id:string; title:string; approver_role:string; status:string; risk:string; created_at:string };
export default async function Approvals() {
  const t = await getTranslations('Approvals');
  const rows = await api<Approval[]>('/approvals');
  return <><div className="header-row"><div><div className="eyebrow">{t('eyebrow')}</div><h2 className="page-title">{t('title')}</h2><p className="page-subtitle">{t('subtitle')}</p></div></div><div className="card"><table className="table"><thead><tr><th>{t('colCase')}</th><th>{t('colApproval')}</th><th>{t('colRisk')}</th><th>{t('colApprover')}</th><th>{t('colStatus')}</th><th>{t('colAction')}</th></tr></thead><tbody>{rows.map(a=><tr key={a.id}><td className="mono">{a.case_id}</td><td>{a.title}</td><td><RiskBadge risk={a.risk}/></td><td>{a.approver_role}</td><td><span className="badge">{a.status}</span></td><td>{a.status==='PENDING'?<div style={{display:'flex',gap:8}}><ApprovalButton id={a.id} action="approve"/><ApprovalButton id={a.id} action="reject"/></div>:<span className="muted">{t('recorded')}</span>}</td></tr>)}</tbody></table></div></>;
}
