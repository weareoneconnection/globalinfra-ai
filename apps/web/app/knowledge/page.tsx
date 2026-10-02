import { getTranslations } from 'next-intl/server';
import { api } from '@/lib/api';

type Doc = { id:number; title:string; category:string; jurisdiction:string; language:string; source_ref:string; summary:string };
export default async function Knowledge() {
  const t = await getTranslations('Knowledge');
  const docs = await api<Doc[]>('/knowledge?query=contract');
  return <><div className="header-row"><div><div className="eyebrow">{t('eyebrow')}</div><h2 className="page-title">{t('title')}</h2><p className="page-subtitle">{t('subtitle')}</p></div></div><div className="grid-2"><div className="card card-pad"><input className="search" defaultValue="contract" aria-label="search"/><div style={{marginTop:14}}>{docs.map(d=><div className="evidence" key={d.id}><h4>{d.title}</h4><p>{d.summary}</p><p className="mono" style={{marginTop:8}}>{d.category} · {d.jurisdiction} · {d.language} · {d.source_ref}</p></div>)}</div></div><div className="card card-pad"><div className="eyebrow">{t('graphEyebrow')}</div><h3>{t('graphTitle')}</h3><div className="codebox">{t('graphBody')}</div></div></div></>;
}
