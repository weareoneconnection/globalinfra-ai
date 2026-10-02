import Link from 'next/link';
import { getTranslations } from 'next-intl/server';
import { api } from '@/lib/api';
import { RiskBadge } from '@/components/RiskBadge';

type Case = { id:string; title:string; type:string; risk:string; status:string; project_name:string; deadline:string; detected_issues:string[] };
export default async function Cases() {
  const t = await getTranslations('Cases');
  const rows = await api<Case[]>('/cases');
  return <><div className="header-row"><div><div className="eyebrow">{t('eyebrow')}</div><h2 className="page-title">{t('title')}</h2><p className="page-subtitle">{t('subtitle')}</p></div><button className="button">{t('newCase')}</button></div><div className="card"><table className="table"><thead><tr><th>{t('colCase')}</th><th>{t('colProject')}</th><th>{t('colRisk')}</th><th>{t('colIssues')}</th><th>{t('colDeadline')}</th><th>{t('colStatus')}</th></tr></thead><tbody>{rows.map(c=><tr key={c.id}><td><Link href={`/cases/${c.id}`}><b className="mono">{c.id}</b></Link><div className="muted" style={{marginTop:4}}>{c.title}</div></td><td>{c.project_name}<div className="muted">{c.type}</div></td><td><RiskBadge risk={c.risk}/></td><td>{c.detected_issues.length}</td><td>{c.deadline}</td><td><span className="badge">{c.status}</span></td></tr>)}</tbody></table></div></>;
}
